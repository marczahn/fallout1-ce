"""Unit tests for the TypewriterConsole panel."""
from __future__ import annotations

import unittest

import pygame

from companion_app.ui.console import (
    CONSOLE_CHAR_INTERVAL_MS,
    CONSOLE_CURSOR_GLYPH,
    CONSOLE_LINE_DELAY_MS,
    ConsoleLine,
    TypewriterConsole,
    _display_state,
)
from companion_app.render import palette
from companion_app.render.font import font_render_surface


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

    def test_log_appends_first_line_uppercased(self) -> None:
        c = TypewriterConsole()
        c.log('hello')
        self.assertEqual(len(c.lines), 1)
        self.assertEqual(c.lines[0].text, 'HELLO')

    def test_log_starts_animation(self) -> None:
        c = TypewriterConsole()
        c.log('hello')
        self.assertFalse(c.lines[0].typing_complete)
        self.assertEqual(c.lines[0].typed_chars, 0)

    def test_tick_advances_typing(self) -> None:
        c = TypewriterConsole()
        c.log('hello world')
        c.tick(CONSOLE_CHAR_INTERVAL_MS)
        self.assertGreater(c.lines[0].typed_chars, 0)

    def test_tick_completes_typing(self) -> None:
        c = TypewriterConsole()
        c.log('hi')
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len('HI') + 1)
        self.assertTrue(c.lines[0].typing_complete)
        self.assertEqual(c.lines[0].typed_chars, len('HI'))

    def test_second_line_waits_for_first_line(self) -> None:
        c = TypewriterConsole()
        c.log('first')
        c.log('second')
        self.assertEqual(len(c.lines), 1)
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len('FIRST') + 1)
        self.assertEqual(len(c.lines), 1)
        c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertEqual(len(c.lines), 2)
        self.assertEqual(c.lines[1].text, 'SECOND')

    def test_max_lines_capped(self) -> None:
        c = TypewriterConsole()
        for i in range(20):
            c.log(f'line {i}')
            c.tick(CONSOLE_CHAR_INTERVAL_MS * 20)
            c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertLessEqual(len(c.lines), 10)

    def test_custom_max_lines_capped(self) -> None:
        c = TypewriterConsole(max_lines=20)
        for i in range(25):
            c.log(f'line {i}')
            c.tick(CONSOLE_CHAR_INTERVAL_MS * 20)
            c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertLessEqual(len(c.lines), 20)

    def test_custom_max_lines_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            TypewriterConsole(max_lines=0)

    def test_lines_keep_order(self) -> None:
        c = TypewriterConsole()
        c.log('first')
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len('FIRST') + 1)
        c.log('second')
        c.tick(CONSOLE_LINE_DELAY_MS)
        self.assertEqual(c.lines[0].text, 'FIRST')
        self.assertEqual(c.lines[-1].text, 'SECOND')

    def test_draw_without_lines_no_error(self) -> None:
        c = TypewriterConsole()
        surface = pygame.Surface((480, 220))
        c.draw(surface)

    def test_visible_false_skips_draw(self) -> None:
        c = TypewriterConsole(visible=False)
        c.log('should not render')
        surface = pygame.Surface((480, 220))
        c.draw(surface)
        self.assertFalse(c.visible)

    def test_draw_does_not_add_header_or_border_lines(self) -> None:
        c = TypewriterConsole()
        c.log('hello')
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len('HELLO') + 1)
        surface = pygame.Surface((480, 220))
        surface.fill(palette.BACKGROUND)
        c.draw(surface, pygame.Rect(20, 20, 200, 80))
        self.assertEqual(tuple(surface.get_at((19, 19)))[:3], palette.BACKGROUND)

    def test_console_line_dataclass(self) -> None:
        ln = ConsoleLine(text='test', typed_chars=2, typing_complete=False)
        self.assertEqual(ln.text, 'test')
        self.assertEqual(ln.typed_chars, 2)
        self.assertFalse(ln.typing_complete)

    def test_is_idle_false_while_pending(self) -> None:
        c = TypewriterConsole()
        c.log('first')
        c.log('second')
        c.tick(CONSOLE_CHAR_INTERVAL_MS * len('FIRST') + 1)
        self.assertFalse(c.is_idle())

    def test_is_idle_true_when_all_lines_complete(self) -> None:
        c = TypewriterConsole()
        c.log('first')
        while not c.is_idle():
            c.tick(CONSOLE_CHAR_INTERVAL_MS * 10)
        self.assertTrue(c.is_idle())

    def test_display_state_appends_cursor_glyph_to_active_line(self) -> None:
        state = _display_state(
            ConsoleLine(text='BOOT', typed_chars=2, typing_complete=False),
            cursor_visible=True,
            is_active=True,
            is_last_visible=True,
            show_idle_cursor=False,
        )
        self.assertEqual(state.text, f'BO{CONSOLE_CURSOR_GLYPH}')

    def test_display_state_appends_idle_cursor_glyph_to_last_line(self) -> None:
        state = _display_state(
            ConsoleLine(text='READY', typed_chars=5, typing_complete=True),
            cursor_visible=True,
            is_active=False,
            is_last_visible=True,
            show_idle_cursor=True,
        )
        self.assertEqual(state.text, f'READY{CONSOLE_CURSOR_GLYPH}')

    def test_cursor_glyph_renders(self) -> None:
        rendered = font_render_surface(CONSOLE_CURSOR_GLYPH, 12, palette.FOREGROUND)
        self.assertIsNotNone(rendered)
        assert rendered is not None
        self.assertGreater(rendered.get_width(), 0)
        self.assertGreater(rendered.get_height(), 0)


if __name__ == '__main__':
    unittest.main()
