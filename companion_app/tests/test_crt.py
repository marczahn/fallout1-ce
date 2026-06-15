"""Tests for the CRT scanline overlay (M2-T4)."""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import crt, palette


class BuildScanlineOverlayTest(unittest.TestCase):
    def test_size_matches_request(self) -> None:
        surface = crt.build_scanline_overlay((480, 800))
        self.assertEqual(surface.get_size(), (480, 800))

    def test_alpha_pattern_alternates_every_two_rows(self) -> None:
        surface = crt.build_scanline_overlay((10, 20))
        # Even rows: opaque-ish scanline. Odd rows: transparent.
        for y in range(0, 20):
            px = surface.get_at((0, y))
            if y % 2 == 0:
                self.assertGreater(
                    px.a, 0, f"expected scanline alpha > 0 on row {y}"
                )
                self.assertEqual(
                    (px.r, px.g, px.b), palette.BACKGROUND,
                    f"unexpected color on row {y}: {(px.r, px.g, px.b)}",
                )
            else:
                self.assertEqual(
                    px.a, 0, f"expected fully transparent pixel on row {y}"
                )

    def test_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            crt.build_scanline_overlay((0, 10))
        with self.assertRaises(ValueError):
            crt.build_scanline_overlay((10, -1))
        with self.assertRaises(TypeError):
            crt.build_scanline_overlay((10.0, 20))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            crt.build_scanline_overlay([10, 20])  # type: ignore[arg-type]


class ScanlineOverlayTest(unittest.TestCase):
    def test_draw_blits_onto_target(self) -> None:
        overlay = crt.ScanlineOverlay((10, 10))
        target = pygame.Surface((10, 10))
        target.fill((255, 0, 0))
        overlay.draw(target)
        # Row 0 was opaque BACKGROUND-tinted, alpha-blended over red.
        # The resulting red channel must be lower than the original 255.
        blended = target.get_at((0, 0))
        self.assertLess(blended.r, 255)
        # Row 1 was fully transparent, so red stays put.
        untouched = target.get_at((0, 1))
        self.assertEqual((untouched.r, untouched.g, untouched.b), (255, 0, 0))

    def test_draw_rejects_none_target(self) -> None:
        overlay = crt.ScanlineOverlay((10, 10))
        with self.assertRaises(ValueError):
            overlay.draw(None)  # type: ignore[arg-type]


# -- Startup power-on tests -------------------------------------------

class PowerOnProgressTest(unittest.TestCase):
    def test_starts_at_zero(self) -> None:
        self.assertEqual(crt.power_on_progress(0), 0.0)

    def test_clamps_to_one_at_duration(self) -> None:
        self.assertEqual(crt.power_on_progress(720), 1.0)
        self.assertEqual(crt.power_on_progress(1000), 1.0)


class PowerOnVisibleHeightTest(unittest.TestCase):
    def test_starts_as_thin_center_band(self) -> None:
        self.assertEqual(crt.power_on_visible_height(100, 0), 1)

    def test_grows_monotonically_to_full_height(self) -> None:
        start = crt.power_on_visible_height(100, 0)
        middle = crt.power_on_visible_height(100, 360)
        end = crt.power_on_visible_height(100, 720)
        self.assertLess(start, middle)
        self.assertLess(middle, end)
        self.assertEqual(end, 100)


class PowerOnWobbleOffsetTest(unittest.TestCase):
    def test_is_zero_during_initial_beam_phase(self) -> None:
        self.assertEqual(crt.power_on_wobble_offset(0), 0)

    def test_is_zero_when_complete(self) -> None:
        self.assertEqual(crt.power_on_wobble_offset(720), 0)

    def test_amplitude_decays_toward_zero(self) -> None:
        early = abs(crt.power_on_wobble_offset(220))
        late = abs(crt.power_on_wobble_offset(560))
        self.assertGreater(early, late)


class PowerOnBeamVisibleTest(unittest.TestCase):
    def test_is_visible_at_start(self) -> None:
        self.assertTrue(crt.power_on_beam_visible(0))

    def test_turns_off_after_hold_period(self) -> None:
        self.assertFalse(crt.power_on_beam_visible(140))


