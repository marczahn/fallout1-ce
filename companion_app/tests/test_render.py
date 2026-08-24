"""Tests for the M2 render primitives (palette, background, font helpers)."""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import background, font, palette


def _surface() -> pygame.Surface:
    if not pygame.display.get_init():
        pygame.display.init()
    # Headless surface; SDL_VIDEODRIVER=dummy is set by tests/__init__.py.
    return pygame.Surface((480, 800))


class PaletteTest(unittest.TestCase):
    def test_constants_are_rgb_tuples(self) -> None:
        for name in ("BACKGROUND", "FOREGROUND", "DIM"):
            color = getattr(palette, name)
            self.assertIsInstance(color, tuple)
            self.assertEqual(len(color), 3)
            for c in color:
                self.assertIsInstance(c, int)
                self.assertGreaterEqual(c, 0)
                self.assertLessEqual(c, 255)


class BackgroundTest(unittest.TestCase):
    def test_fill_background_paints_palette_color(self) -> None:
        s = _surface()
        s.fill((255, 255, 255))
        background.fill_background(s)
        self.assertEqual(tuple(s.get_at((0, 0)))[:3], palette.BACKGROUND)
        self.assertEqual(tuple(s.get_at((479, 799)))[:3], palette.BACKGROUND)

    def test_fill_background_rejects_none(self) -> None:
        with self.assertRaises(ValueError):
            background.fill_background(None)  # type: ignore[arg-type]


class FontHelpersTest(unittest.TestCase):
    def test_load_font_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            font.load_font(0)
        with self.assertRaises(ValueError):
            font.load_font(-5)
        with self.assertRaises(TypeError):
            font.load_font("22")  # type: ignore[arg-type]

    def test_draw_text_left_returns_rect_at_pos(self) -> None:
        s = _surface()
        rect = font.draw_text_left(s, "STATUS", (16, 8), 22, palette.FOREGROUND)
        self.assertEqual(rect.left, 16)
        self.assertEqual(rect.top, 8)
        self.assertGreater(rect.width, 0)

    def test_draw_text_right_anchors_to_right_edge(self) -> None:
        s = _surface()
        right_pos = (464, 8)
        rect = font.draw_text_right(s, "--", right_pos, 22, palette.FOREGROUND)
        self.assertEqual(rect.right, right_pos[0])
        self.assertEqual(rect.top, right_pos[1])

    def test_draw_text_centered_centers_in_rect(self) -> None:
        s = _surface()
        body = pygame.Rect(0, 41, 480, 759)
        rect = font.draw_text_centered(
            s, "PIPBOY 2000", body, 32, palette.FOREGROUND
        )
        # Centered within rect (allow 1 px slack from integer rounding).
        self.assertAlmostEqual(rect.centerx, body.centerx, delta=1)
        self.assertAlmostEqual(rect.centery, body.centery, delta=1)

    def test_strike_adds_pixels_on_the_midline(self) -> None:
        """The strike is measured, not assumed (TASK-021).

        Renders the same glyph twice and compares the midline row: the
        struck copy must have foreground pixels where the unstruck one has
        none. Uses a glyph with a gap at its vertical centre so there is a
        column to find — "X" narrows to a crossing point at the midline,
        which is exactly where the rule lands, so it is a poor probe.
        """
        plain = _surface()
        struck = _surface()

        rect = font.draw_text_left(plain, "II", (10, 10), 22, palette.FOREGROUND)
        rect_struck = font.draw_text_left(
            struck, "II", (10, 10), 22, palette.FOREGROUND, strike=True
        )
        self.assertEqual(rect, rect_struck, "strike must not move the text")

        y = rect.centery
        plain_row = [
            plain.get_at((x, y))[:3] for x in range(rect.left, rect.right)
        ]
        struck_row = [
            struck.get_at((x, y))[:3] for x in range(rect.left, rect.right)
        ]
        fg = tuple(palette.FOREGROUND)
        self.assertGreater(
            sum(1 for px in struck_row if tuple(px) == fg),
            sum(1 for px in plain_row if tuple(px) == fg),
            "struck midline must carry more foreground pixels than the plain one",
        )
        # And the rule spans the text: both ends of the midline are lit.
        self.assertEqual(tuple(struck.get_at((rect.left, y))[:3]), fg)
        self.assertEqual(tuple(struck.get_at((rect.right - 1, y))[:3]), fg)

    def test_strike_defaults_off_so_existing_callers_are_unchanged(self) -> None:
        with_default = _surface()
        explicit_off = _surface()
        font.draw_text_left(with_default, "AB", (5, 5), 20, palette.FOREGROUND)
        font.draw_text_left(
            explicit_off, "AB", (5, 5), 20, palette.FOREGROUND, strike=False
        )
        self.assertEqual(
            pygame.image.tostring(with_default, "RGB"),
            pygame.image.tostring(explicit_off, "RGB"),
        )

    def test_strike_on_empty_text_draws_nothing(self) -> None:
        blank = _surface()
        struck = _surface()
        font.draw_text_left(struck, "", (5, 5), 20, palette.FOREGROUND, strike=True)
        self.assertEqual(
            pygame.image.tostring(blank, "RGB"),
            pygame.image.tostring(struck, "RGB"),
        )

    def test_helpers_reject_bad_args(self) -> None:
        s = _surface()
        with self.assertRaises(ValueError):
            font.draw_text_left(None, "x", (0, 0), 22, palette.FOREGROUND)  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            font.draw_text_left(s, 123, (0, 0), 22, palette.FOREGROUND)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            font.draw_text_left(s, "x", (0, 0), 0, palette.FOREGROUND)


if __name__ == "__main__":
    unittest.main()
