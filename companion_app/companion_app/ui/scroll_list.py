"""Reusable selectable-list primitive with a scrolling viewport (TASK-018).

The app's first list component. Rows are either selectable items or
non-selectable headings; the cursor moves item to item, skipping headings
and wrapping endlessly in both directions.

The wrap/skip transition deliberately mirrors ``segmented_header._cycle``:
the same "nothing selectable" and "current selection does not resolve"
guards, the same modulo step. Endless wrap is the behaviour the device
already teaches on the sub-header, so the list inherits it rather than
inventing a second rule.

``ListCursor`` carries ``selected_index`` alongside ``selected_key``. The
key is the anchor, but when the selected row disappears from the list the
cursor needs a *position* to fall back to, and a key that no longer
resolves cannot supply one.

The viewport is **not** state: ``window_top_for`` derives it from the
selection alone, so nothing has to keep a scroll offset in sync with a
rect it cannot see. Deriving beats storing here because the row list is
itself derived fresh every frame.

State is immutable and every transition is pure, so this module is
unit-testable without a display and imports no pygame.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

# Sentinel selected_key meaning "nothing selected". Same convention as
# ``segmented_header._NO_SELECTION`` rather than a new idiom.
NO_SELECTION: str = ""

# selected_index value meaning "never resolved to a position".
NO_INDEX: int = -1


@dataclass(frozen=True)
class ListRow:
    """One rendered line. Headings are rows with ``selectable=False``."""

    key: str
    label: str
    selectable: bool = True


@dataclass(frozen=True)
class ListCursor:
    """The selection, as a key plus the position it last resolved to.

    ``selected_index`` exists so that a selection whose row has vanished
    can clamp back to where it used to be; see the module docstring.
    """

    selected_key: str = NO_SELECTION
    selected_index: int = NO_INDEX


def index_of(rows: Sequence[ListRow], key: str) -> int | None:
    """Index of the row carrying ``key``, or ``None``."""
    if not key:
        return None
    for index, row in enumerate(rows):
        if row.key == key:
            return index
    return None


def first_selectable(rows: Sequence[ListRow]) -> str:
    """Key of the leading selectable row, or the empty sentinel."""
    for row in rows:
        if row.selectable:
            return row.key
    return NO_SELECTION


def cursor_at(rows: Sequence[ListRow], index: int) -> ListCursor:
    """Cursor pointing at ``index``, or an empty cursor if out of range."""
    if index < 0 or index >= len(rows):
        return ListCursor()
    return ListCursor(selected_key=rows[index].key, selected_index=index)


def _step(
    rows: Sequence[ListRow],
    cursor: ListCursor,
    step: int,
) -> ListCursor:
    # Guard before any index lookup, mirroring segmented_header._cycle:
    # nothing to do without a selectable row or a resolvable selection.
    if not any(row.selectable for row in rows):
        return cursor
    current = index_of(rows, cursor.selected_key)
    if current is None:
        return cursor

    count = len(rows)
    index = current
    for _ in range(count):
        index = (index + step) % count
        if rows[index].selectable:
            return ListCursor(selected_key=rows[index].key, selected_index=index)
    return cursor


def move_next(rows: Sequence[ListRow], cursor: ListCursor) -> ListCursor:
    """Advance to the next selectable row, wrapping endlessly."""
    return _step(rows, cursor, 1)


def move_prev(rows: Sequence[ListRow], cursor: ListCursor) -> ListCursor:
    """Move to the previous selectable row, wrapping endlessly."""
    return _step(rows, cursor, -1)


def resolve_cursor(
    rows: Sequence[ListRow],
    cursor: ListCursor,
) -> ListCursor:
    """Re-anchor ``cursor`` against ``rows``.

    Idempotent and pure over ``(rows, cursor)`` — which is what lets the
    input router resolve-then-move while the renderer resolves-and-discards
    on the same rows, and still reach the same answer without either one
    writing back through the other.

    When the anchored row is gone, ``selected_index`` is the position to
    clamp to: nearest surviving selectable row at or before it, then the
    nearest after it. That is the whole reason the cursor remembers a
    position and not just a key.
    """
    if not rows:
        return ListCursor()

    index = index_of(rows, cursor.selected_key)
    if index is not None and rows[index].selectable:
        # Refresh the remembered position; the key may have moved.
        return ListCursor(selected_key=cursor.selected_key, selected_index=index)

    if cursor.selected_index == NO_INDEX:
        first_index = index_of(rows, first_selectable(rows))
        if first_index is None:
            return ListCursor()
        return cursor_at(rows, first_index)

    start = min(max(cursor.selected_index, 0), len(rows) - 1)
    for index in range(start, -1, -1):
        if rows[index].selectable:
            return cursor_at(rows, index)
    for index in range(start + 1, len(rows)):
        if rows[index].selectable:
            return cursor_at(rows, index)
    return ListCursor()


def visible(
    rows: Sequence[ListRow],
    cursor: ListCursor,
    available: int,
    row_height: Callable[[ListRow], int],
) -> tuple[tuple[int, ListRow], ...]:
    """The visible ``(absolute_index, row)`` window for ``cursor``.

    Height-aware rather than row-count-aware, because rows are not a
    uniform height: a group heading is taller than an item, since the air
    that separates a group from the one before it lives inside the
    heading's own row. ``available`` and ``row_height`` are in whatever
    unit the caller works in — pixels, for the inventory.

    Stateless by construction — no previous scroll offset is consulted —
    so the renderer computes the window fresh each frame and the input
    router never has to know anything about geometry. The selection is kept
    roughly centred, and a list that fits never scrolls.
    """
    if available <= 0 or not rows:
        return ()

    index = index_of(rows, cursor.selected_key)
    anchor = min(max(index if index is not None else 0, 0), len(rows) - 1)

    # Walk back from the selection until about half the space is spoken for.
    start = anchor
    used = row_height(rows[anchor])
    half = available // 2
    while start > 0:
        height = row_height(rows[start - 1])
        if used + height > half:
            break
        start -= 1
        used += height

    # Fill forward from there.
    end = start
    total = 0
    while end < len(rows):
        height = row_height(rows[end])
        if total + height > available:
            break
        total += height
        end += 1

    # At the end of the list, reclaim leftover space upward rather than
    # leaving a gap below the last row.
    if end == len(rows):
        while start > 0:
            height = row_height(rows[start - 1])
            if total + height > available:
                break
            start -= 1
            total += height

    return tuple((offset, rows[offset]) for offset in range(start, end))
