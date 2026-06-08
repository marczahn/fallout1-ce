"""Smoke tests for the STATUS page (UI refactoring).

Uses a real (offscreen) pygame Surface. No display needed.
"""
from __future__ import annotations

import unittest

import pygame

from companion_app.state import AppState, ConnectionState, PlayerState
from companion_app.ui.layout import Layout
from companion_app.ui.pages.status import StatusPage


class StatusPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.surface = pygame.Surface((480, 800))
        self.layout = Layout((480, 800))
        self.page = StatusPage()

    def _make_state(
        self,
        hp: int = 50,
        max_hp: int = 100,
        available: bool = True,
    ) -> AppState:
        return AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=available, hp=hp, max_hp=max_hp),
        )

    def test_draws_hp_when_available(self) -> None:
        self.page.render(
            self.surface, self.layout.content_rect, self._make_state(hp=73, max_hp=100),
        )

    def test_draws_hp_with_zero_values(self) -> None:
        self.page.render(
            self.surface, self.layout.content_rect, self._make_state(hp=0, max_hp=0),
        )

    def test_draws_hp_full_health(self) -> None:
        self.page.render(
            self.surface,
            self.layout.content_rect,
            self._make_state(hp=100, max_hp=100),
        )

    def test_render_called_multiple_times(self) -> None:
        for _ in range(10):
            self.page.render(
                self.surface,
                self.layout.content_rect,
                self._make_state(hp=50, max_hp=50),
            )


if __name__ == "__main__":
    unittest.main()
