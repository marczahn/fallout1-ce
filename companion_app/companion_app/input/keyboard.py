"""Pygame keyboard backend for the locked input vocabulary (M1).

Translates ``KEYDOWN`` events into ``InputEvent`` instances using the
keymap resolved by :mod:`companion_app.config`. ``KEYUP`` is ignored.
Key repeat is filtered at the pygame level (``set_repeat(0)`` in
``app.py``), so each physical press produces exactly one event.

This is the only input backend that ships in M1. A future hardware
backend will implement the same ``poll`` shape.
"""
from __future__ import annotations

from typing import Iterable

from companion_app.input.events import InputEvent, make_event


class KeyboardInput:
    """Stateless-per-frame mapping from pygame events to InputEvents."""

    def __init__(self, keymap: dict[str, list[int]]) -> None:
        # Invert the event -> [keys] map into key -> event_name so
        # lookup per pygame KEYDOWN is O(1). If a single key code is
        # bound to multiple events (last-one-wins via dict insertion),
        # warn-quietly is overkill for M1; just take the first binding
        # encountered. The config validator will catch nonsense.
        self._key_to_event: dict[int, str] = {}
        for event_name, codes in keymap.items():
            for code in codes:
                # First binding wins; later duplicates are ignored.
                self._key_to_event.setdefault(code, event_name)

    def poll(self, pygame_events: Iterable) -> list[InputEvent]:
        import pygame

        out: list[InputEvent] = []
        for ev in pygame_events:
            if ev.type != pygame.KEYDOWN:
                continue
            event_name = self._key_to_event.get(ev.key)
            if event_name is None:
                continue
            out.append(make_event(event_name))
        return out