class PowerOnEffectTest(unittest.TestCase):
    def test_reports_complete_after_duration(self) -> None:
        effect = crt.PowerOnEffect((20, 100))
        self.assertFalse(effect.is_complete)
        effect.tick(720)
        self.assertTrue(effect.is_complete)

    def test_apply_draws_bright_center_beam_at_start(self) -> None:
        effect = crt.PowerOnEffect((20, 100))
        target = pygame.Surface((20, 100))
        target.fill((0, 255, 0))

        effect.apply(target)

        self.assertEqual(tuple(target.get_at((10, 0)))[:3], palette.BACKGROUND)
        center = target.get_at((10, 50))
        self.assertGreater(center.g, 200)
        self.assertNotEqual(tuple(center)[:3], palette.BACKGROUND)

    def test_apply_reveals_compressed_image_after_beam_phase(self) -> None:
        effect = crt.PowerOnEffect((20, 100))
        target = pygame.Surface((20, 100))
        target.fill((0, 255, 0))
        effect.tick(180)

        effect.apply(target)

        self.assertEqual(tuple(target.get_at((10, 0)))[:3], palette.BACKGROUND)
        band_values = [target.get_at((x, 50)).g for x in range(20)]
        self.assertTrue(any(value > 100 for value in band_values))

    def test_apply_rejects_none_target(self) -> None:
        effect = crt.PowerOnEffect((20, 100))
        with self.assertRaises(ValueError):
            effect.apply(None)  # type: ignore[arg-type]

    def test_tick_rejects_negative_values(self) -> None:
        effect = crt.PowerOnEffect((20, 100))
        with self.assertRaises(ValueError):
            effect.tick(-1)


# -- Vertical sweep tests ---------------------------------------------

class BuildVerticalSweepOverlayTest(unittest.TestCase):
    def test_size_matches_request(self) -> None:
        surface = crt.build_vertical_sweep_overlay(40, 12)
        self.assertEqual(surface.get_size(), (40, 12))

    def test_leading_edge_is_brighter_than_tail_and_edges(self) -> None:
        surface = crt.build_vertical_sweep_overlay(6, 20)
        peak = surface.get_at((0, 3))
        tail = surface.get_at((0, 10))
        edge = surface.get_at((0, 19))
        self.assertGreater(peak.g, tail.g)
        self.assertGreater(tail.g, edge.g)

    def test_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            crt.build_vertical_sweep_overlay(0, 10)
        with self.assertRaises(ValueError):
            crt.build_vertical_sweep_overlay(10, -1)
        with self.assertRaises(TypeError):
            crt.build_vertical_sweep_overlay(10.0, 20)  # type: ignore[arg-type]


class VerticalSweepTopTest(unittest.TestCase):
    def test_starts_above_screen(self) -> None:
        self.assertEqual(crt.vertical_sweep_top(100, 18, 0), -18)

    def test_reaches_mid_screen_halfway_through_cycle(self) -> None:
        top = crt.vertical_sweep_top(100, 18, 3400)
        self.assertEqual(top, 41.0)

    def test_wraps_after_full_cycle(self) -> None:
        self.assertEqual(crt.vertical_sweep_top(100, 18, 6800), -18)


class VerticalSweepOverlayTest(unittest.TestCase):
    def test_draw_brightens_pixels_after_tick(self) -> None:
        overlay = crt.VerticalSweepOverlay((20, 100))
        overlay.tick(3400)
        target = pygame.Surface((20, 100))
        target.fill((0, 0, 0))
        overlay.draw(target)
        band_values = [target.get_at((0, y)).g for y in range(41, 50)]
        self.assertTrue(any(value > 0 for value in band_values))

    def test_tick_rejects_negative_values(self) -> None:
        overlay = crt.VerticalSweepOverlay((20, 100))
        with self.assertRaises(ValueError):
            overlay.tick(-1)

    def test_draw_rejects_none_target(self) -> None:
        overlay = crt.VerticalSweepOverlay((20, 100))
        with self.assertRaises(ValueError):
            overlay.draw(None)  # type: ignore[arg-type]

    def test_reset_restarts_sweep_from_top(self) -> None:
        overlay = crt.VerticalSweepOverlay((20, 100))
        overlay.tick(3400)
        overlay.reset()
        restarted = pygame.Surface((20, 100))
        restarted.fill((0, 0, 0))
        overlay.draw(restarted)

        fresh = crt.VerticalSweepOverlay((20, 100))
        expected = pygame.Surface((20, 100))
        expected.fill((0, 0, 0))
        fresh.draw(expected)

        self.assertEqual(
            restarted.get_at((0, 0)),
            expected.get_at((0, 0)),
        )
        self.assertEqual(
            restarted.get_at((0, 4)),
            expected.get_at((0, 4)),
        )


# -- Vignette tests ---------------------------------------------------

