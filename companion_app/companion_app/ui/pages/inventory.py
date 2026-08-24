"""STATUS/INVENTORY sub-section — the scrollable item list (TASK-018).

Was a placeholder until TASK-018. Renders a type-grouped, infinitely
scrolling list with a live detail readout beneath it: the readout follows
the selection, so there is no second ``Confirm``/``Back`` level and no
depth to lose track of.

The focus rule is shared with the sub-header: **the solid inverse fill
always marks whatever the encoder currently drives.** Activated, the
selected row is filled and the sub-header segment is outlined; back at the
sub-section row it is the other way round. Exactly one filled element on
screen at any time, which is the entire focus indicator — a breadcrumb
would not fit on a 480x800 device.

**Styling reuses the CHARACTER sub-section's vocabulary** rather than
inventing a second one, so both halves of STATUS read as one instrument:
group headings are ruled section headers (the ``S.P.E.C.I.A.L.`` /
``STATUS FX`` treatment), rows carry the ``>`` chevron and an aligned
right-hand value column (the ``> CND: INJURED`` treatment), and the detail
readout is corner-bracketed (the ``LVL/XP/NX`` treatment). The one new
mark is the scroll gutter, which borrows the S.P.E.C.I.A.L. bar's
filled-segment look.

**The equipped slot is a symbol, not a word.** ``[R.HAND]`` / ``[L.HAND]`` /
``[WORN]`` were replaced by drawn marks (``ui/slot_icons``) in both the row's
right-hand column and the detail readout's ``SLOT`` value, so the marker reads
at a glance and stops competing with the stack count for the width of a 480px
row. They are drawn rather than typed because the vendored font has no symbol
glyphs at all — see that module.

``_TYPE_DETAIL`` is the per-type seam TASK-018 left open and TASK-019
filled: it dispatches over all seven engine item types, and each entry now
returns the fields that type contributes to the readout — damage/ammo/range
for a weapon, total rounds for an ammo stack, armor class, charges, caps.
The dispatch stays total, so a type that gains fields later replaces an
entry rather than adding a branch.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState, InventoryItem
from companion_app.ui import inventory_list, list_geometry, scroll_list, slot_icons

if TYPE_CHECKING:
    from companion_app.ui.sections import SubSectionFocus

EMPTY_TEXT: str = "No items available"
_EMPTY_SIZE: int = 20

# Sizes track the CHARACTER block scale (rows 13, sections 14) so the two
# sub-sections look like one screen.
_HEADING_SIZE: int = 14
_DETAIL_NAME_SIZE: int = 15
_DETAIL_ROW_SIZE: int = 13

# Row metrics moved to ``ui/list_geometry`` when ARCHIVES/QUESTS became the
# device's second scrolling list (TASK-021). Aliased rather than re-spelled,
# so this file reads as it did and the two lists cannot drift apart.
_ROW_SIZE: int = list_geometry.ROW_SIZE
_ROW_HEIGHT: int = list_geometry.ROW_HEIGHT
_ROW_PAD_X: int = list_geometry.ROW_PAD_X
_ROW_PAD_Y: int = list_geometry.ROW_PAD_Y

# A group heading gets a taller row than an item, and the extra height is
# all air *above* the label. That is what separates one type-section from
# the previous one — a full spacer row would cost twice as much viewport,
# and padding inside a 26px row cannot fit more than a few pixels.
_HEADING_ROW_HEIGHT: int = 44

# Group heading: label then a rule out to the right edge, matching
# status.py's _draw_section_header.
_HEADING_RULE_GAP: int = 14
_HEADING_RULE_Y_OFFSET: int = 4
# Where the label sits inside its taller row: low, so the air lands above
# the heading rather than between a heading and the items it belongs to.
_HEADING_LABEL_Y: int = 24

# Scroll gutter on the right, drawn only when the list overflows.
_GUTTER_WIDTH: int = list_geometry.GUTTER_WIDTH
_GUTTER_GAP: int = list_geometry.GUTTER_GAP

# Corner-bracketed detail readout at the bottom of the body.
#
# TASK-019 raised the height from 132 to 174 and paired the fields two per
# row. At 132 the usable baselines were 46 / 67 / 88 / 109 — only four fit a
# 12px glyph box — and TYPE/QTY/SLOT already took three, so the common block
# alone overflowed once weight and value joined it, before a single per-type
# row existed. Six baselines at two fields each gives twelve slots against a
# weapon's nine. The 42px comes out of the list viewport (~1.6 rows of 26),
# which the readout earns now that it carries real data.
_DETAIL_HEIGHT: int = 174
_DETAIL_GAP: int = 12
_DETAIL_CORNER: int = 20
_DETAIL_PAD_X: int = 16
_DETAIL_PAD_Y: int = 12
_DETAIL_ROW_GAP: int = 21
_DETAIL_LABEL_X: int = 16
_DETAIL_VALUE_X: int = 104
# Second field column, mirroring the first at half the inner width.
_DETAIL_LABEL_X2: int = 224
_DETAIL_VALUE_X2: int = 312
# Fixed offset from the panel top to the first attribute row. Deliberately
# NOT derived from the name's measured rect: `font.get_rect` returns the
# glyph bounding box, so a name with a descender ("Stimpak") measures
# taller than one without ("Leather Armor") and the attribute rows would
# sit at a different height per item.
_DETAIL_ROWS_TOP: int = 46

_OUTLINE_WIDTH: int = list_geometry.OUTLINE_WIDTH

# Vertical breathing room inside the body. The bottom margin is load-bearing,
# not decoration: without it the readout's lower brackets land on the row
# *past* the last pixel and pygame clips them silently, leaving a box with no
# bottom. CHARACTER keeps a comparable margin below STATUS FX.
_BODY_MARGIN_TOP: int = list_geometry.BODY_MARGIN_TOP
_BODY_MARGIN_BOTTOM: int = list_geometry.BODY_MARGIN_BOTTOM

# The equipped slot is a drawn symbol, not a word — see ``ui/slot_icons``.
# ``STOWED`` stays a word in the detail readout because "not equipped" has no
# symbol; an empty value row there would read as a missing field.
_STOWED_TAG: str = "STOWED"

# Gap between the stack count and the slot symbol in the row's right column.
_SUFFIX_GAP: int = 6

# Half the height of a non-descender glyph box at each text size, used to
# centre a symbol on its line. Measured, not derived from a rendered rect:
# ``font.get_rect`` returns the glyph bounding box, so "Stimpak" measures
# taller than "Leather Armor" and an icon aligned to it would jitter per item
# — the same trap ``_DETAIL_ROWS_TOP`` exists to avoid.
_ROW_TEXT_HALF_HEIGHT: int = 6
_DETAIL_TEXT_HALF_HEIGHT: int = 6


def body_inner_rect(body_rect: pygame.Rect) -> pygame.Rect:
    """The body inset to the shared page margin on both sides.

    Delegates to ``list_geometry`` (TASK-021), which ARCHIVES/QUESTS shares;
    kept as a name here because callers and tests reference it.
    """
    return list_geometry.body_inner_rect(body_rect)


def list_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The rows area: inner body, above the readout, left of the gutter.

    The gutter is excluded whether or not it is drawn, so a row's geometry
    does not change when a list grows past the viewport.
    """
    inner = body_inner_rect(body_rect)
    rect = inner.copy()
    rect.width = inner.width - _GUTTER_WIDTH - _GUTTER_GAP
    rect.height = inner.height - _DETAIL_HEIGHT - _DETAIL_GAP
    return rect


