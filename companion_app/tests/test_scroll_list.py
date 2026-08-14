"""Unit tests for the scroll-list primitive (TASK-018).

Pure transitions — no pygame, no display. Mirrors the shape of
test_segmented_header's cycle tests, since the wrap/skip semantics are
deliberately the same.
"""
from __future__ import annotations

import unittest

from companion_app.ui import scroll_list
from companion_app.ui.scroll_list import ListCursor, ListRow


def _rows(*spec: tuple[str, bool]) -> tuple[ListRow, ...]:
    return tuple(
        ListRow(key=key, label=key, selectable=selectable) for key, selectable in spec
    )


_HEADED = _rows(
    ("#A", False),
    ("a1", True),
    ("a2", True),
    ("#B", False),
    ("b1", True),
)


def _uniform(_row: ListRow) -> int:
    """Every row one unit tall — the simple case."""
    return 1


def _tall_headings(row: ListRow) -> int:
    """Headings twice an item's height, as the inventory lays them out."""
    return 1 if row.selectable else 2


def _at(rows: tuple[ListRow, ...], key: str) -> ListCursor:
    index = scroll_list.index_of(rows, key)
    assert index is not None
    return ListCursor(selected_key=key, selected_index=index)


class FirstSelectableTests(unittest.TestCase):
    def test_skips_leading_headings(self) -> None:
        self.assertEqual(scroll_list.first_selectable(_HEADED), "a1")

    def test_no_selectable_yields_sentinel(self) -> None:
        rows = _rows(("#A", False), ("#B", False))
        self.assertEqual(scroll_list.first_selectable(rows), scroll_list.NO_SELECTION)

    def test_empty_rows_yield_sentinel(self) -> None:
        self.assertEqual(scroll_list.first_selectable(()), scroll_list.NO_SELECTION)


class MoveTests(unittest.TestCase):
    def test_next_skips_headings(self) -> None:
        cursor = scroll_list.move_next(_HEADED, _at(_HEADED, "a2"))
        self.assertEqual(cursor.selected_key, "b1")

    def test_prev_skips_headings(self) -> None:
        cursor = scroll_list.move_prev(_HEADED, _at(_HEADED, "b1"))
        self.assertEqual(cursor.selected_key, "a2")

    def test_next_wraps_past_the_end(self) -> None:
        cursor = scroll_list.move_next(_HEADED, _at(_HEADED, "b1"))
        self.assertEqual(cursor.selected_key, "a1")

    def test_prev_wraps_past_the_start(self) -> None:
        cursor = scroll_list.move_prev(_HEADED, _at(_HEADED, "a1"))
        self.assertEqual(cursor.selected_key, "b1")

    def test_move_records_the_index(self) -> None:
        cursor = scroll_list.move_next(_HEADED, _at(_HEADED, "a1"))
        self.assertEqual(cursor.selected_key, "a2")
        self.assertEqual(cursor.selected_index, 2)

    def test_single_selectable_is_a_noop(self) -> None:
        rows = _rows(("#A", False), ("only", True))
        cursor = _at(rows, "only")
        self.assertEqual(scroll_list.move_next(rows, cursor).selected_key, "only")
        self.assertEqual(scroll_list.move_prev(rows, cursor).selected_key, "only")

    def test_zero_selectable_is_a_safe_noop(self) -> None:
        rows = _rows(("#A", False), ("#B", False))
        cursor = ListCursor()
        self.assertEqual(scroll_list.move_next(rows, cursor), cursor)
        self.assertEqual(scroll_list.move_prev(rows, cursor), cursor)

    def test_unresolvable_selection_is_a_noop(self) -> None:
        cursor = ListCursor(selected_key="gone", selected_index=99)
        self.assertEqual(scroll_list.move_next(_HEADED, cursor), cursor)


class WindowTests(unittest.TestCase):
    def test_short_list_shows_everything(self) -> None:
        visible = scroll_list.visible(_HEADED, _at(_HEADED, "a1"), 100, _uniform)
        self.assertEqual(len(visible), len(_HEADED))
        self.assertEqual(visible[0][0], 0)

    def test_selection_near_the_top_does_not_scroll_past_the_start(self) -> None:
        rows = _rows(*((f"i{n}", True) for n in range(50)))
        visible = scroll_list.visible(rows, _at(rows, "i1"), 10, _uniform)
        self.assertEqual(visible[0][0], 0)

    def test_selection_centres_once_past_the_middle(self) -> None:
        """Roughly centred: the selection's own height counts toward the half."""
        rows = _rows(*((f"i{n}", True) for n in range(100)))
        visible = scroll_list.visible(rows, _at(rows, "i20"), 10, _uniform)
        indices = [index for index, _row in visible]
        self.assertEqual(len(indices), 10)
        self.assertEqual(20 - indices[0], 4)
        self.assertEqual(indices[-1] - 20, 5)

    def test_selection_at_the_end_fills_the_window(self) -> None:
        """No blank space below the last row."""
        rows = _rows(*((f"i{n}", True) for n in range(50)))
        visible = scroll_list.visible(rows, _at(rows, "i49"), 10, _uniform)
        self.assertEqual(len(visible), 10)
        self.assertEqual(visible[-1][0], 49)

    def test_zero_space_is_safe(self) -> None:
        self.assertEqual(
            scroll_list.visible(_HEADED, _at(_HEADED, "a1"), 0, _uniform), ()
        )


