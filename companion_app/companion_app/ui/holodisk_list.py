"""ARCHIVES/HOLODISKS list and reader projection (TASK-025).

Turns ``player.holodisks`` into display rows for both levels of the holodisk
screen, and owns the rules that screen depends on. Pure data work: no pygame,
no ``AppState``, so the input router and the renderer both call it and unit
tests need no display. Mirrors ``quest_list`` and ``transmission_list``
exactly, and for the same reason: the engine half has no test target, so every
rule that *can* live app-side lives here where it is testable.

**This module owns level 1 only.** Level 2 — the document itself — is built in
``ui.pages.archives``, because how far a document scrolls depends on
soft-wrapping, which needs the font and the reader's geometry, and neither
belongs in a pygame-free module. Level-2 rows are one per *scroll position*,
so the cursor index is the index of the top visible line and one encoder click
moves the page by one line. The engine paginates this screen at 35 lines and
shows an "n of m" counter; the device deliberately does not, because paging is
too fiddly with one encoder and two buttons.

**Line breaks are authored, not incidental.** The engine stores each line as
its own message id, and disks 5 and 11 use leading whitespace for alignment
(indented measurements, and right-aligned timestamps). So a line is a row, and
nothing here reflows or strips them. Soft-wrapping an over-wide line is the
renderer's job, and it preserves the indent — see
``ui.pages.archives.wrap_body_line``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from companion_app.state import Holodisk
from companion_app.ui.scroll_list import ListRow

# Row-key prefixes. "H" is reserved for this module by
# ``transmission_list``'s own comment, and both are disjoint from
# ``quest_list``'s "L"/"Q" -- so a stale cursor from any one of the three
# ARCHIVES sub-sections can never resolve against another.
#
# Level-2 line rows take "HL", which cannot collide with a level-1 "H<n>"
# key even though it shares the first character: ``holodisk_index_from_key``
# parses the remainder as an int, and "L3" is not one.
_HOLODISK_PREFIX: str = "H"
_LINE_PREFIX: str = "HL"

# Shown in place of a title the server could not resolve. The server emits
# such a row rather than dropping it, so the failure has to be visible -- a
# missing row would silently disagree with the in-game screen.
NO_TITLE_LABEL: str = "[NO TITLE]"

# Level-1 empty state. Not "no holodisks": the app cannot distinguish "the
# player has found none" from "the server has not reported any yet".
EMPTY_TEXT: str = "NO ARCHIVE DATA"

# Level-2 state for a disk whose body arrived empty. That means the server
# could not resolve the text -- never that the disk has none, since all 18
# have some. The server assembles all-or-nothing precisely so this stays one
# unambiguous signal instead of a truncated document that looks whole.
NO_TEXT_TEXT: str = "DISK UNREADABLE"

# Characters the vendored face cannot draw legibly, mapped to ones it can.
#
# A table rather than a bare ``.replace()``: the next one must extend this,
# not add a second call site.
#
# U+2022 (bullet) is what the game's own text uses -- byte 0x95 in cp1252, on
# disks 0, 5, 8 and 12 -- and the engine now transcodes it correctly, but
# `jh_fallout-webfont.ttf` has no glyph for it at all
# (``get_metrics("•")`` returns ``[None]``).
#
# **U+00B7 (middle dot) is the wrong replacement even though it looks right
# on paper.** The face reports metrics for it, so it passes a naive
# "is the glyph present" check -- but it renders as a filled 14x19 block,
# not a dot. Caught by rendering the real disk-0 text and looking at it;
# a metrics check alone would have shipped a page of boxes. ASCII "*" has
# genuinely distinct metrics, is the conventional plain-text bullet, and is
# verified by eye.
_GLYPH_SUBSTITUTIONS: dict[str, str] = {
    "•": "*",
}


def renderable(line: str) -> str:
    """``line`` with characters the vendored font cannot draw substituted."""
    for missing, replacement in _GLYPH_SUBSTITUTIONS.items():
        line = line.replace(missing, replacement)
    return line


def holodisk_key(index: int) -> str:
    """Stable level-1 row key for a holodisk table index."""
    return f"{_HOLODISK_PREFIX}{index}"


def holodisk_index_from_key(key: str) -> int | None:
    """Inverse of :func:`holodisk_key`; ``None`` for anything else.

    Round-trips, which is what makes a key as stable as an index across the
    wholesale list replacement the client performs on every update. A level-2
    line key ("HL3") returns ``None`` here, which is what keeps the two levels
    from ever being confused.
    """
    if not key.startswith(_HOLODISK_PREFIX):
        return None
    try:
        return int(key[len(_HOLODISK_PREFIX):])
    except ValueError:
        return None


def line_key(line_number: int) -> str:
    """Stable level-2 row key for a body line."""
    return f"{_LINE_PREFIX}{line_number}"


@dataclass(frozen=True)
class HolodiskRow:
    """One projected level-1 row."""

    key: str
    index: int
    title: str


def project(holodisks: Sequence[Holodisk]) -> list[HolodiskRow]:
    """Project found holodisks into rows, in engine table order.

    Order is the engine's own table index, matching the in-game STATUS
    screen's disk column, so the two lists never disagree about sequence.

    **No ``(n)`` duplicate-label suffix**, unlike ``transmission_list``: all 18
    holodisk titles are distinct, verified by extraction, whereas two movies
    genuinely share "Leaving Vault". Row identity is the index either way, so
    nothing depends on the label being unique.
    """
    return [
        HolodiskRow(
            key=holodisk_key(holodisk.index),
            index=holodisk.index,
            title=renderable(holodisk.title) if holodisk.title else NO_TITLE_LABEL,
        )
        for holodisk in sorted(holodisks, key=lambda item: item.index)
    ]


def list_rows(holodisks: Sequence[Holodisk]) -> list[ListRow]:
    """Selectable level-1 rows for the scroll list / input router."""
    return [ListRow(key=row.key, label=row.title) for row in project(holodisks)]


def disk_for_key(holodisks: Sequence[Holodisk], key: str) -> Holodisk | None:
    """The holodisk a level-1 row key identifies, or ``None``."""
    index = holodisk_index_from_key(key)
    if index is None:
        return None
    for holodisk in holodisks:
        if holodisk.index == index:
            return holodisk
    return None


def row_for_key(holodisks: Sequence[Holodisk], key: str) -> HolodiskRow | None:
    for row in project(holodisks):
        if row.key == key:
            return row
    return None


# Level-2 rows are **not** built here, deliberately. They are one row per
# scroll position, and how far a document scrolls depends on soft-wrapping,
# which needs the font and the reader's geometry — neither of which belongs in
# this pygame-free module. See `ui.pages.archives.reader_scroll_rows`.
#
# The first implementation did put them here, one row per authored line, and
# let `scroll_list.visible` choose the window. That centres the selection,
# which is correct for a list drawing a selection box and wrong for a document
# drawing none: the page did not move for the first 26 encoder clicks. Caught
# on the device, not by the suite.
