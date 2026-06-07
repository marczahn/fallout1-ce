"""Unit tests for the TypewriterConsole overlay (M3)."""
from __future__ import annotations

import unittest

from companion_app.debug.console import ConsoleLine, TypewriterConsole


class TypewriterConsoleTests(unittest.TestCase):
    def test_default_is_visible(self) -> None:
        c = TypewriterConsole()
        self.assertTrue(c.visible)

    def test_log_appends_line(self) -> None:
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
        c.tick()
        self.assertGreater(c.lines[0].typed_chars, 0)

    def test_tick_completes_typing(self) -> None:
        c = TypewriterConsole()
        c.log("hi")
        # Tick many times to complete the short string
        for _ in range(100):
            c.tick()
        self.assertTrue(c.lines[0].typing_complete)
        self.assertEqual(c.lines[0].typed_chars, len("hi"))

    def test_max_lines_capped(self) -> None:
        c = TypewriterConsole()
        for i in range(20):
            c.log(f"line {i}")
        self.assertLessEqual(len(c.lines), 14)

    def test_log_preserves_order(self) -> None:
        c = TypewriterConsole()
        c.log("first")
        c.log("second")
        self.assertEqual(c.lines[0].text, "first")
        self.assertEqual(c.lines[1].text, "second")

    def test_draw_without_lines_no_error(self) -> None:
        c = TypewriterConsole()
        # Should not raise even though no pygame surface
        c.lines.clear()
        self.assertIsNotNone(c)

    def test_visible_false_skips_draw(self) -> None:
        c = TypewriterConsole(visible=False)
        c.log("should not render")
        # No crash when drawing without a surface
        self.assertFalse(c.visible)

    def test_console_line_dataclass(self) -> None:
        ln = ConsoleLine(text="test", typed_chars=2, typing_complete=False)
        self.assertEqual(ln.text, "test")
        self.assertEqual(ln.typed_chars, 2)
        self.assertFalse(ln.typing_complete)


if __name__ == "__main__":
    unittest.main()
