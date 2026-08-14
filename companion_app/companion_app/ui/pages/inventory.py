"""STATUS/INVENTORY sub-section — the scrollable item list (TASK-018).

Was a placeholder until TASK-018. Renders a type-grouped, infinitely
scrolling list with a live detail pane beneath it: the pane follows the
selection, so there is no second ``Confirm``/``Back`` level and no depth
to lose track of.

The focus rule is shared with the sub-header: **the solid inverse fill
always marks whatever the encoder currently drives.** Activated, the
selected row is filled and the sub-header segment is outlined; back at the
sub-section row it is the other way round. Exactly one filled element on
screen at any time, which is the entire focus indicator — a breadcrumb
would not fit on a 480x800 device.

``_render_type_detail`` is a deliberate seam: it dispatches over all seven
engine item types and draws nothing for any of them, because the per-type
stats (damage, ammo, armor class, charges) are not on the wire yet. TASK-019
adds the fields and fills the branches; keeping the dispatch total here is
what makes that additive.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState, InventoryItem
from companion_app.ui import inventory_list, scroll_list
from companion_app.ui.shell import PAGE_MARGIN_X

if TYPE_CHECKING:
    from companion_app.ui.sections import SubSectionFocus

EMPTY_TEXT: str = "No items available"
_EMPTY_SIZE: int = 20

_ROW_SIZE: int = 15
_HEADING_SIZE: int = 13
_DETAIL_LABEL_SIZE: int = 13
_DETAIL_VALUE_SIZE: int = 15

# One row's full height including its padding, so the viewport row count
# and the drawn rows cannot disagree.
_ROW_HEIGHT: int = 26
_ROW_PAD_X: int = 6
_ROW_PAD_Y: int = 4

# Reserved for the detail pane at the bottom of the body, plus the rule
# separating it from the list.
_DETAIL_HEIGHT: int = 132
_DETAIL_GAP: int = 10
_DETAIL_ROW_GAP: int = 22
_RULE_HEIGHT: int = 1

_OUTLINE_WIDTH: int = 1


def body_inner_rect(body_rect: pygame.Rect) -> pygame.Rect:
    """The body inset to the shared page margin on both sides.

    ``content_rect`` spans the full 480px virtual width (its left edge is
    0), and STATUS forwards it insetting only the top — so the horizontal
    margin has to be applied here or the list would run to the screen
    edge. Matches how AUTOMAPS insets its map body.
    """
    inner = body_rect.copy()
    inner.left = body_rect.left + PAGE_MARGIN_X
    inner.width = body_rect.width - 2 * PAGE_MARGIN_X
    return inner


def list_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The list viewport: the body inner rect above the detail pane."""
    inner = body_inner_rect(body_rect)
    rect = inner.copy()
    rect.height = inner.height - _DETAIL_HEIGHT - _DETAIL_GAP - _RULE_HEIGHT
    return rect


