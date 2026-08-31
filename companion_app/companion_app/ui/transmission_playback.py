"""Playback control for the transmission screen (TASK-024 F6a).

Where the audio *side effects* live. They cannot live in ``sections.py``:
``handle_input`` and ``deactivated`` are pure functions returning a new
frozen ``SectionsUiState`` and hold no reference to a sink. The
Independent Reviewer Gate caught an earlier draft of the plan putting
them there.

So the frame loop owns the sink and calls :func:`apply` once per input
event, plus :func:`sync` once per frame for the transitions no event
produces — a disconnect, or a track reaching its end.

The transport reads the *input event* rather than diffing a state field.
Pausing and seeking deliberately change no UI state at all: position and
paused-ness are the sink's, and mirroring them into ``SectionsUiState``
would create two sources of truth that drift the moment SDL disagrees.
What the diff *is* used for is entry and exit — which disk is open — which
is genuinely UI state.
"""
from __future__ import annotations

from companion_app.input.events import (
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    InputEvent,
)
from companion_app.state import AppState, ConnectionState
from companion_app.ui import transmission_list, sections
from companion_app.ui.sections import ARCHIVES_TRANSMISSIONS, Page, SectionsUiState

# One encoder step. Deliberately coarse: this is a physical rotary control
# on a handheld device, not a scrub bar.
SEEK_STEP_MS: int = 5000


def open_disk_index(page: Page, ui: SectionsUiState) -> int | None:
    """Table index of the transmission currently open at level 2, if any."""
    if page is not Page.ARCHIVES:
        return None
    seg = sections.for_page(ui, page)
    if seg.selected_key != ARCHIVES_TRANSMISSIONS:
        return None
    if not ui.activated:
        return None
    key = sections.drill_key_for(ui, page, seg.selected_key)
    if not key:
        return None
    return transmission_list.transmission_index_from_key(key)


def apply(
    sink,
    before_page: Page,
    before_ui: SectionsUiState,
    after_page: Page,
    after_ui: SectionsUiState,
    input_event: InputEvent,
    state: AppState,
) -> None:
    """Issue sink calls for one routed input event."""
    before_index = open_disk_index(before_page, before_ui)
    after_index = open_disk_index(after_page, after_ui)

    if before_index != after_index:
        # Entered, left, or switched disks. Leaving always stops AND
        # resets — re-opening starts from the beginning, never from where
        # it was paused.
        sink.stop()
        if after_index is not None:
            recording = state.transmission_audio.recordings.get(after_index)
            if recording is not None:
                sink.play(recording.path, recording.duration_ms)
        return

    if after_index is None:
        return

    # Still on the same open disk: the transport gestures.
    if isinstance(input_event, ConfirmEvent):
        sink.toggle_pause()
    elif isinstance(input_event, EncoderLeftEvent):
        sink.seek_by(-SEEK_STEP_MS)
    elif isinstance(input_event, EncoderRightEvent):
        sink.seek_by(SEEK_STEP_MS)


def sync(sink, page: Page, ui: SectionsUiState, state: AppState) -> None:
    """Per-frame reconciliation for transitions no input event produces.

    Two of them: the connection dropping (which never passes through input
    routing at all), and a track running to its end.
    """
    if state.connection is not ConnectionState.READY:
        sink.stop()
        return
    if open_disk_index(page, ui) is None:
        sink.stop()
        return
    sink.tick()
