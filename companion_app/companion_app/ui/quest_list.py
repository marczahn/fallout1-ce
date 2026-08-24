"""ARCHIVES/QUESTS list projection (TASK-021).

Turns ``player.quests`` into display rows for a **two-level** list, and
owns every rule the screen depends on. Pure data work: no pygame, no
``AppState``, so both the input router and the renderer call it and unit
tests need no display. Mirrors ``inventory_list``'s role exactly.

**Why so much lives here.** The engine side of this feature has no test
target at all — ``CMakeLists.txt`` declares one executable and no tests —
so the C++ half was deliberately kept a thin read (walk the table, read
the variables, copy the strings) and every rule that *can* be expressed
app-side is expressed here, where it is testable.

**Two levels, not one.** Level 1 is the location list; ``Confirm`` drills
into a location; level 2 is that location's quest lines; ``Back`` comes
back. This mirrors the in-game Pip-Boy's own quest screen. It does not
resurrect the root/detail model TASK-017 deleted: that was navigation
*between sub-sections*, and sub-sections still switch immediately on the
encoder. Drill-down here happens strictly *inside* activated content.

**Row keys are the navigation state.** ``sections.py`` stores the drilled
location as a level-1 row key rather than an index, so it needs no decoder
of its own and keeps importing no projection module. The keys are pure
functions of the location index and round-trip through
``location_index_from_key``, which is what makes them as stable as an
index across the wholesale quest-list replacement the client performs.

**The water countdown's row is found via the server's flag.** No GVAR
index crosses the wire, so the app cannot compute which quest the Vault 13
countdown belongs to; the server marks it with ``water_chip`` and
``water_row_key`` reads that. There is deliberately no client-side table
mapping quests to the water chip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from companion_app.state import PlayerState, Quest
from companion_app.ui.scroll_list import ListRow

# Row-key prefixes. Level 1 and level 2 keys never mix in one list, but
# they are still disjoint so a stale cursor from one level can never
# resolve against the other.
_LOCATION_PREFIX: str = "L"
_QUEST_PREFIX: str = "Q"

# Shown in place of a quest line the server could not resolve. The server
# emits such a row with an empty ``text`` rather than dropping it, so the
# failure has to be visible here — a blank row would read as a rendering
# bug, and a missing row would silently disagree with the in-game screen
# with no symptom at all.
NO_TEXT_LABEL: str = "[NO TEXT]"

# Level-1 empty state. Not "no quests": the app cannot distinguish "the
# player has none" from "the server has not reported any yet".
EMPTY_TEXT: str = "NO QUEST DATA"

WATER_PREFIX: str = "WATER: "
WATER_SECURED: str = f"{WATER_PREFIX}SECURED"
WATER_DEPLETED: str = f"{WATER_PREFIX}DEPLETED"


def location_row_key(location_index: int) -> str:
    """Level-1 row key for a location."""
    return f"{_LOCATION_PREFIX}{location_index}"


def quest_row_key(location_index: int, slot: int) -> str:
    """Level-2 row key: the ``(location_index, slot)`` wire identity."""
    return f"{_QUEST_PREFIX}{location_index}.{slot}"


def location_index_from_key(key: str) -> int | None:
    """Inverse of ``location_row_key``, or ``None`` if ``key`` is not one.

    Returns ``None`` rather than raising, because the caller's fallback is
    to show level 1 — a key that no longer decodes should pop the screen up
    a level, not crash it.
    """
    if not key.startswith(_LOCATION_PREFIX):
        return None
    digits = key[len(_LOCATION_PREFIX) :]
    if not digits.isdigit():
        return None
    return int(digits)


def location_indexes(quests: Sequence[Quest]) -> tuple[int, ...]:
    """Location indexes that have at least one visible quest, ascending.

    A location whose every slot is empty contributes nothing to
    ``player.quests`` at all, so it cannot appear here — which is how the
    engine's four all-zero locations stay unreachable without this module
    knowing they exist.
    """
    return tuple(sorted({quest.location_index for quest in quests}))


def quests_for_location(
    quests: Sequence[Quest],
    location_index: int,
) -> tuple[Quest, ...]:
    """That location's quests in slot order."""
    return tuple(
        sorted(
            (q for q in quests if q.location_index == location_index),
            key=lambda q: q.slot,
        )
    )


