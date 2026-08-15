"""Render tests for the STATUS/INVENTORY list (TASK-018).

Covers the empty state, the focus rule (the solid fill marks whatever the
encoder drives), the per-type seam being total, and both axes of the body
budget. The budget is checked arithmetically rather than by scanning
pixels because pygame clips silently at the surface edge — an overflowing
row simply vanishes and leaves nothing to scan for.
"""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import palette
from companion_app.state import (
    AppState,
    ConnectionState,
    InventoryItem,
    PlayerState,
)
from companion_app.ui import inventory_list, scroll_list, sections, slot_icons
from companion_app.ui.layout import Layout
from companion_app.ui.pages import inventory as inventory_page
from companion_app.ui.pages.inventory import EMPTY_TEXT, render_inventory
from companion_app.ui.scroll_list import ListCursor
from companion_app.ui.shell import (
    PAGE_MARGIN_X,
    SUBHEADER_BAND_HEIGHT,
    VIRTUAL_HEIGHT,
    VIRTUAL_WIDTH,
)


def _item(
    pid: int,
    name: str,
    item_type: str,
    *,
    count: int = 1,
    slot: str = "none",
) -> InventoryItem:
    return InventoryItem(
        pid=pid, name=name, item_type=item_type, count=count, slot=slot
    )


def _state(items: list[InventoryItem]) -> AppState:
    return AppState(
        connection=ConnectionState.READY,
        player=PlayerState(available=True, inventory=items),
    )


class InventoryRenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.surface = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
        content = Layout((VIRTUAL_WIDTH, VIRTUAL_HEIGHT)).content_rect
        self.body = content.copy()
        self.body.top += SUBHEADER_BAND_HEIGHT
        self.body.height = content.height - SUBHEADER_BAND_HEIGHT

    def _focus(
        self, *, activated: bool, cursor: ListCursor | None = None
    ) -> sections.SubSectionFocus:
        return sections.SubSectionFocus(
            activated=activated, cursor=cursor or ListCursor()
        )

    def _render(
        self, items: list[InventoryItem], *, activated: bool = False
    ) -> pygame.Surface:
        render_inventory(
            self.surface, self.body, _state(items), self._focus(activated=activated)
        )
        return self.surface

    def _cursor_on(self, items: list[InventoryItem], key: str) -> ListCursor:
        rows = inventory_list.build_rows(items)
        return scroll_list.resolve_cursor(rows, ListCursor(key))

    # ── empty state ────────────────────────────────────────────────

    def test_empty_inventory_renders_the_empty_message(self) -> None:
        self._render([])
        # Something was drawn in phosphor near the middle of the body.
        painted = any(
            tuple(self.surface.get_at((x, self.body.centery)))[:3]
            == palette.FOREGROUND
            for x in range(self.body.left, self.body.right)
        )
        self.assertTrue(painted, "expected the empty message on the centre line")

    def test_empty_message_text_is_the_agreed_string(self) -> None:
        self.assertEqual(EMPTY_TEXT, "No items available")

    # ── focus rule ─────────────────────────────────────────────────

    def _selected_row_rect(self, items: list[InventoryItem], key: str) -> pygame.Rect:
        """Walk the same variable-height layout the renderer walks."""
        rows = inventory_list.build_rows(items)
        cursor = self._cursor_on(items, key)
        list_rect = inventory_page.list_rect_for(self.body)
        y = list_rect.top
        for _index, row in inventory_page.visible_rows_for(self.body, rows, cursor):
            height = inventory_page.row_height(row)
            if row.key == cursor.selected_key:
                return pygame.Rect(list_rect.left, y, list_rect.width, height)
            y += height
        raise AssertionError("selected row is not visible")

    def test_activated_selection_is_filled(self) -> None:
        items = [_item(1, "Stimpak", "drug")]
        rect = self._selected_row_rect(items, "1:none:0")
        render_inventory(
            self.surface,
            self.body,
            _state(items),
            self._focus(activated=True, cursor=self._cursor_on(items, "1:none:0")),
        )
        # Interior of the row is solid phosphor.
        mid = (rect.left + rect.width // 2, rect.centery)
        self.assertEqual(tuple(self.surface.get_at(mid))[:3], palette.FOREGROUND)

    def test_deactivated_selection_is_outlined_not_filled(self) -> None:
        items = [_item(1, "Stimpak", "drug")]
        rect = self._selected_row_rect(items, "1:none:0")
        render_inventory(
            self.surface,
            self.body,
            _state(items),
            self._focus(activated=False, cursor=self._cursor_on(items, "1:none:0")),
        )
        # The border is drawn...
        self.assertEqual(
            tuple(self.surface.get_at((rect.centerx, rect.top)))[:3],
            palette.FOREGROUND,
        )
        # ...but the interior is not filled. Sample just inside the border
        # and clear of the glyphs, on the right-hand side of the row.
        interior = (rect.right - 3, rect.centery)
        self.assertNotEqual(
            tuple(self.surface.get_at(interior))[:3], palette.FOREGROUND
        )

    # ── the per-type seam ──────────────────────────────────────────

    def test_every_wire_type_renders_without_raising(self) -> None:
        for index, (wire_type, _label) in enumerate(inventory_list.GROUP_ORDER):
            items = [_item(index + 1, f"Item{index}", wire_type)]
            with self.subTest(item_type=wire_type):
                self._render(items)

    def test_unrecognized_type_renders_without_raising(self) -> None:
        self._render([_item(1, "Mystery", "sasquatch")])

    def test_type_detail_dispatch_covers_every_group(self) -> None:
        for wire_type, _label in inventory_list.GROUP_ORDER:
            self.assertIn(wire_type, inventory_page._TYPE_DETAIL)

    # ── list content ───────────────────────────────────────────────

    def test_populated_list_and_detail_pane_render(self) -> None:
        items = [
            _item(1, "10mm Pistol", "weapon", slot="rightHand"),
            _item(2, "Stimpak", "drug", count=5),
        ]
        self._render(items, activated=True)
        # The detail pane region has been written to.
        detail_top = inventory_page.detail_rect_for(self.body).top
        painted = any(
            tuple(self.surface.get_at((x, y)))[:3] != palette.BACKGROUND
            for y in range(detail_top, min(self.body.bottom, detail_top + 100))
            for x in range(self.body.left + PAGE_MARGIN_X, self.body.right - PAGE_MARGIN_X, 4)
        )
        self.assertTrue(painted, "expected the detail pane to draw something")

    def test_long_list_renders_only_the_viewport(self) -> None:
        items = [_item(n, f"Item {n:03d}", "misc") for n in range(200)]
        self._render(items, activated=True)  # must not raise or overflow

    # ── slot symbols ───────────────────────────────────────────────

    def _row_icon_box(self, row_rect: pygame.Rect) -> pygame.Rect:
        """The symbol's box in a row, derived the way the renderer derives it."""
        centery = (
            row_rect.top
            + inventory_page._ROW_PAD_Y
            + inventory_page._ROW_TEXT_HALF_HEIGHT
        )
        return pygame.Rect(
            row_rect.right - inventory_page._ROW_PAD_X - slot_icons.ICON_WIDTH,
            centery - slot_icons.ICON_HEIGHT // 2,
            slot_icons.ICON_WIDTH,
            slot_icons.ICON_HEIGHT,
        )

    def _icon_signature(
        self, box: pygame.Rect, color: tuple[int, int, int]
    ) -> frozenset[tuple[int, int]]:
        """Which pixels inside ``box`` carry ``color``, box-relative."""
        return frozenset(
            (x - box.left, y - box.top)
            for x in range(box.left, box.right)
            for y in range(box.top, box.bottom)
            if tuple(self.surface.get_at((x, y)))[:3] == color
        )

    def _render_single(
        self, slot: str, *, activated: bool = False
    ) -> tuple[pygame.Rect, list[InventoryItem]]:
        items = [_item(1, "10mm Pistol", "weapon", slot=slot)]
        row_rect = self._selected_row_rect(items, f"1:{slot}:0")
        self.surface.fill(palette.BACKGROUND)
        render_inventory(
            self.surface,
            self.body,
            _state(items),
            self._focus(
                activated=activated, cursor=self._cursor_on(items, f"1:{slot}:0")
            ),
        )
        return row_rect, items

    def test_every_equipped_slot_draws_a_symbol_in_the_row(self) -> None:
        for slot in ("rightHand", "leftHand", "worn"):
            with self.subTest(slot=slot):
                row_rect, _items = self._render_single(slot)
                box = self._row_icon_box(row_rect)
                self.assertTrue(
                    self._icon_signature(box, palette.FOREGROUND),
                    f"{slot} drew no symbol in the row's right-hand column",
                )

    def test_stowed_row_draws_no_symbol(self) -> None:
        row_rect, _items = self._render_single("none")
        box = self._row_icon_box(row_rect)
        self.assertFalse(
            self._icon_signature(box, palette.FOREGROUND),
            "a stowed item marked its row",
        )

    def test_the_three_symbols_are_distinguishable(self) -> None:
        """Left vs right in particular: mirrored shapes at 10px is the risk."""
        signatures: dict[str, frozenset[tuple[int, int]]] = {}
        for slot in ("rightHand", "leftHand", "worn"):
            row_rect, _items = self._render_single(slot)
            signatures[slot] = self._icon_signature(
                self._row_icon_box(row_rect), palette.FOREGROUND
            )
        self.assertNotEqual(signatures["rightHand"], signatures["leftHand"])
        self.assertNotEqual(signatures["rightHand"], signatures["worn"])
        self.assertNotEqual(signatures["leftHand"], signatures["worn"])

    def test_symbol_inverts_on_an_activated_row(self) -> None:
        """Foreground-on-foreground would erase the mark inside the fill."""
        row_rect, _items = self._render_single("rightHand", activated=True)
        box = self._row_icon_box(row_rect)
        self.assertTrue(
            self._icon_signature(box, palette.BACKGROUND),
            "the symbol did not invert with the row",
        )

    def test_unknown_slot_value_draws_nothing_and_does_not_raise(self) -> None:
        """A schema that grows a slot must not blank or crash a row."""
        self._render([_item(1, "Mystery", "weapon", slot="tail")])
        self.assertFalse(slot_icons.has_icon("tail"))

    def _detail_slot_value_box(self) -> pygame.Rect:
        rect = inventory_page.detail_rect_for(self.body)
        y = (
            rect.top
            + inventory_page._DETAIL_ROWS_TOP
            + 2 * inventory_page._DETAIL_ROW_GAP
        )
        centery = y + inventory_page._DETAIL_TEXT_HALF_HEIGHT
        return pygame.Rect(
            rect.left + inventory_page._DETAIL_VALUE_X,
            centery - slot_icons.ICON_HEIGHT // 2,
            slot_icons.ICON_WIDTH,
            slot_icons.ICON_HEIGHT,
        )

    def test_detail_slot_row_shows_the_symbol_not_the_word(self) -> None:
        for slot in ("rightHand", "leftHand", "worn"):
            with self.subTest(slot=slot):
                self._render_single(slot)
                self.assertTrue(
                    self._icon_signature(
                        self._detail_slot_value_box(), palette.FOREGROUND
                    ),
                    f"{slot} drew no symbol in the readout's SLOT row",
                )

    def test_detail_slot_row_keeps_the_word_for_a_stowed_item(self) -> None:
        """"Not equipped" has no symbol; an empty value would read as a fault."""
        self._render_single("none")
        self.assertTrue(
            self._icon_signature(self._detail_slot_value_box(), palette.FOREGROUND),
            "the readout's SLOT value is blank for a stowed item",
        )

    # ── per-type detail (TASK-019) ─────────────────────────────────

    def _labels(self, item: InventoryItem) -> list[str]:
        return [f.label for f in inventory_page.detail_fields_for(item)]

    def _value(self, item: InventoryItem, label: str) -> str:
        for field in inventory_page.detail_fields_for(item):
            if field.label == label:
                return field.value
        raise AssertionError(f"{label} not in {self._labels(item)}")

    def test_common_block_is_on_every_type(self) -> None:
        for wire_type, _label in inventory_list.GROUP_ORDER:
            with self.subTest(item_type=wire_type):
                labels = self._labels(_item(1, "X", wire_type))
                self.assertEqual(labels[:5], ["TYPE", "QTY", "SLOT", "WT", "VAL"])

    def test_weapon_shows_damage_range_strength_and_ammo(self) -> None:
        weapon = _item(1, "10mm Pistol", "weapon")
        weapon.dmg_min, weapon.dmg_max = 5, 12
        weapon.weapon_range, weapon.min_st = 25, 3
        weapon.ammo_current, weapon.ammo_max = 8, 12
        weapon.ammo_name = "10mm JHP"
        self.assertEqual(self._value(weapon, "DMG"), "5-12")
        self.assertEqual(self._value(weapon, "RNG"), "25")
        self.assertEqual(self._value(weapon, "MIN ST"), "3")
        self.assertEqual(self._value(weapon, "AMMO"), "8/12 10mm JHP")

    def test_weapon_without_a_resolvable_ammo_name_still_shows_counts(self) -> None:
        weapon = _item(1, "Odd Gun", "weapon")
        weapon.ammo_current, weapon.ammo_max = 2, 6
        self.assertEqual(self._value(weapon, "AMMO"), "2/6")

    def test_melee_weapon_omits_ammo_and_keeps_damage(self) -> None:
        knife = _item(1, "Knife", "weapon")
        knife.dmg_min, knife.dmg_max = 1, 8
        self.assertIn("DMG", self._labels(knife))
        self.assertNotIn("AMMO", self._labels(knife))

    def test_ammo_shows_total_rounds_not_the_stack_count(self) -> None:
        """Two partially-used boxes: the figure matches neither count nor load."""
        ammo = _item(1, "10mm JHP", "ammo", count=2)
        ammo.total_rounds, ammo.caliber = 31, 4
        self.assertEqual(self._value(ammo, "RNDS"), "31")
        self.assertNotEqual(self._value(ammo, "RNDS"), self._value(ammo, "QTY"))
        self.assertEqual(self._value(ammo, "CAL"), "4")

    def test_armor_shows_armor_class(self) -> None:
        armor = _item(1, "Leather Armor", "armor")
        armor.armor_class = 8
        self.assertEqual(self._value(armor, "AC"), "8")

    def test_misc_shows_charges_and_caps_shows_amount(self) -> None:
        lockpick = _item(1, "Lockpick", "misc")
        lockpick.charges_current, lockpick.charges_max = 3, 10
        self.assertEqual(self._value(lockpick, "CHG"), "3/10")

        caps = _item(2, "Bottle Caps", "misc")
        caps.caps_amount = 1200
        self.assertEqual(self._value(caps, "CAPS"), "1200")
        # Caps are misc-typed; they must not also claim a charges row.
        self.assertNotIn("CHG", self._labels(caps))

    def test_types_with_nothing_to_add_show_only_the_common_block(self) -> None:
        for wire_type in ("drug", "key", "container"):
            with self.subTest(item_type=wire_type):
                self.assertEqual(len(self._labels(_item(1, "X", wire_type))), 5)

    def test_unknown_type_shows_only_the_common_block(self) -> None:
        self.assertEqual(len(self._labels(_item(1, "Mystery", "sasquatch"))), 5)

    def test_absent_fields_produce_no_row(self) -> None:
        """The -1 sentinel means "does not apply", and 0 is a real value."""
        empty_gun = _item(1, "Empty Gun", "weapon")
        empty_gun.ammo_current, empty_gun.ammo_max = 0, 12
        self.assertEqual(self._value(empty_gun, "AMMO"), "0/12")
        self.assertNotIn("DMG", self._labels(empty_gun))

    def test_every_field_set_fits_the_readout(self) -> None:
        """The pane's row budget, asserted rather than assumed.

        The pre-TASK-019 pane held four baselines and the common block alone
        would have needed five, so this is the guard on the reshape.
        """
        weapon = _item(1, "Weapon", "weapon")
        weapon.dmg_min, weapon.dmg_max = 5, 12
        weapon.weapon_range, weapon.min_st = 25, 3
        weapon.ammo_current, weapon.ammo_max = 8, 12
        weapon.ammo_name = "10mm JHP"
        candidates = [weapon] + [
            _item(2, "X", wire_type) for wire_type, _label in inventory_list.GROUP_ORDER
        ]
        rect = inventory_page.detail_rect_for(self.body)
        for item in candidates:
            with self.subTest(item_type=item.item_type):
                rows = inventory_page.pack_detail_rows(
                    inventory_page.detail_fields_for(item)
                )
                lowest = (
                    rect.top
                    + inventory_page._DETAIL_ROWS_TOP
                    + (len(rows) - 1) * inventory_page._DETAIL_ROW_GAP
                    + 2 * inventory_page._DETAIL_TEXT_HALF_HEIGHT
                )
                self.assertLessEqual(
                    lowest, rect.bottom, f"{len(rows)} rows overflow the readout"
                )

    def test_wide_field_gets_its_own_row(self) -> None:
        pack = inventory_page.pack_detail_rows
        Field = inventory_page.Field
        rows = pack([Field("A", "1"), Field("B", "2", wide=True), Field("C", "3")])
        self.assertEqual([len(r) for r in rows], [1, 1, 1])
        rows = pack([Field("A", "1"), Field("B", "2"), Field("C", "3")])
        self.assertEqual([len(r) for r in rows], [2, 1])

    def test_populated_detail_renders_for_every_type(self) -> None:
        for wire_type, _label in inventory_list.GROUP_ORDER:
            with self.subTest(item_type=wire_type):
                item = _item(1, "X", wire_type)
                item.dmg_min = item.dmg_max = 4
                item.armor_class = item.caliber = item.total_rounds = 2
                item.charges_current = item.charges_max = 1
                self._render([item], activated=True)

    # ── body budget, both axes ─────────────────────────────────────

    def test_content_stays_inside_the_body_bottom(self) -> None:
        self.assertLessEqual(
            inventory_page.inventory_content_bottom(self.body), self.body.bottom
        )

    def test_readout_bottom_is_strictly_inside_the_surface(self) -> None:
        """A box bottom drawn *at* body.bottom is clipped away entirely.

        pygame's last drawable row is ``bottom - 1``, so landing exactly on
        ``bottom`` silently removes the readout's lower brackets. Regression
        guard for that specific mistake, which the first styling pass made.
        """
        self.assertLess(
            inventory_page.inventory_content_bottom(self.body), self.body.bottom
        )

    def test_readout_lower_brackets_are_actually_drawn(self) -> None:
        """Pixel proof, since an arithmetic bound alone missed this once."""
        self._render([_item(1, "Stimpak", "drug", count=3)], activated=True)
        rect = inventory_page.detail_rect_for(self.body)
        painted = [
            x
            for x in range(rect.left, rect.right)
            if tuple(self.surface.get_at((x, rect.bottom - 1)))[:3]
            == palette.FOREGROUND
        ]
        self.assertTrue(painted, "readout bottom bracket row is blank")

    def test_attribute_rows_sit_at_the_same_height_for_every_item(self) -> None:
        """Names with descenders must not push the attribute rows down.

        ``font.get_rect`` returns the glyph bounding box, so deriving the
        first row's y from the drawn name made "Stimpak" (descender) lay out
        differently from "Leather Armor" (none). The offset is fixed now;
        this compares the two rendered panels row-band by row-band.
        """
        rect = inventory_page.detail_rect_for(self.body)
        band = range(rect.top + 30, rect.bottom - 1)

        def row_profile(item: InventoryItem) -> list[int]:
            self.surface.fill(palette.BACKGROUND)
            render_inventory(
                self.surface,
                self.body,
                _state([item]),
                self._focus(
                    activated=True,
                    cursor=self._cursor_on([item], f"{item.pid}:{item.slot}:0"),
                ),
            )
            # Which scanlines inside the attribute area carry any ink.
            return [
                y
                for y in band
                if any(
                    tuple(self.surface.get_at((x, y)))[:3] != palette.BACKGROUND
                    for x in range(rect.left + 10, rect.right - 10, 2)
                )
            ]

        with_descender = row_profile(_item(1, "Stimpak", "drug", count=3))
        without = row_profile(_item(2, "Leather Armor", "armor"))
        self.assertTrue(with_descender, "no attribute rows rendered")
        # Same first and last inked scanline => same vertical placement.
        self.assertEqual(with_descender[0], without[0])
        self.assertEqual(with_descender[-1], without[-1])

    def test_group_heading_leaves_air_above_its_label(self) -> None:
        """The gap belongs above a heading, separating it from the group before.

        A heading row is taller than an item row, and the extra height is
        air above the label — so the visual break lands between groups, not
        between a heading and the items under it.
        """
        self.assertGreater(
            inventory_page._HEADING_ROW_HEIGHT, inventory_page._ROW_HEIGHT
        )
        # The label sits in the lower part of its own row.
        self.assertGreater(
            inventory_page._HEADING_LABEL_Y, inventory_page._HEADING_ROW_HEIGHT // 2
        )
        # And still inside it.
        self.assertLessEqual(
            inventory_page._HEADING_LABEL_Y + inventory_page._HEADING_SIZE,
            inventory_page._HEADING_ROW_HEIGHT,
        )

    def test_content_stays_inside_the_body_right_edge(self) -> None:
        """The rect handed in is the full 480px; the renderer insets itself."""
        self.assertLessEqual(
            inventory_page.inventory_content_right(self.body), self.body.right
        )

    def test_body_is_inset_by_the_shared_page_margin(self) -> None:
        inner = inventory_page.body_inner_rect(self.body)
        self.assertEqual(inner.left, self.body.left + PAGE_MARGIN_X)
        self.assertEqual(inner.width, self.body.width - 2 * PAGE_MARGIN_X)
        # The documented usable width, now that it is actually established.
        self.assertEqual(inner.width, 424)

    def test_viewport_holds_at_least_a_screenful_of_rows(self) -> None:
        items = [_item(n, f"Item {n:03d}", "misc") for n in range(60)]
        rows = inventory_list.build_rows(items)
        cursor = self._cursor_on(items, "0:none:0")
        visible = inventory_page.visible_rows_for(self.body, rows, cursor)
        self.assertGreaterEqual(len(visible), 10)

    def test_visible_rows_never_overflow_the_list_area(self) -> None:
        """Variable row heights must still fit the viewport exactly."""
        items = [_item(n, f"Item {n:03d}", t) for n, t in enumerate(
            ["weapon", "ammo", "armor", "drug", "misc", "key", "container"] * 6
        )]
        rows = inventory_list.build_rows(items)
        list_height = inventory_page.list_rect_for(self.body).height
        for key in ("0:none:0", "20:none:0", f"{len(items) - 1}:none:0"):
            with self.subTest(selected=key):
                cursor = self._cursor_on(items, key)
                visible = inventory_page.visible_rows_for(self.body, rows, cursor)
                total = sum(
                    inventory_page.row_height(row) for _index, row in visible
                )
                self.assertLessEqual(total, list_height)


if __name__ == "__main__":
    unittest.main()