def gutter_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The scroll-indicator track, hugging the inner right edge."""
    inner = body_inner_rect(body_rect)
    list_rect = list_rect_for(body_rect)
    return pygame.Rect(
        inner.right - _GUTTER_WIDTH,
        list_rect.top,
        _GUTTER_WIDTH,
        list_rect.height,
    )


def row_height(row: scroll_list.ListRow) -> int:
    """Headings are taller than items; see ``_HEADING_ROW_HEIGHT``."""
    return _ROW_HEIGHT if row.selectable else _HEADING_ROW_HEIGHT


def visible_rows_for(
    body_rect: pygame.Rect,
    rows: tuple[scroll_list.ListRow, ...],
    cursor: scroll_list.ListCursor,
) -> tuple[tuple[int, scroll_list.ListRow], ...]:
    """The window this body rect can show, given variable row heights."""
    return scroll_list.visible(
        rows, cursor, list_rect_for(body_rect).height, row_height
    )


def detail_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The corner-bracketed readout panel at the bottom of the body."""
    inner = body_inner_rect(body_rect)
    list_rect = list_rect_for(body_rect)
    return pygame.Rect(
        inner.left,
        list_rect.top + list_rect.height + _DETAIL_GAP,
        inner.width,
        _DETAIL_HEIGHT,
    )


