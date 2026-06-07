"""Unit tests for the locked input event vocabulary."""
from __future__ import annotations

import unittest


from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    SectionButtonEvent,
    make_event,
)


class MakeEventTests(unittest.TestCase):
    def test_section_buttons_carry_correct_index(self) -> None:
        for i in (1, 2, 3, 4):
            ev = make_event(f"SectionButton{i}")
            self.assertIsInstance(ev, SectionButtonEvent)
            self.assertEqual(ev.index, i)

    def test_encoder_left_right(self) -> None:
        self.assertIsInstance(make_event("EncoderLeft"), EncoderLeftEvent)
        self.assertIsInstance(make_event("EncoderRight"), EncoderRightEvent)

    def test_confirm_and_back(self) -> None:
        self.assertIsInstance(make_event("Confirm"), ConfirmEvent)
        self.assertIsInstance(make_event("Back"), BackEvent)

    def test_unknown_event_name_raises_keyerror(self) -> None:
        # Config layer is the public guard; make_event is internal and
        # treats unknown names as a programmer error.
        with self.assertRaises(KeyError):
            make_event("SectionButton5")
        with self.assertRaises(KeyError):
            make_event("Submit")

    def test_events_are_frozen_dataclasses(self) -> None:
        ev = SectionButtonEvent(index=1)
        with self.assertRaises(Exception):
            ev.index = 2  # type: ignore[misc]


if __name__ == "__main__":
    unittest.main()