class VisibleTests(unittest.TestCase):
    """``visible`` is height-aware; heights are in the caller's own units."""

    def test_returns_absolute_indices(self) -> None:
        """Indices are into ``rows``, not into the returned window.

        With space for 3 units the window cannot reach back past the
        heading at index 0 (half of 3 is 1, already spent on the selection),
        so it starts at the selection itself — which is what makes the
        absolute-vs-relative distinction visible here.
        """
        visible = scroll_list.visible(_HEADED, _at(_HEADED, "a1"), 3, _uniform)
        self.assertEqual([index for index, _row in visible], [1, 2, 3])

    def test_window_follows_the_selection_in_a_long_list(self) -> None:
        rows = _rows(*((f"i{n}", True) for n in range(50)))
        visible = scroll_list.visible(rows, _at(rows, "i40"), 10, _uniform)
        keys = [row.key for _index, row in visible]
        self.assertIn("i40", keys)
        self.assertEqual(len(keys), 10)

    def test_empty_rows_return_nothing(self) -> None:
        self.assertEqual(scroll_list.visible((), ListCursor(), 100, _uniform), ())

    def test_taller_headings_consume_more_of_the_window(self) -> None:
        """The whole point of making the window height-aware."""
        uniform = scroll_list.visible(_HEADED, _at(_HEADED, "a1"), 5, _uniform)
        tall = scroll_list.visible(_HEADED, _at(_HEADED, "a1"), 5, _tall_headings)
        self.assertGreater(len(uniform), len(tall))

    def test_window_never_exceeds_the_available_space(self) -> None:
        rows = _rows(*((f"i{n}", n % 3 != 0) for n in range(40)))
        for key in ("i1", "i20", "i38"):
            with self.subTest(selected=key):
                visible = scroll_list.visible(rows, _at(rows, key), 12, _tall_headings)
                total = sum(_tall_headings(row) for _index, row in visible)
                self.assertLessEqual(total, 12)

    def test_selection_is_always_inside_the_window(self) -> None:
        rows = _rows(*((f"i{n}", n % 4 != 0) for n in range(60)))
        for key in ("i1", "i2", "i30", "i58", "i59"):
            with self.subTest(selected=key):
                visible = scroll_list.visible(
                    rows, _at(rows, key), 12, _tall_headings
                )
                self.assertIn(key, [row.key for _index, row in visible])


class ResolveCursorTests(unittest.TestCase):
    def test_resolving_a_live_key_refreshes_its_index(self) -> None:
        stale = ListCursor(selected_key="b1", selected_index=0)
        resolved = scroll_list.resolve_cursor(_HEADED, stale)
        self.assertEqual(resolved.selected_key, "b1")
        self.assertEqual(resolved.selected_index, 4)

    def test_is_idempotent(self) -> None:
        once = scroll_list.resolve_cursor(_HEADED, ListCursor("b1", 0))
        twice = scroll_list.resolve_cursor(_HEADED, once)
        self.assertEqual(once, twice)

    def test_empty_rows_yield_an_empty_cursor(self) -> None:
        self.assertEqual(
            scroll_list.resolve_cursor((), _at(_HEADED, "a1")), ListCursor()
        )

    def test_no_index_falls_back_to_first_selectable(self) -> None:
        resolved = scroll_list.resolve_cursor(_HEADED, ListCursor("gone"))
        self.assertEqual(resolved.selected_key, "a1")

    def test_vanished_key_clamps_backwards_from_its_index(self) -> None:
        # "b1" removed; its old index 4 is now past the end of the list.
        shorter = _rows(("#A", False), ("a1", True), ("a2", True))
        resolved = scroll_list.resolve_cursor(shorter, ListCursor("b1", 4))
        self.assertEqual(resolved.selected_key, "a2")

    def test_vanished_key_searches_forward_when_nothing_precedes(self) -> None:
        # Index 0 is a heading and everything before it is gone.
        resolved = scroll_list.resolve_cursor(_HEADED, ListCursor("gone", 0))
        self.assertEqual(resolved.selected_key, "a1")

    def test_selecting_a_heading_key_is_rejected(self) -> None:
        resolved = scroll_list.resolve_cursor(_HEADED, ListCursor("#B", 3))
        self.assertTrue(_HEADED[resolved.selected_index].selectable)

    def test_all_headings_yield_an_empty_cursor(self) -> None:
        rows = _rows(("#A", False), ("#B", False))
        self.assertEqual(
            scroll_list.resolve_cursor(rows, ListCursor("gone", 1)), ListCursor()
        )


if __name__ == "__main__":
    unittest.main()
