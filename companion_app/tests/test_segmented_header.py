"""Unit tests for the reusable sub-header segmented control (TASK-010)."""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import palette
from companion_app.ui import segmented_header as sh
from companion_app.ui.segmented_header import (
    Segment,
    SegmentedHeaderState,
    create,
    cycle_next,
    cycle_prev,
)


def _state(specs: list[tuple[str, bool]], selected: str) -> SegmentedHeaderState:
    return SegmentedHeaderState(
        segments=tuple(Segment(key, key, enabled) for key, enabled in specs),
        selected_key=selected,
    )


class CreateTests(unittest.TestCase):
    def test_selects_first_enabled(self) -> None:
        state = create((Segment("A", "A"), Segment("B", "B")))
        self.assertEqual(state.selected_key, "A")

    def test_skips_leading_disabled(self) -> None:
        state = create((Segment("A", "A", enabled=False), Segment("B", "B")))
        self.assertEqual(state.selected_key, "B")

    def test_no_enabled_yields_empty_sentinel(self) -> None:
        state = create(
            (Segment("A", "A", enabled=False), Segment("B", "B", enabled=False))
        )
        self.assertEqual(state.selected_key, "")


class CycleTests(unittest.TestCase):
    def test_next_wraps_endlessly(self) -> None:
        state = _state([("A", True), ("B", True), ("C", True)], "C")
        self.assertEqual(cycle_next(state).selected_key, "A")

    def test_prev_wraps_endlessly(self) -> None:
        state = _state([("A", True), ("B", True), ("C", True)], "A")
        self.assertEqual(cycle_prev(state).selected_key, "C")

    def test_next_skips_disabled(self) -> None:
        state = _state([("A", True), ("B", False), ("C", True)], "A")
        self.assertEqual(cycle_next(state).selected_key, "C")

    def test_prev_skips_disabled(self) -> None:
        state = _state([("A", True), ("B", False), ("C", True)], "A")
        self.assertEqual(cycle_prev(state).selected_key, "C")

    def test_single_enabled_is_noop(self) -> None:
        state = _state([("A", False), ("B", True), ("C", False)], "B")
        self.assertEqual(cycle_next(state), state)
        self.assertEqual(cycle_prev(state), state)

    def test_zero_enabled_is_safe_noop(self) -> None:
        state = _state([("A", False), ("B", False)], "")
        self.assertEqual(cycle_next(state), state)
        self.assertEqual(cycle_prev(state), state)


class TextColorTests(unittest.TestCase):
    def test_disabled_is_dim(self) -> None:
        seg = Segment("A", "A", enabled=False)
        self.assertEqual(sh._segment_text_color(seg, "A"), palette.DIM)

    def test_active_is_background(self) -> None:
        self.assertEqual(sh._segment_text_color(Segment("A", "A"), "A"), palette.BACKGROUND)

    def test_inactive_is_foreground(self) -> None:
        self.assertEqual(sh._segment_text_color(Segment("A", "A"), "B"), palette.FOREGROUND)


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.content = pygame.Rect(0, 0, 480, 800)
        # A point inside the first segment's active box, in the left padding
        # before the glyphs: box left = 0 + 28, top = 0 + 12.
        self.first_box_fill = (30, 14)

    def _render(self, state: SegmentedHeaderState) -> pygame.Surface:
        surface = pygame.Surface((480, 800))
        sh.render(surface, self.content, state)
        return surface

    def test_active_segment_is_inverse_filled_and_left_aligned(self) -> None:
        surface = self._render(_state([("A", True), ("B", True)], "A"))
        # Active fill present on the left.
        self.assertEqual(
            tuple(surface.get_at(self.first_box_fill))[:3], palette.FOREGROUND
        )
        # Left-aligned: the right edge of the row is empty background, so the
        # control is not centered or right-aligned.
        self.assertNotEqual(tuple(surface.get_at((475, 14)))[:3], palette.FOREGROUND)

    def test_inverse_fill_follows_selection(self) -> None:
        # When the second segment is active, the first segment is inactive and
        # its box region is no longer filled.
        surface = self._render(_state([("A", True), ("B", True)], "B"))
        self.assertNotEqual(
            tuple(surface.get_at(self.first_box_fill))[:3], palette.FOREGROUND
        )

    def test_disabled_state_renders_without_active_fill(self) -> None:
        # No enabled selection -> no inverse fill anywhere on the first box.
        surface = self._render(_state([("A", False), ("B", False)], ""))
        self.assertNotEqual(
            tuple(surface.get_at(self.first_box_fill))[:3], palette.FOREGROUND
        )

    def test_render_with_disabled_segment_does_not_raise(self) -> None:
        self._render(_state([("A", True), ("B", False), ("C", True)], "A"))


if __name__ == "__main__":
    unittest.main()
