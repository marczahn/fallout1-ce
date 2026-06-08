"""Tests for the boot startup page and transition timeline."""
from __future__ import annotations

import unittest

import pygame

from companion_app.debug.console import CONSOLE_CHAR_INTERVAL_MS, TypewriterConsole
from companion_app.render import palette
from companion_app.ui.pages.boot import (
    BOOT_CURSOR_HOLD_MS,
    REDIRECT_HOLD_MS,
    BootPage,
    BootPhase,
    BootSequence,
    REDIRECT_LINE,
)


class BootSequenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_begin_queues_boot_transcript(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence()
        sequence.begin(console)
        self.assertGreater(len(console.lines), 0)
        self.assertEqual(sequence.phase, BootPhase.BOOTING)

    def test_boot_completion_clears_console_then_enters_wait_phase(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence()
        sequence.begin(console)

        self._drain_console(console)
        result = sequence.tick(0, console)

        self.assertTrue(result.clear_console)
        self.assertEqual(sequence.phase, BootPhase.CLEARING)
        self.assertEqual(len(console.lines), 0)
        self.assertTrue(console.show_idle_cursor)

    def test_clearing_phase_starts_connect_after_delay(self) -> None:
        console = TypewriterConsole(show_idle_cursor=True)
        sequence = BootSequence(phase=BootPhase.CLEARING)

        result = sequence.tick(BOOT_CURSOR_HOLD_MS, console)

        self.assertTrue(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.CONNECTING)
        self.assertFalse(console.show_idle_cursor)

    def test_connect_phase_logs_redirect_when_console_finishes(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.CONNECTING)

        result = sequence.tick(16, console)

        self.assertTrue(result.log_redirect)
        self.assertEqual(sequence.phase, BootPhase.REDIRECTING)

    def test_redirect_phase_completes_after_redirect_line_and_hold(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.REDIRECTING)
        console.log(REDIRECT_LINE)
        self._drain_console(console)

        result = sequence.tick(REDIRECT_HOLD_MS, console)

        self.assertTrue(result.show_main_ui)
        self.assertTrue(sequence.show_main_ui)
        self.assertEqual(sequence.phase, BootPhase.COMPLETE)

    def test_boot_page_renders_background(self) -> None:
        surface = pygame.Surface((480, 800))
        surface.fill((123, 45, 67))
        page = BootPage((480, 800))

        page.render(surface)

        px = tuple(surface.get_at((1, 1)))[:3]
        self.assertEqual(px, palette.BACKGROUND)

    def _drain_console(self, console: TypewriterConsole) -> None:
        for _ in range(64):
            if console.is_idle():
                return
            console.tick(CONSOLE_CHAR_INTERVAL_MS * 64)
        self.fail('console did not drain to idle')


if __name__ == '__main__':
    unittest.main()
