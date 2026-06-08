"""Unit tests for the TypewriterConsole panel."""
from __future__ import annotations

import unittest

import pygame

from companion_app.debug.console import (
    CONSOLE_CHAR_INTERVAL_MS,
    CONSOLE_LINE_DELAY_MS,
    ConsoleLine,
    TypewriterConsole,
)
from companion_app.render import palette


class TypewriterConsoleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_default_is_visible(self) -> None:
        c = TypewriterConsole()
        self.assertTrue(c.visible)

    def test_log_appends_first_line(self) -> None:
        c = TypewriterConsole()
        c.log("hello")
        self.assertEqual(len(c.lines), 1)
        self.assertEqual(c.lines[0].text, "hello")

    def test_log_starts_animation(self) -> None:
        c = TypewriterConsole()
        c.log("hello")
        self.assertFalse(c.lines[0].typing_complete)
        self.assertEqual(c.lines[0].typed_chars, 0)

    def test_tick_advances_typing(self) -> None:
        c = TypewriterConsole()
        c.log("hello world")
        c.tick(CONSOLE_CHAR_INTERVAL_MS)
        self.assertGreater(c.lines[0].typed_chars, 0)

    def test_tick_completes_typing(self) -> None:
        c = TypewriterConsole()
        c.log("hi")
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len("hi") + 1)
        self.assertTrue(c.lines[0].typing_complete)
        self.assertEqual(c.lines[0].typed_chars, len("hi"))

    def test_second_line_waits_for_first_line(self) -> None:
        c = TypewriterConsole()
        c.log("first")
        c.log("second")
        self.assertEqual(len(c.lines), 1)
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len("first") + 1)
        self.assertEqual(len(c.lines), 1)
        c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertEqual(len(c.lines), 2)
        self.assertEqual(c.lines[1].text, "second")

    def test_max_lines_capped(self) -> None:
        c = TypewriterConsole()
        for i in range(20):
            c.log(f"line {i}")
            c.tick(CONSOLE_CHAR_INTERVAL_MS * 20)
            c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertLessEqual(len(c.lines), 10)

    def test_lines_keep_order(self) -> None:
        c = TypewriterConsole()
        c.log("first")
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len("first") + 1)
        c.log("second")
        c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertEqual(c.lines[0].text, "first")
        self.assertEqual(c.lines[-1].text, "second")

    def test_draw_without_lines_no_error(self) -> None:
        c = TypewriterConsole()
        surface = pygame.Surface((480, 220))
        c.draw(surface)

    def test_visible_false_skips_draw(self) -> None:
        c = TypewriterConsole(visible=False)
        c.log("should not render")
        surface = pygame.Surface((480, 220))
        c.draw(surface)
        self.assertFalse(c.visible)

    def test_draw_does_not_add_header_or_border_lines(self) -> None:
        c = TypewriterConsole()
        c.log("hello")
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len("hello") + 1)
        surface = pygame.Surface((480, 220))
        surface.fill(palette.BACKGROUND)
        c.draw(surface, pygame.Rect(20, 20, 200, 80))
        self.assertEqual(tuple(surface.get_at((19, 19)))[:3], palette.BACKGROUND)

    def test_console_line_dataclass(self) -> None:
        ln = ConsoleLine(text="test", typed_chars=2, typing_complete=False)
        self.assertEqual(ln.text, "test")
        self.assertEqual(ln.typed_chars, 2)
        self.assertFalse(ln.typing_complete)


if __name__ == "__main__":
    unittest.main()
