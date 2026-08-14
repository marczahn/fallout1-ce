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
        self.assertEqual(sh._segment_text_color(seg, "A", True), palette.DIM)

    def test_active_is_background(self) -> None:
        self.assertEqual(sh._segment_text_color(Segment("A", "A"), "A", True), palette.BACKGROUND)

    def test_inactive_is_foreground(self) -> None:
        self.assertEqual(sh._segment_text_color(Segment("A", "A"), "B", True), palette.FOREGROUND)


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
        # before the glyphs. Measured box: x 28..58, y 6..26.
        self.first_box_fill = (30, 14)

    def _render(
        self, state: SegmentedHeaderState, *, focused: bool = True
    ) -> pygame.Surface:
        surface = pygame.Surface((480, 800))
        sh.render(surface, self.content, state, focused=focused)
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


class FocusStateTests(unittest.TestCase):
    """TASK-018: the active segment outlines when the content has focus."""

    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.content = pygame.Rect(0, 0, 480, 800)
        # Measured geometry of the first segment's active box with
        # content_rect at the origin: x 28..58, y 6..26 (left margin
        # PAGE_MARGIN_X, top _SUBHEADER_TOP_GAP).
        self.inside_box = (30, 20)  # interior, clear of the glyphs
        self.box_top = (30, 6)  # the top border row
        self.border_row_y = 6

    def _render(self, *, focused: bool) -> pygame.Surface:
        surface = pygame.Surface((480, 800))
        sh.render(
            surface,
            self.content,
            _state([("A", True), ("B", True)], "A"),
            focused=focused,
        )
        return surface

    def test_focused_active_segment_is_filled(self) -> None:
        surface = self._render(focused=True)
        self.assertEqual(
            tuple(surface.get_at(self.inside_box))[:3], palette.FOREGROUND
        )

    def test_unfocused_active_segment_is_not_filled(self) -> None:
        surface = self._render(focused=False)
        self.assertNotEqual(
            tuple(surface.get_at(self.inside_box))[:3], palette.FOREGROUND
        )

    def test_unfocused_active_segment_still_draws_its_border(self) -> None:
        """Outlined, not erased — ``Back`` still returns here."""
        surface = self._render(focused=False)
        self.assertEqual(tuple(surface.get_at(self.box_top))[:3], palette.FOREGROUND)

    def test_geometry_is_identical_across_focus_states(self) -> None:
        """The row must not shift when focus moves into the content."""

        def border_span(surface: pygame.Surface) -> list[int]:
            return [
                x
                for x in range(0, 200)
                if tuple(surface.get_at((x, self.border_row_y)))[:3]
                == palette.FOREGROUND
            ]

        self.assertEqual(
            border_span(self._render(focused=True)),
            border_span(self._render(focused=False)),
        )

    def test_unfocused_active_label_is_phosphor_not_background(self) -> None:
        self.assertEqual(
            sh._segment_text_color(Segment("A", "A"), "A", False),
            palette.FOREGROUND,
        )

    def test_unfocused_active_is_distinguishable_from_disabled(self) -> None:
        """DIM means disabled; an unfocused row is still the encoder's home.

        A disabled segment draws no box at all, which is what keeps the two
        states unambiguous even though neither is inverse-filled.
        """
        unfocused_active = sh._segment_text_color(Segment("A", "A"), "A", False)
        disabled = sh._segment_text_color(
            Segment("A", "A", enabled=False), "A", False
        )
        self.assertNotEqual(unfocused_active, disabled)
        self.assertEqual(disabled, palette.DIM)

        surface = pygame.Surface((480, 800))
        sh.render(
            surface,
            self.content,
            _state([("A", False), ("B", False)], ""),
            focused=False,
        )
        self.assertNotEqual(
            tuple(surface.get_at(self.box_top))[:3], palette.FOREGROUND
        )


if __name__ == "__main__":
    unittest.main()