def inventory_content_bottom(body_rect: pygame.Rect) -> int:
    """Absolute y of the lowest pixel this sub-section draws.

    Derived from the same constants the renderer uses, for the reason
    ``status.character_content_bottom`` exists: pygame clips silently at
    the surface edge, so an overflowing block simply disappears and leaves
    nothing in the rendered output for a pixel-scanning test to find.
    """
    return detail_rect_for(body_rect).bottom


def inventory_content_right(body_rect: pygame.Rect) -> int:
    """Absolute x of the rightmost pixel this sub-section may draw."""
    return body_inner_rect(body_rect).right


def _draw_group_heading(
    surface: pygame.Surface,
    rect: pygame.Rect,
    label: str,
    right_x: int,
) -> None:
    """Label plus a rule to the right edge — the S.P.E.C.I.A.L. treatment."""
    label_rect = font.draw_text_left(
        surface,
        label,
        (rect.left, rect.top + _HEADING_LABEL_Y),
        _HEADING_SIZE,
        palette.FOREGROUND,
    )
    rule_y = label_rect.centery + _HEADING_RULE_Y_OFFSET
    pygame.draw.line(
        surface,
        palette.FOREGROUND,
        (label_rect.right + _HEADING_RULE_GAP, rule_y),
        (right_x, rule_y),
        1,
    )


def _row_count_text(item: InventoryItem) -> str:
    """The stack count for the right-hand column, or empty for a single."""
    return f"x{item.count}" if item.count > 1 else ""


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

    # The "> label" chevron is the CHARACTER rows' idiom, applied to every
    # row rather than used as a selection cue — the box is the cue.
    font.draw_text_left(
        surface,
        f"> {label}",
        (rect.left + _ROW_PAD_X, rect.top + _ROW_PAD_Y),
        _ROW_SIZE,
        text_color,
    )
    # Right-hand column, laid out from the right edge inwards: the slot
    # symbol first, then the stack count beside it. Composed from measured
    # pieces rather than one right-anchored string, because a drawn icon has
    # no glyph metrics to concatenate.
    right = rect.right - _ROW_PAD_X
    icon_rect = slot_icons.draw_midright(
        surface,
        item.slot,
        (right, rect.top + _ROW_PAD_Y + _ROW_TEXT_HALF_HEIGHT),
        text_color,
    )
    if icon_rect is not None:
        right = icon_rect.left - _SUFFIX_GAP

    count = _row_count_text(item)
    if count:
        font.draw_text_right(
            surface,
            count,
            (right, rect.top + _ROW_PAD_Y),
            _ROW_SIZE,
            text_color,
        )


def _draw_corner_box(
    surface: pygame.Surface,
    rect: pygame.Rect,
    corner: int,
) -> None:
    """Corner brackets only — the LVL/XP/NX readout treatment."""
    left, top, right, bottom = rect.left, rect.top, rect.right, rect.bottom
    for start, end in (
        ((left, top), (left + corner, top)),
        ((left, top), (left, top + corner)),
        ((right - corner, top), (right, top)),
        ((right, top), (right, top + corner)),
        ((left, bottom - corner), (left, bottom)),
        ((left, bottom), (left + corner, bottom)),
        ((right - corner, bottom), (right, bottom)),
        ((right, bottom - corner), (right, bottom)),
    ):
        pygame.draw.line(surface, palette.FOREGROUND, start, end, 1)


