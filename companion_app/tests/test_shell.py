"""Tests for the Layout screen chrome (UI refactoring)."""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import palette
from companion_app.ui.layout import Layout
from companion_app.ui.pages import Page
from companion_app.ui.shell import (
    BODY_SIZE,
    HEADER_HEIGHT,
    HEADER_SIZE,
    VIRTUAL_HEIGHT,
    VIRTUAL_WIDTH,
)


class LayoutTest(unittest.TestCase):
    def setUp(self) -> None:
        if not pygame.display.get_init():
            pygame.display.init()
        self.surface = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
        self.layout = Layout((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    def test_draw_fills_background(self) -> None:
        self.surface.fill((123, 45, 67))
        self.layout.draw(self.surface, Page.STATUS, '--')
        px = tuple(self.surface.get_at((1, 1)))[:3]
        self.assertEqual(px, palette.BACKGROUND)

    def test_content_rect_starts_after_header_band(self) -> None:
        r = self.layout.content_rect
        self.assertEqual(r.top, 56)
        self.assertEqual(r.width, VIRTUAL_WIDTH)
        self.assertEqual(r.height, VIRTUAL_HEIGHT - 56)

    def test_console_rect_sits_inside_content_rect(self) -> None:
        self.assertTrue(self.layout.content_rect.contains(self.layout.console_rect))

    def test_layout_does_not_import_input_config_or_debug(self) -> None:
        import companion_app.ui.layout as mod
        from pathlib import Path
        src = Path(mod.__file__).read_text(encoding='utf-8')
        self.assertNotIn('companion_app.input', src)
        self.assertNotIn('companion_app.config', src)
        self.assertNotIn('companion_app.debug', src)

    def test_header_page_label_falls_inside_header_band(self) -> None:
        from companion_app.render.font import _get_font

        header_font = _get_font(HEADER_SIZE)
        title_rect = header_font.get_rect('STATUS', size=HEADER_SIZE)
        title_rect.center = (VIRTUAL_WIDTH // 2, HEADER_HEIGHT // 2)

        self.assertGreaterEqual(title_rect.top, 0)
        self.assertLess(title_rect.bottom, HEADER_HEIGHT)

    def test_draw_renders_underlined_header(self) -> None:
        from companion_app.render.font import _get_font

        self.layout.draw(self.surface, Page.STATUS, 'OK')
        header_font = _get_font(HEADER_SIZE)
        title_rect = header_font.get_rect('STATUS', size=HEADER_SIZE)
        title_rect.center = (VIRTUAL_WIDTH // 2, HEADER_HEIGHT // 2)
        underline_y = title_rect.bottom + 4
        px = tuple(self.surface.get_at((VIRTUAL_WIDTH // 2, underline_y)))[:3]
        self.assertEqual(px, palette.DIM)

    def test_draw_console_frame_renders_rule(self) -> None:
        from companion_app.render.font import _get_font

        self.layout.draw(self.surface, Page.STATUS, 'OK')
        label_font = _get_font(HEADER_SIZE)
        label_rect = label_font.get_rect('CONSOLE', size=HEADER_SIZE)
        label_rect.topleft = self.layout.console_rect.topleft
        rule_y = label_rect.bottom + 10
        px = tuple(self.surface.get_at((self.layout.console_rect.left + 40, rule_y)))[:3]
        self.assertEqual(px, palette.DIM)

    def test_draw_placeholder_centers_text_in_content_rect(self) -> None:
        from companion_app.render.font import _get_font

        body_font = _get_font(BODY_SIZE)
        text_rect = body_font.get_rect('CONNECTING…', size=BODY_SIZE)
        text_rect.center = self.layout.content_rect.center
        cr = self.layout.content_rect
        self.assertTrue(cr.contains(text_rect), f'placeholder text rect {text_rect} not inside content rect {cr}')

    def test_draw_placeholder_does_not_crash_with_empty_string(self) -> None:
        self.layout.draw_placeholder(self.surface, '')


if __name__ == '__main__':
    unittest.main()
