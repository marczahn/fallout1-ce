"""Tests for the M2 screen shell."""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import palette
from companion_app.ui import shell


class ShellTest(unittest.TestCase):
    def setUp(self) -> None:
        if not pygame.display.get_init():
            pygame.display.init()
        self.surface = pygame.Surface((shell.VIRTUAL_WIDTH, shell.VIRTUAL_HEIGHT))

    def test_draw_shell_fills_background(self) -> None:
        # Pre-paint to a different color to make sure draw_shell repaints.
        self.surface.fill((123, 45, 67))
        shell.draw_shell(self.surface, "STATUS", "--", "PIPBOY 2000")
        # A pixel far away from text should be background-colored.
        self.assertEqual(
            tuple(self.surface.get_at((1, 1)))[:3], palette.BACKGROUND
        )

    def test_separator_pixel_is_dim(self) -> None:
        shell.draw_shell(self.surface, "STATUS", "--", "PIPBOY 2000")
        # Mid-x on the separator line.
        px = tuple(self.surface.get_at((shell.VIRTUAL_WIDTH // 2, shell.SEPARATOR_Y)))[:3]
        self.assertEqual(px, palette.DIM)

    def test_layout_constants(self) -> None:
        self.assertEqual(shell.HEADER_HEIGHT, 40)
        self.assertEqual(shell.SEPARATOR_Y, 40)
        self.assertEqual(shell.BODY_RECT.top, 41)
        self.assertEqual(shell.BODY_RECT.height, shell.VIRTUAL_HEIGHT - 41)
        self.assertEqual(shell.BODY_RECT.width, shell.VIRTUAL_WIDTH)

    def test_draw_shell_does_not_import_input_config_or_debug(self) -> None:
        import companion_app.ui.shell as s
        from pathlib import Path
        src = Path(s.__file__).read_text(encoding="utf-8")
        self.assertNotIn("companion_app.input", src)
        self.assertNotIn("companion_app.config", src)
        self.assertNotIn("companion_app.debug", src)

    def test_header_text_rects_fall_inside_header_band(self) -> None:
        # Exercise the font helpers via the shell. Recompute rects from
        # the font directly to assert positioning matches the layout.
        from companion_app.render.font import _get_font

        header_font = _get_font(shell.HEADER_SIZE)
        left_rect = header_font.get_rect("STATUS", size=shell.HEADER_SIZE)
        left_rect.topleft = shell.HEADER_LEFT_POS
        right_rect = header_font.get_rect("--", size=shell.HEADER_SIZE)
        right_rect.topright = shell.HEADER_RIGHT_POS

        self.assertGreaterEqual(left_rect.top, 0)
        self.assertLess(left_rect.bottom, shell.HEADER_HEIGHT)
        self.assertGreaterEqual(right_rect.top, 0)
        self.assertLess(right_rect.bottom, shell.HEADER_HEIGHT)
        self.assertEqual(right_rect.right, shell.HEADER_RIGHT_POS[0])

    def test_body_text_rect_falls_inside_body_rect(self) -> None:
        from companion_app.render.font import _get_font

        body_font = _get_font(shell.BODY_SIZE)
        body_rect = body_font.get_rect("PIPBOY 2000", size=shell.BODY_SIZE)
        body_rect.center = shell.BODY_RECT.center
        self.assertTrue(shell.BODY_RECT.contains(body_rect))


if __name__ == "__main__":
    unittest.main()