def _draw_scroll_gutter(
    surface: pygame.Surface,
    rect: pygame.Rect,
    row_count: int,
    first_index: int,
    visible_count: int,
) -> None:
    """The scroll thumb — shared with ARCHIVES/QUESTS via ``list_geometry``."""
    list_geometry.draw_scroll_gutter(
        surface, rect, row_count, first_index, visible_count
    )


class SlotValue:
    """Marks a field whose value is the slot symbol rather than text."""

    __slots__ = ("slot",)

    def __init__(self, slot: str) -> None:
        self.slot = slot


class Field:
    """One ``LABEL value`` pair in the readout.

    ``wide`` gives the field a row to itself. Only ``AMMO`` needs it: its
    value carries an ammo name, which does not fit the 120px a half-row
    value column allows.
    """

    __slots__ = ("label", "value", "wide")

    def __init__(
        self, label: str, value: str | SlotValue, *, wide: bool = False
    ) -> None:
        self.label = label
        self.value = value
        self.wide = wide


def _absent(value: int) -> bool:
    """The server's "does not apply" sentinel — see `kCompanionItemFieldAbsent`."""
    return value < 0


def _weapon_fields(item: InventoryItem) -> list[Field]:
    fields: list[Field] = []
    if not _absent(item.dmg_min) and not _absent(item.dmg_max):
        # dmg_max already carries the melee-damage contribution; the server
        # applies it because it depends on the player, not the weapon.
        fields.append(Field("DMG", f"{item.dmg_min}-{item.dmg_max}"))
    if not _absent(item.weapon_range):
        fields.append(Field("RNG", str(item.weapon_range)))
    if not _absent(item.min_st):
        fields.append(Field("MIN ST", str(item.min_st)))
    if not _absent(item.ammo_current) and not _absent(item.ammo_max):
        loaded = f"{item.ammo_current}/{item.ammo_max}"
        if item.ammo_name:
            loaded = f"{loaded} {item.ammo_name}"
        fields.append(Field("AMMO", loaded, wide=True))
    return fields


def _ammo_fields(item: InventoryItem) -> list[Field]:
    fields: list[Field] = []
    if not _absent(item.total_rounds):
        # Not the stack count: the engine merges boxes holding different
        # numbers of rounds, so this is its own figure.
        fields.append(Field("RNDS", str(item.total_rounds)))
    if not _absent(item.caliber):
        fields.append(Field("CAL", str(item.caliber)))
    return fields


def _armor_fields(item: InventoryItem) -> list[Field]:
    if _absent(item.armor_class):
        return []
    return [Field("AC", str(item.armor_class))]


def _misc_fields(item: InventoryItem) -> list[Field]:
    # Caps are misc-typed but carry their amount on their own block, so they
    # must not be read as charges.
    if not _absent(item.caps_amount):
        return [Field("CAPS", str(item.caps_amount))]
    if _absent(item.charges_current) or _absent(item.charges_max):
        return []
    return [Field("CHG", f"{item.charges_current}/{item.charges_max}")]


def _no_extra_fields(item: InventoryItem) -> list[Field]:
    """Types the common block already describes fully."""
    _ = item
    return []


# The per-type seam, filled by TASK-019. Still total over the wire's seven
# `type` values, so a type that gains fields later replaces an entry rather
# than adding a dispatch.
_TypeDetailFields = Callable[[InventoryItem], "list[Field]"]

_TYPE_DETAIL: dict[str, _TypeDetailFields] = {
    "weapon": _weapon_fields,
    "ammo": _ammo_fields,
    "armor": _armor_fields,
    "drug": _no_extra_fields,
    "misc": _misc_fields,
    "key": _no_extra_fields,
    "container": _no_extra_fields,
}


def _type_detail_fields(item: InventoryItem) -> list[Field]:
    """The per-type fields for ``item``.

    ``group_for`` folds an unrecognized wire type into MISC, so this lookup
    cannot miss.
    """
    return _TYPE_DETAIL[inventory_list.group_for(item.item_type)](item)


