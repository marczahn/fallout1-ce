"""Unit tests for the M1 debug event overlay."""
from __future__ import annotations

import unittest


import pygame

from companion_app.debug.event_log import EventLogOverlay
from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    SectionButtonEvent,
)


class EventLogOverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_empty_overlay_draws_without_crash(self) -> None:
        overlay = EventLogOverlay()
        surf = pygame.Surface((480, 800))
        overlay.draw(surf)  # must not raise

    def test_records_appear_in_fifo_order(self) -> None:
        overlay = EventLogOverlay()
        a, b, c = SectionButtonEvent(1), EncoderLeftEvent(), ConfirmEvent()
        for e in (a, b, c):
            overlay.record(e)
        self.assertEqual(list(overlay._events), [a, b, c])

    def test_capacity_caps_at_ten_and_drops_oldest(self) -> None:
        overlay = EventLogOverlay()
        events = [SectionButtonEvent(index=(i % 4) + 1) for i in range(15)]
        for e in events:
            overlay.record(e)
        kept = list(overlay._events)
        self.assertEqual(len(kept), 10)
        # Oldest 5 dropped, newest 10 kept in original order.
        self.assertEqual(kept, events[-10:])

    def test_custom_capacity_is_honored(self) -> None:
        overlay = EventLogOverlay(maxlen=3)
        for i in range(5):
            overlay.record(BackEvent())
        self.assertEqual(len(overlay._events), 3)

    def test_draw_after_records_produces_pixels(self) -> None:
        overlay = EventLogOverlay()
        overlay.record(ConfirmEvent())
        surf = pygame.Surface((480, 800))
        surf.fill((0, 0, 0))
        overlay.draw(surf)
        # At least one non-black pixel exists in the bottom region where
        # the overlay renders. Sampling avoids a numpy dep.
        found_pixel = False
        for y in range(750, 800):
            for x in range(0, 200):
                if surf.get_at((x, y))[:3] != (0, 0, 0):
                    found_pixel = True
                    break
            if found_pixel:
                break
        self.assertTrue(found_pixel, "overlay drew no visible pixels")


if __name__ == "__main__":
    unittest.main()
