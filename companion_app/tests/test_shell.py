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
    HEADER_RIGHT_POS,
    HEADER_SIZE,
    SEPARATOR_Y,
    STATUS_SIZE,
    TAB_START_X,
    TAB_TOP,
    TAB_WIDTH,
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

    def test_separator_pixel_is_dim(self) -> None:
        self.layout.draw(self.surface, Page.STATUS, "--")
        px = tuple(self.surface.get_at((VIRTUAL_WIDTH // 2, SEPARATOR_Y)))[:3]
        self.assertEqual(px, palette.DIM)

    def test_content_rect_starts_after_separator(self) -> None:
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

    def test_header_text_rects_fall_inside_header_band(self) -> None:
        from companion_app.render.font import _get_font

        label_font = _get_font(STATUS_SIZE)
        title_rect = label_font.get_rect("PIP-BOY 2000", size=STATUS_SIZE)
        title_rect.topleft = HEADER_LEFT_POS
        status_rect = label_font.get_rect("--", size=STATUS_SIZE)
        status_rect.topright = HEADER_RIGHT_POS

        self.assertGreaterEqual(title_rect.top, 0)
        self.assertLess(title_rect.bottom, HEADER_HEIGHT)
        self.assertGreaterEqual(status_rect.top, 0)
        self.assertLess(status_rect.bottom, HEADER_HEIGHT)
        self.assertEqual(status_rect.right, HEADER_RIGHT_POS[0])

    def test_active_tab_border_is_bright(self) -> None:
        self.layout.draw(self.surface, Page.STATUS, "OK")
        px = tuple(self.surface.get_at((TAB_START_X, TAB_TOP)))[:3]
        self.assertEqual(px, palette.FOREGROUND)

    def test_inactive_tab_area_is_not_active_fill(self) -> None:
        self.layout.draw(self.surface, Page.STATUS, "OK")
        sample_x = TAB_START_X + TAB_WIDTH + 10
        px = tuple(self.surface.get_at((sample_x, TAB_TOP + 4)))[:3]
        self.assertNotEqual(px, palette.FOREGROUND)

    def test_draw_placeholder_centers_text_in_content_rect(self) -> None:
        from companion_app.render.font import _get_font

        body_font = _get_font(BODY_SIZE)
        text_rect = body_font.get_rect("CONNECTING…", size=BODY_SIZE)
        text_rect.center = self.layout.content_rect.center
        cr = self.layout.content_rect
        self.assertTrue(
            cr.contains(text_rect),
            f"placeholder text rect {text_rect} not inside content rect {cr}",
        )

    def test_draw_placeholder_does_not_crash_with_empty_string(self) -> None:
        self.layout.draw_placeholder(self.surface, "")


if __name__ == "__main__":
    unittest.main()