def location_label(quests: Sequence[Quest], location_index: int) -> str:
    """The engine's own Pip-Boy name for a location.

    Taken from the first quest reporting it, since the server stamps every
    row of a location with the same name. Falls back to the row key so a
    location whose name failed to resolve is still navigable rather than
    becoming an unlabelled row.
    """
    for quest in quests:
        if quest.location_index == location_index and quest.location:
            return quest.location
    return location_row_key(location_index)


def location_counts(
    quests: Sequence[Quest],
    location_index: int,
) -> tuple[int, int, int]:
    """``(active, completed, total)`` for one location.

    Free from the same walk the rows need, and what makes level 1 worth
    looking at rather than a bare list of place names.
    """
    entries = quests_for_location(quests, location_index)
    completed = sum(1 for quest in entries if quest.completed)
    return len(entries) - completed, completed, len(entries)


def build_location_rows(quests: Sequence[Quest]) -> tuple[ListRow, ...]:
    """Level 1: one selectable row per location that has a visible quest.

    No headings at this level, so there is nothing for the cursor to skip.
    """
    rows: list[ListRow] = []
    for location_index in location_indexes(quests):
        _active, completed, total = location_counts(quests, location_index)
        rows.append(
            ListRow(
                key=location_row_key(location_index),
                label=f"{location_label(quests, location_index)} {completed}/{total}",
                selectable=True,
            )
        )
    return tuple(rows)


def build_quest_rows(
    quests: Sequence[Quest],
    location_index: int,
) -> tuple[ListRow, ...]:
    """Level 2: that location's quest lines, in slot order."""
    return tuple(
        ListRow(
            key=quest_row_key(quest.location_index, quest.slot),
            label=quest.text if quest.text else NO_TEXT_LABEL,
            selectable=True,
        )
        for quest in quests_for_location(quests, location_index)
    )


def quest_for_key(quests: Sequence[Quest], key: str) -> Quest | None:
    """The quest a level-2 row key points at, or ``None``."""
    for quest in quests:
        if quest_row_key(quest.location_index, quest.slot) == key:
            return quest
    return None


def water_row_key(quests: Sequence[Quest]) -> str:
    """Level-2 row key of the water-chip quest, or ``""`` if not visible.

    The server's ``water_chip`` flag is the only source: see the module
    docstring on why the app never derives this itself.
    """
    for quest in quests:
        if quest.water_chip:
            return quest_row_key(quest.location_index, quest.slot)
    return ""


@dataclass(frozen=True)
class WaterDisplay:
    """The water countdown as one label plus whether it is a live number."""

    label: str
    running: bool


def water_state(player: PlayerState) -> WaterDisplay:
    """The Vault 13 countdown's label, from one place.

    Three branches cover four states, and that is the point:

    ==================================  =====================
    Condition                           Label
    ==================================  =====================
    not ``countdown_active``            ``WATER: SECURED``
    active and ``days_remaining > 0``   ``WATER: N DAYS``
    active and ``days_remaining <= 0``  ``WATER: DEPLETED``
    ==================================  =====================

    The **divergent** state — the engine's water-chip variable above 2,
    where the Pip-Boy's completion rule (``> 1``) and the countdown's own
    guard (``!= 2``) disagree — needs no fourth branch: the server sends
    ``completed=True`` *and* ``countdown_active=True``, so the quest
    renders struck through while the label still reads ``N DAYS``. Two
    independent signals, honestly reported, rather than one invented merged
    state. See ``test_quest_list`` for the case that pins this.

    ``SECURED`` and ``DEPLETED`` are words, never numbers. A frozen day
    count left on screen after the chip is delivered would read as a live
    deadline, and ``0 DAYS`` would read as "you still have today" when the
    engine has already reached its losing state.
    """
    if not player.water.countdown_active:
        return WaterDisplay(label=WATER_SECURED, running=False)
    if player.water.days_remaining <= 0:
        return WaterDisplay(label=WATER_DEPLETED, running=False)
    return WaterDisplay(
        label=f"{WATER_PREFIX}{player.water.days_remaining} DAYS",
        running=True,
    )
