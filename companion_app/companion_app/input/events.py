"""Input event vocabulary for the companion app.

The companion app has exactly five logical input events:

- ``SectionButtonEvent(index)`` with ``index`` in ``{1, 2, 3, 4}``
- ``EncoderLeftEvent``
- ``EncoderRightEvent``
- ``ConfirmEvent``
- ``BackEvent``

This vocabulary is locked. Any future input backend (hardware
GPIO/serial, scripted test stub, ...) must implement::

    poll(pygame_events) -> list[InputEvent]

and may produce zero or more events per frame. No other event types
are allowed to flow through this surface.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Union


@dataclass(frozen=True)
class SectionButtonEvent:
    index: int


@dataclass(frozen=True)
class EncoderLeftEvent:
    pass


@dataclass(frozen=True)
class EncoderRightEvent:
    pass


@dataclass(frozen=True)
class ConfirmEvent:
    pass


@dataclass(frozen=True)
class BackEvent:
    pass


InputEvent = Union[
    SectionButtonEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    ConfirmEvent,
    BackEvent,
]


# Map event-name strings (as used in the config keymap) to the
# factory that produces the corresponding InputEvent instance.
_EVENT_FACTORIES = {
    "SectionButton1": lambda: SectionButtonEvent(1),
    "SectionButton2": lambda: SectionButtonEvent(2),
    "SectionButton3": lambda: SectionButtonEvent(3),
    "SectionButton4": lambda: SectionButtonEvent(4),
    "EncoderLeft":    EncoderLeftEvent,
    "EncoderRight":   EncoderRightEvent,
    "Confirm":        ConfirmEvent,
    "Back":           BackEvent,
}


def make_event(event_name: str) -> InputEvent:
    """Build an InputEvent from its config-level event name.

    Raises KeyError on unknown names. The config loader is expected to
    have already validated names against ``VALID_EVENT_NAMES``, so a
    KeyError here is a programmer error, not user input.
    """
    return _EVENT_FACTORIES[event_name]()
