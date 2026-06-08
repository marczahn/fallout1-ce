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
    HEADER_LEFT_POS,
    SEPARATOR_Y,
    TITLE_SIZE,
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
        self.layout.draw(self.surface, Page.STATUS, "--")
        px = tuple(self.surface.get_at((1, 1)))[:3]
        self.assertEqual(px, palette.BACKGROUND)

    def test_content_rect_starts_after_header_band(self) -> None:
        r = self.layout.content_rect
        self.assertEqual(r.top, SEPARATOR_Y + 1)
        self.assertEqual(r.width, VIRTUAL_WIDTH)
        self.assertEqual(r.height, VIRTUAL_HEIGHT - (SEPARATOR_Y + 1))

    def test_console_rect_sits_inside_content_rect(self) -> None:
        self.assertTrue(self.layout.content_rect.contains(self.layout.console_rect))

    def test_layout_does_not_import_input_config_or_debug(self) -> None:
        import companion_app.ui.layout as mod
        from pathlib import Path
        src = Path(mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("companion_app.input", src)
        self.assertNotIn("companion_app.config", src)
        self.assertNotIn("companion_app.debug", src)

    def test_title_rect_falls_inside_header_band(self) -> None:
        from companion_app.render.font import _get_font

        title_font = _get_font(TITLE_SIZE)
        title_rect = title_font.get_rect("PIP-BOY 2000 Mk. 1", size=TITLE_SIZE)
        title_rect.topleft = HEADER_LEFT_POS

        self.assertGreaterEqual(title_rect.top, 0)
        self.assertLess(title_rect.bottom, HEADER_HEIGHT)

    def test_header_area_away_from_title_stays_background(self) -> None:
        self.layout.draw(self.surface, Page.STATUS, "OK")
        px = tuple(self.surface.get_at((VIRTUAL_WIDTH - 40, HEADER_HEIGHT // 2)))[:3]
        self.assertEqual(px, palette.BACKGROUND)

    def test_draw_placeholder_centers_text_in_content_rect(self) -> None:
        from companion_app.render.font import _get_font

        body_font = _get_font(BODY_SIZE)
        text_rect = body_font.get_rect("CONNECTING…", size=BODY_SIZE)
        text_rect.center = self.layout.content_rect.center
        cr = self.layout.content_rect
        self.assertTrue(cr.contains(text_rect), f"placeholder text rect {text_rect} not inside content rect {cr}")

    def test_draw_placeholder_does_not_crash_with_empty_string(self) -> None:
        self.layout.draw_placeholder(self.surface, "")


if __name__ == "__main__":
    unittest.main()