class BuildVignetteOverlayTest(unittest.TestCase):
    def test_size_matches_request(self) -> None:
        surface = crt.build_vignette_overlay((480, 800))
        self.assertEqual(surface.get_size(), (480, 800))

    def test_centre_is_transparent(self) -> None:
        surface = crt.build_vignette_overlay((20, 20))
        cx, cy = 10, 10
        px = surface.get_at((cx, cy))
        self.assertEqual(px.a, 0, "centre pixel should be transparent")

    def test_corner_is_dark(self) -> None:
        surface = crt.build_vignette_overlay((20, 20))
        px = surface.get_at((0, 0))
        self.assertGreater(px.a, 0, "corner pixel should have non-zero alpha")
        self.assertEqual(
            (px.r, px.g, px.b), palette.BACKGROUND,
        )

    def test_alpha_increases_outward(self) -> None:
        # On a 40x40 surface, the pixel midway along the top edge
        # should have higher alpha than the centre.
        surface = crt.build_vignette_overlay((40, 40))
        centre_alpha = surface.get_at((20, 20)).a
        edge_alpha = surface.get_at((20, 0)).a
        self.assertGreater(edge_alpha, centre_alpha)

    def test_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            crt.build_vignette_overlay((0, 10))
        with self.assertRaises(ValueError):
            crt.build_vignette_overlay((10, -1))
        with self.assertRaises(TypeError):
            crt.build_vignette_overlay((10.0, 20))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            crt.build_vignette_overlay([10, 20])  # type: ignore[arg-type]


class VignetteOverlayTest(unittest.TestCase):
    def test_draw_blits(self) -> None:
        overlay = crt.VignetteOverlay((10, 10))
        target = pygame.Surface((10, 10))
        target.fill((255, 255, 255))
        overlay.draw(target)
        # Corner pixel should be blended with BACKGROUND green.
        corner = target.get_at((0, 0))
        self.assertLess(corner.g, 255)

    def test_draw_rejects_none_target(self) -> None:
        overlay = crt.VignetteOverlay((10, 10))
        with self.assertRaises(ValueError):
            overlay.draw(None)  # type: ignore[arg-type]


# -- Rounded-corner tests ---------------------------------------------

class BuildRoundedCornerOverlayTest(unittest.TestCase):
    def test_size_matches_request(self) -> None:
        surface = crt.build_rounded_corner_overlay((480, 800))
        self.assertEqual(surface.get_size(), (480, 800))

    def test_centre_is_transparent(self) -> None:
        surface = crt.build_rounded_corner_overlay((40, 40), radius=10)
        px = surface.get_at((20, 20))
        self.assertEqual(px.a, 0, "centre pixel should be transparent")

    def test_corner_is_opaque(self) -> None:
        surface = crt.build_rounded_corner_overlay((40, 40), radius=10)
        # Far corner (0, 0) is outside the rounded area and should be opaque.
        px = surface.get_at((0, 0))
        self.assertEqual(px.a, 255)

    def test_inside_radius_is_transparent(self) -> None:
        surface = crt.build_rounded_corner_overlay((40, 40), radius=10)
        # Top-left corner quadrant: (10, 10) is on the arc boundary
        # but *inside* the display area -> transparent.
        px = surface.get_at((10, 10))
        self.assertEqual(px.a, 0)

    def test_rejects_bad_radius(self) -> None:
        with self.assertRaises(ValueError):
            crt.build_rounded_corner_overlay((10, 10), radius=0)
        with self.assertRaises(ValueError):
            crt.build_rounded_corner_overlay((10, 10), radius=-1)

    def test_rejects_bad_sizes(self) -> None:
        with self.assertRaises(ValueError):
            crt.build_rounded_corner_overlay((0, 10))
        with self.assertRaises(TypeError):
            crt.build_rounded_corner_overlay([10, 20])  # type: ignore[arg-type]


class RoundedCornerOverlayTest(unittest.TestCase):
    def test_draw_blits(self) -> None:
        overlay = crt.RoundedCornerOverlay((20, 20), radius=5)
        target = pygame.Surface((20, 20))
        target.fill((0, 255, 0))
        overlay.draw(target)
        # Corner should be masked (blended with black).
        corner = target.get_at((0, 0))
        self.assertLess(corner.g, 255)

    def test_draw_rejects_none_target(self) -> None:
        overlay = crt.RoundedCornerOverlay((10, 10), radius=3)
        with self.assertRaises(ValueError):
            overlay.draw(None)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
