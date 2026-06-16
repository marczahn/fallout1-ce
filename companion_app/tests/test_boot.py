"""Tests for the boot startup page and transition timeline."""
from __future__ import annotations

import unittest

import pygame

from companion_app.ui.console import CONSOLE_CHAR_INTERVAL_MS, TypewriterConsole
from companion_app.render import palette
from companion_app.ui.pages.boot import (
    BOOT_CONSOLE_MAX_LINES,
    BOOT_CURSOR_HOLD_MS,
    BOOT_READY_HOLD_MS,
    BOOT_TRANSCRIPT,
    BootPage,
    BootPhase,
    BootSequence,
    SPLASH_HOLD_MS,
    SplashPage,
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
        self.assertEqual(sequence.phase, BootPhase.SPLASH)

    def test_begin_preserves_full_transcript_with_boot_console_capacity(self) -> None:
        console = TypewriterConsole(max_lines=BOOT_CONSOLE_MAX_LINES)
        sequence = BootSequence()
        sequence.begin(console)

        self._drain_console(console)

        self.assertEqual(len(console.lines), len(BOOT_TRANSCRIPT))
        self.assertEqual(console.lines[0].text, BOOT_TRANSCRIPT[0])

    def test_splash_phase_holds_before_boot_begins(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence()

        result = sequence.tick(SPLASH_HOLD_MS - 1, console)

        self.assertFalse(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.SPLASH)
        self.assertEqual(len(console.lines), 0)

    def test_splash_phase_transitions_into_booting_after_delay(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence()

        result = sequence.tick(SPLASH_HOLD_MS, console)

        self.assertFalse(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.BOOTING)
        self.assertGreater(len(console.lines), 0)

    def test_boot_completion_enters_cursor_hold_without_clearing_console(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.BOOTING)
        sequence.begin(console)

        self._drain_console(console)
        result = sequence.tick(0, console)

        self.assertFalse(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.CURSOR_HOLD)
        self.assertGreater(len(console.lines), 0)
        self.assertTrue(console.show_idle_cursor)

    def test_cursor_hold_phase_starts_connect_after_delay(self) -> None:
        console = TypewriterConsole(show_idle_cursor=True)
        sequence = BootSequence(phase=BootPhase.CURSOR_HOLD)

        result = sequence.tick(BOOT_CURSOR_HOLD_MS, console)

        self.assertTrue(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.CONNECTING)
        self.assertFalse(console.show_idle_cursor)

    def test_connect_phase_waits_for_successful_connection(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.CONNECTING)

        result = sequence.tick(16, console)

        self.assertFalse(result.start_connect)
        self.assertFalse(sequence.show_main_ui)
        self.assertEqual(sequence.phase, BootPhase.CONNECTING)

    def test_connect_phase_enters_ready_hold_after_successful_connection(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.CONNECTING)

        result = sequence.tick(16, console, connection_ready=True)

        self.assertFalse(result.start_connect)
        self.assertFalse(sequence.show_main_ui)
        self.assertEqual(sequence.phase, BootPhase.READY_HOLD)

    def test_skip_from_splash_completes_boot_and_requests_connect(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence()

        result = sequence.skip(console)

        self.assertTrue(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.COMPLETE)
        self.assertTrue(sequence.show_main_ui)
        self.assertFalse(console.show_idle_cursor)

    def test_skip_finishes_existing_console_output(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.BOOTING)
        sequence.begin(console)
        console.tick(CONSOLE_CHAR_INTERVAL_MS)

        result = sequence.skip(console)

        self.assertTrue(result.start_connect)
        self.assertTrue(console.is_idle())
        self.assertTrue(all(line.typing_complete for line in console.lines))

    def test_skip_during_connecting_does_not_request_second_connect(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.CONNECTING)

        result = sequence.skip(console)

        self.assertFalse(result.start_connect)
        self.assertEqual(sequence.phase, BootPhase.COMPLETE)

    def test_ready_hold_completes_after_delay(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.READY_HOLD)

        result = sequence.tick(BOOT_READY_HOLD_MS, console)

        self.assertFalse(result.start_connect)
        self.assertTrue(sequence.show_main_ui)
        self.assertEqual(sequence.phase, BootPhase.COMPLETE)

    def test_ready_hold_waits_for_console_to_finish(self) -> None:
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.READY_HOLD)
        console.log("connected")

        result = sequence.tick(BOOT_READY_HOLD_MS, console)

        self.assertFalse(result.start_connect)
        self.assertFalse(sequence.show_main_ui)
        self.assertEqual(sequence.phase, BootPhase.READY_HOLD)

    def test_boot_page_renders_background(self) -> None:
        surface = pygame.Surface((480, 800))
        surface.fill((123, 45, 67))
        page = BootPage((480, 800))

        page.render(surface)

        px = tuple(surface.get_at((1, 1)))[:3]
        self.assertEqual(px, palette.BACKGROUND)

    def test_splash_page_renders_image_over_background(self) -> None:
        surface = pygame.Surface((480, 800))
        surface.fill((123, 45, 67))
        page = SplashPage()

        page.render(surface)

        self.assertEqual(tuple(surface.get_at((1, 1)))[:3], palette.BACKGROUND)
        self.assertNotEqual(tuple(surface.get_at((240, 400)))[:3], palette.BACKGROUND)

    def _drain_console(self, console: TypewriterConsole) -> None:
        for _ in range(64):
            if console.is_idle():
                return
            console.tick(CONSOLE_CHAR_INTERVAL_MS * 64)
        self.fail('console did not drain to idle')


if __name__ == '__main__':
    unittest.main()
