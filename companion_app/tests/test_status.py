"""Smoke tests for the STATUS section renderer (M4).

Uses a real (offscreen) pygame Surface. No display needed.
"""
from __future__ import annotations

import unittest

import pygame

from companion_app.ui.status import draw_status


class DrawStatusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.surface = pygame.Surface((480, 800))

    def test_draws_no_signal_when_unavailable(self) -> None:
        draw_status(self.surface, player_available=False, hp=50, max_hp=100)
        # No crash — no assertion needed beyond not raising.

    def test_draws_hp_when_available(self) -> None:
        draw_status(self.surface, player_available=True, hp=73, max_hp=100)
        # Smoke test — verifies the function does not raise.

    def test_draws_hp_with_zero_values(self) -> None:
        draw_status(self.surface, player_available=True, hp=0, max_hp=0)
        # Edge case: dead character.

    def test_draws_hp_max_hp_zero_still_renders(self) -> None:
        draw_status(self.surface, player_available=True, hp=100, max_hp=100)
        # Full health.

    def test_draws_no_signal_called_multiple_times(self) -> None:
        for _ in range(10):
            draw_status(self.surface, player_available=False, hp=0, max_hp=0)
            draw_status(self.surface, player_available=True, hp=50, max_hp=50)


if __name__ == "__main__":
    unittest.main()