def viewport_rows_for(body_rect: pygame.Rect) -> int:
    """How many rows fit in the viewport, derived from the rect itself."""
    return max(0, list_rect_for(body_rect).height // _ROW_HEIGHT)


def inventory_content_bottom(body_rect: pygame.Rect) -> int:
    """Absolute y of the lowest pixel this sub-section draws.

    Derived from the same constants the renderer uses, for the reason
    ``status.character_content_bottom`` exists: pygame clips silently at
    the surface edge, so an overflowing block simply disappears and leaves
    nothing in the rendered output for a pixel-scanning test to find.
    """
    list_rect = list_rect_for(body_rect)
    return (
        list_rect.top
        + viewport_rows_for(body_rect) * _ROW_HEIGHT
        + _DETAIL_GAP
        + _RULE_HEIGHT
        + _DETAIL_HEIGHT
    )


def inventory_content_right(body_rect: pygame.Rect) -> int:
    """Absolute x of the rightmost pixel this sub-section may draw."""
    return body_inner_rect(body_rect).right


def _draw_heading(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
) -> None:
    font.draw_text_left(
        surface,
        label,
        (rect.left + _ROW_PAD_X, rect.top + _ROW_PAD_Y + 2),
        _HEADING_SIZE,
        palette.DIM,
    )


def _row_suffix(item: InventoryItem) -> str:
    """Right-hand column: stack count and equipped marker."""
    parts: list[str] = []
    if item.count > 1:
        parts.append(f"x{item.count}")
    if inventory_list.is_equipped(item):
        parts.append("*")
    return " ".join(parts)


def _draw_item_row(
    surface: pygame.Surface,
    rect: pygame.Rect,
    item: InventoryItem,
    label: str,
    *,
    selected: bool,
    activated: bool,
) -> None:
    text_color = palette.FOREGROUND
    if selected:
        # Filled while the list holds the encoder, outlined otherwise —
        # the same rule the sub-header follows, inverted.
        pygame.draw.rect(
            surface,
            palette.FOREGROUND,
            rect,
            0 if activated else _OUTLINE_WIDTH,
        )
        if activated:
            text_color = palette.BACKGROUND

    font.draw_text_left(
        surface,
        label,
        (rect.left + _ROW_PAD_X, rect.top + _ROW_PAD_Y),
        _ROW_SIZE,
        text_color,
    )
    suffix = _row_suffix(item)
    if suffix:
        font.draw_text_right(
            surface,
            suffix,
            (rect.right - _ROW_PAD_X, rect.top + _ROW_PAD_Y),
            _ROW_SIZE,
            text_color,
        )


def _detail_common_only(
    surface: pygame.Surface,
    rect: pygame.Rect,
    item: InventoryItem,
) -> None:
    """No type-specific stats — the common block already said everything.

    Every type resolves here today. Weight, value, damage, ammo, armor
    class and charges are simply not on the wire at ``schemaVersion`` 9.
    """
    _ = (surface, rect, item)


# The per-type seam. Total over the wire's seven ``type`` values, so
# TASK-019 replaces entries rather than adding a dispatch.
_TypeDetailRenderer = Callable[[pygame.Surface, pygame.Rect, InventoryItem], None]

_TYPE_DETAIL: dict[str, _TypeDetailRenderer] = {
    wire_type: _detail_common_only for wire_type, _label in inventory_list.GROUP_ORDER
}


def _render_type_detail(
    surface: pygame.Surface,
    rect: pygame.Rect,
    item: InventoryItem,
) -> None:
    """Dispatch the per-type detail block for ``item``.

    ``group_for`` folds an unrecognized wire type into MISC, so this
    lookup cannot miss.
    """
    _TYPE_DETAIL[inventory_list.group_for(item.item_type)](surface, rect, item)


def _draw_detail(
    surface: pygame.Surface,
    rect: pygame.Rect,
    item: InventoryItem | None,
) -> None:
    if item is None:
        return

    font.draw_text_left(
        surface,
        item.name,
        (rect.left, rect.top),
        _DETAIL_VALUE_SIZE,
        palette.FOREGROUND,
    )
    font.draw_text_left(
        surface,
        inventory_list.group_label(item.item_type),
        (rect.left, rect.top + _DETAIL_ROW_GAP),
        _DETAIL_LABEL_SIZE,
        palette.DIM,
    )
    font.draw_text_left(
        surface,
        f"QTY {item.count}",
        (rect.left, rect.top + 2 * _DETAIL_ROW_GAP),
        _DETAIL_LABEL_SIZE,
        palette.FOREGROUND,
    )
    if inventory_list.is_equipped(item):
        font.draw_text_left(
            surface,
            f"EQUIPPED {item.slot.upper()}",
            (rect.left, rect.top + 3 * _DETAIL_ROW_GAP),
            _DETAIL_LABEL_SIZE,
            palette.FOREGROUND,
        )

    _render_type_detail(surface, rect, item)


def render_inventory(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
) -> None:
    """Draw the item list and its detail pane into the body rect."""
    inner = body_inner_rect(body_rect)
    items = state.player.inventory
    if not items:
        font.draw_text_centered(
            surface, EMPTY_TEXT, inner, _EMPTY_SIZE, palette.FOREGROUND
        )
        return

    rows = inventory_list.build_rows(items)
    cursor = scroll_list.resolve_cursor(rows, focus.cursor)
    list_rect = list_rect_for(body_rect)
    viewport_rows = viewport_rows_for(body_rect)

    for offset, (_index, row) in enumerate(
        scroll_list.visible(rows, cursor, viewport_rows)
    ):
        row_rect = pygame.Rect(
            list_rect.left,
            list_rect.top + offset * _ROW_HEIGHT,
            list_rect.width,
            _ROW_HEIGHT,
        )
        if not row.selectable:
            _draw_heading(surface, row_rect, row.label)
            continue
        item = inventory_list.item_for_key(items, row.key)
        if item is None:
            continue
        _draw_item_row(
            surface,
            row_rect,
            item,
            row.label,
            selected=row.key == cursor.selected_key,
            activated=focus.activated,
        )

    rule_y = list_rect.top + viewport_rows * _ROW_HEIGHT + _DETAIL_GAP
    pygame.draw.rect(
        surface,
        palette.DIM,
        pygame.Rect(inner.left, rule_y, inner.width, _RULE_HEIGHT),
    )

    detail_rect = pygame.Rect(
        inner.left,
        rule_y + _RULE_HEIGHT + _DETAIL_GAP,
        inner.width,
        _DETAIL_HEIGHT - _DETAIL_GAP,
    )
    _draw_detail(
        surface, detail_rect, inventory_list.item_for_key(items, cursor.selected_key)
    )
