"""ARCHIVES/TRANSMISSIONS list projection (TASK-024).

Turns ``player.transmissions`` into display rows for level 1 of the transmission
screen, and owns the rules that screen depends on. Pure data work: no
pygame, no ``AppState``, so the input router and the renderer both call it
and unit tests need no display. Mirrors ``quest_list``'s role exactly, and
for the same reason: the engine half has no test target, so every rule
that can live app-side lives here where it is testable.

**One level of rows, not two.** Unlike ``quest_list``, level 2 has no
list at all — it is a player. So this module projects level 1 only, and
``sections.py``'s drill depth stores which disk is open. The encoder is
consequently state-inert at level 2 (no rows to move through), which is
what frees that gesture for seeking.

**Availability and bakedness are separate, and only meet here.** Which
disks exist comes from the engine (`player.transmissions`, live GVAR state);
which disks have a recording comes from the audio sync's manifest, which
is fetched independently of game state. A disk is listed on availability
alone — never filtered by whether audio arrived — and playability is a
*property of the row*, not a condition for showing it. See the TASK-024
fetch-on-connect decision for why those two sources are kept apart.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from companion_app.state import Transmission, TransmissionAudioState, TransmissionSyncStatus
from companion_app.ui.scroll_list import ListRow

# Row-key prefix. Disjoint from ``quest_list``'s ("L"/"Q") **and** from
# the holodisk list TASK-025 will add ("H"), so a stale cursor from any
# one of the three ARCHIVES sub-sections can never resolve against
# another. Getting this wrong is not hypothetical: this module was itself
# the holodisk list until TASK-024's subject correction, and kept "H"
# through the rename until a render check caught it.
_TRANSMISSION_PREFIX: str = "T"

# Shown in place of a title the server could not resolve. The server emits
# such a row with an empty title rather than dropping it, so the failure
# has to be visible — a blank row reads as a rendering bug and a missing
# row would silently disagree with the in-game Archives screen.
NO_TITLE_LABEL: str = "[NO TITLE]"

# Level-1 empty state. Not "no transmissions": the app cannot distinguish
# "the player has found none" from "the server has not reported any yet".
EMPTY_TEXT: str = "NO ARCHIVE DATA"

# Level-2 state when the selected disk has no playable recording. Covers
# all three causes without distinguishing them, by decision: an
# unreachable filler disk, a disk not yet baked, and a disk whose audio is
# still in flight. The sync completes in well under a second, so the third
# is not worth a state of its own.
NO_RECORD_TEXT: str = "NO RECORD AVAILABLE"

# Level-2 state while the on-connect sync is still running and this disk
# has not landed yet. Distinguished from NO_RECORD_TEXT only because a
# sync that is still running may yet produce the recording.
SYNCING_TEXT: str = "SYNCING ARCHIVES"


def transmission_key(index: int) -> str:
    """Stable row key for a transmission table index."""
    return f"{_TRANSMISSION_PREFIX}{index}"


def transmission_index_from_key(key: str) -> int | None:
    """Inverse of :func:`transmission_key`; ``None`` for anything else.

    Round-trips, which is what makes a key as stable as an index across
    the wholesale list replacement the client performs on every update.
    """
    if not key.startswith(_TRANSMISSION_PREFIX):
        return None
    try:
        return int(key[len(_TRANSMISSION_PREFIX):])
    except ValueError:
        return None


@dataclass(frozen=True)
class TransmissionRow:
    """One projected level-1 row."""

    key: str
    index: int
    title: str
    playable: bool


def project(
    transmissions: Sequence[Transmission],
    audio: TransmissionAudioState,
) -> list[TransmissionRow]:
    """Project found transmissions into rows, in engine table order.

    Order is the engine's own table index, matching the in-game Archives
    screen, so the two lists never disagree about sequence.

    **Repeated labels get a ``(n)`` suffix from the second occurrence on.**
    ``MOVIE_WALKM`` and ``MOVIE_WALKW`` genuinely share the title "Leaving
    Vault" -- both resolve message ``500 + movie`` -- so without this the
    screen shows two identical rows and the player cannot tell them apart.
    Display only: ``key`` and ``index`` still carry identity, so selection
    and playback never depend on the label. Deterministic, because the walk
    is in sorted index order.
    """
    rows: list[TransmissionRow] = []
    seen: dict[str, int] = {}
    for transmission in sorted(transmissions, key=lambda item: item.index):
        label = transmission.title if transmission.title else NO_TITLE_LABEL
        occurrence = seen.get(label, 0)
        seen[label] = occurrence + 1
        rows.append(
            TransmissionRow(
                key=transmission_key(transmission.index),
                index=transmission.index,
                title=label if occurrence == 0 else f"{label} ({occurrence})",
                playable=audio.has_recording(transmission.index),
            )
        )
    return rows


def list_rows(
    transmissions: Sequence[Transmission],
    audio: TransmissionAudioState,
) -> list[ListRow]:
    """Selectable rows for the scroll list / input router."""
    return [ListRow(key=row.key, label=row.title) for row in project(transmissions, audio)]


def row_for_key(
    transmissions: Sequence[Transmission],
    audio: TransmissionAudioState,
    key: str,
) -> TransmissionRow | None:
    for row in project(transmissions, audio):
        if row.key == key:
            return row
    return None


def unavailable_text(audio: TransmissionAudioState) -> str:
    """Level-2 message for a disk with no recording.

    ``SYNCING`` only while the sync could still deliver it; otherwise the
    single ``NO RECORD AVAILABLE`` state.
    """
    if audio.status in (TransmissionSyncStatus.IDLE, TransmissionSyncStatus.FETCHING):
        return SYNCING_TEXT
    return NO_RECORD_TEXT