def _draw_detail_field(
    surface: pygame.Surface,
    left: int,
    y: int,
    field: Field,
    *,
    label_x: int,
    value_x: int,
) -> None:
    """``> LABEL   value`` on an aligned value column, as CHARACTER does.

    A ``SlotValue`` draws the equipped-slot symbol instead of text — the
    readout is the list symbol's legend, same mark and same column as every
    other attribute. A stowed item has no symbol, so it keeps ``STOWED``: an
    empty value would read as a field that failed to load.
    """
    font.draw_text_left(
        surface,
        f"> {field.label}",
        (left + label_x, y),
        _DETAIL_ROW_SIZE,
        palette.FOREGROUND,
    )

    if isinstance(field.value, SlotValue):
        drawn = slot_icons.draw_midleft(
            surface,
            field.value.slot,
            (left + value_x, y + _DETAIL_TEXT_HALF_HEIGHT),
            palette.FOREGROUND,
        )
        if drawn is not None:
            return
        text = _STOWED_TAG
    else:
        text = field.value

    font.draw_text_left(
        surface,
        text,
        (left + value_x, y),
        _DETAIL_ROW_SIZE,
        palette.FOREGROUND,
    )


def pack_detail_rows(fields: list[Field]) -> list[list[Field]]:
    """Group fields two per row, giving a ``wide`` field its own row.

    Split out and named without an underscore because the row *count* is the
    pane's budget, and the budget is a test rather than a comment — see
    ``_DETAIL_HEIGHT``.
    """
    rows: list[list[Field]] = []
    pending: list[Field] = []
    for field in fields:
        if field.wide:
            if pending:
                rows.append(pending)
                pending = []
            rows.append([field])
            continue
        pending.append(field)
        if len(pending) == 2:
            rows.append(pending)
            pending = []
    if pending:
        rows.append(pending)
    return rows


def detail_fields_for(item: InventoryItem) -> list[Field]:
    """Every field the readout shows for ``item``, common block first."""
    return [
        Field("TYPE", inventory_list.group_label(item.item_type)),
        Field("QTY", str(item.count)),
        Field("SLOT", SlotValue(item.slot)),
        Field("WT", str(item.weight)),
        Field("VAL", str(item.value)),
        *_type_detail_fields(item),
    ]


def _draw_detail(
    surface: pygame.Surface,
    rect: pygame.Rect,
    item: InventoryItem | None,
) -> None:
    if item is None:
        return

    _draw_corner_box(surface, rect, _DETAIL_CORNER)

    font.draw_text_left(
        surface,
        item.name,
        (rect.left + _DETAIL_PAD_X, rect.top + _DETAIL_PAD_Y),
        _DETAIL_NAME_SIZE,
        palette.FOREGROUND,
    )

    # Fixed offset, not name_rect.bottom — see _DETAIL_ROWS_TOP.
    row_y = rect.top + _DETAIL_ROWS_TOP
    for index, row in enumerate(pack_detail_rows(detail_fields_for(item))):
        y = row_y + index * _DETAIL_ROW_GAP
        _draw_detail_field(
            surface,
            rect.left,
            y,
            row[0],
            label_x=_DETAIL_LABEL_X,
            value_x=_DETAIL_VALUE_X,
        )
        if len(row) > 1:
            _draw_detail_field(
                surface,
                rect.left,
                y,
                row[1],
                label_x=_DETAIL_LABEL_X2,
                value_x=_DETAIL_VALUE_X2,
            )


def render_inventory(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
) -> None:
    """Draw the item list and its detail readout into the body rect."""
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

    visible = visible_rows_for(body_rect, rows, cursor)
    y = list_rect.top
    for _index, row in visible:
        height = row_height(row)
        row_rect = pygame.Rect(list_rect.left, y, list_rect.width, height)
        y += height
        if not row.selectable:
            _draw_group_heading(surface, row_rect, row.label, list_rect.right)
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

    _draw_scroll_gutter(
        surface,
        gutter_rect_for(body_rect),
        len(rows),
        visible[0][0] if visible else 0,
        len(visible),
    )

    _draw_detail(
        surface,
        detail_rect_for(body_rect),
        inventory_list.item_for_key(items, cursor.selected_key),
    )
