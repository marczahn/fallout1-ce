"""Unit tests for the inventory list projection (TASK-018).

Grouping, ordering, row keys, and the selection anchoring that has to
survive the wholesale replacement the network layer performs on every
inventory update. Pure data — no pygame, no display.
"""
from __future__ import annotations

import unittest

from companion_app.state import InventoryItem
from companion_app.ui import inventory_list, scroll_list
from companion_app.ui.scroll_list import ListCursor


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


def _labels(items: list[InventoryItem]) -> list[str]:
    return [row.label for row in inventory_list.build_rows(items)]


class GroupingTests(unittest.TestCase):
    def test_groups_follow_the_declared_display_order(self) -> None:
        items = [
            _item(1, "Key", "key"),
            _item(2, "Stimpak", "drug"),
            _item(3, "10mm Pistol", "weapon"),
        ]
        self.assertEqual(
            _labels(items),
            ["WEAPONS", "10mm Pistol", "AID", "Stimpak", "KEYS", "Key"],
        )

    def test_empty_groups_are_omitted(self) -> None:
        labels = _labels([_item(1, "Stimpak", "drug")])
        self.assertEqual(labels, ["AID", "Stimpak"])
        self.assertNotIn("WEAPONS", labels)

    def test_aid_is_the_heading_for_drugs(self) -> None:
        """AID over HEALTH, by explicit choice; stimpaks are ITEM_TYPE_DRUG."""
        self.assertEqual(inventory_list.group_label("drug"), "AID")

    def test_headings_are_never_selectable(self) -> None:
        rows = inventory_list.build_rows([_item(1, "Stimpak", "drug")])
        self.assertFalse(rows[0].selectable)
        self.assertTrue(rows[1].selectable)

    def test_items_are_alphabetical_within_a_group(self) -> None:
        items = [
            _item(1, "Sledgehammer", "weapon"),
            _item(2, "Combat Knife", "weapon"),
            _item(3, "10mm Pistol", "weapon"),
        ]
        self.assertEqual(
            _labels(items),
            ["WEAPONS", "10mm Pistol", "Combat Knife", "Sledgehammer"],
        )

    def test_ordering_is_case_insensitive(self) -> None:
        items = [_item(1, "beer", "misc"), _item(2, "Ammo box", "misc")]
        self.assertEqual(_labels(items), ["MISC", "Ammo box", "beer"])

    def test_unknown_type_lands_in_misc(self) -> None:
        """A carried item must never be silently hidden."""
        labels = _labels([_item(1, "Mystery", "sasquatch")])
        self.assertEqual(labels, ["MISC", "Mystery"])

    def test_empty_type_lands_in_misc(self) -> None:
        self.assertEqual(_labels([_item(1, "Blank", "")]), ["MISC", "Blank"])

    def test_every_wire_type_produces_a_group(self) -> None:
        items = [
            _item(index, f"Item{index}", wire_type)
            for index, (wire_type, _label) in enumerate(inventory_list.GROUP_ORDER)
        ]
        rows = inventory_list.build_rows(items)
        headings = [row.label for row in rows if not row.selectable]
        self.assertEqual(
            headings, [label for _wire, label in inventory_list.GROUP_ORDER]
        )

    def test_empty_inventory_produces_no_rows(self) -> None:
        self.assertEqual(inventory_list.build_rows([]), ())


class RowKeyTests(unittest.TestCase):
    def test_occurrence_disambiguates_identical_pid_and_slot(self) -> None:
        """Containers never stack, so two empty backpacks are two entries."""
        items = [
            _item(7, "Backpack", "container"),
            _item(7, "Backpack", "container"),
        ]
        rows = inventory_list.build_rows(items)
        keys = [row.key for row in rows if row.selectable]
        self.assertEqual(keys, ["7:none:0", "7:none:1"])

    def test_slot_distinguishes_an_equipped_copy(self) -> None:
        items = [
            _item(5, "10mm Pistol", "weapon", slot="rightHand"),
            _item(5, "10mm Pistol", "weapon"),
        ]
        keys = [row.key for row in inventory_list.build_rows(items) if row.selectable]
        self.assertEqual(sorted(keys), ["5:none:0", "5:rightHand:0"])

    def test_heading_keys_cannot_collide_with_item_keys(self) -> None:
        rows = inventory_list.build_rows([_item(1, "Stimpak", "drug")])
        self.assertTrue(rows[0].key.startswith("#"))
        self.assertNotIn(":", rows[0].key)

    def test_item_for_key_round_trips(self) -> None:
        items = [_item(1, "Stimpak", "drug", count=5), _item(2, "Rope", "misc")]
        rows = inventory_list.build_rows(items)
        for row in rows:
            if not row.selectable:
                self.assertIsNone(inventory_list.item_for_key(items, row.key))
                continue
            found = inventory_list.item_for_key(items, row.key)
            self.assertIsNotNone(found)
            assert found is not None
            self.assertEqual(found.name, row.label)

    def test_item_for_key_returns_none_for_an_unknown_key(self) -> None:
        self.assertIsNone(inventory_list.item_for_key([], "1:none:0"))


class EquippedTests(unittest.TestCase):
    def test_wire_slot_values_are_recognized(self) -> None:
        for slot in ("worn", "rightHand", "leftHand"):
            self.assertTrue(inventory_list.is_equipped(_item(1, "X", "misc", slot=slot)))

    def test_none_slot_is_not_equipped(self) -> None:
        self.assertFalse(inventory_list.is_equipped(_item(1, "X", "misc")))


class AnchoringTests(unittest.TestCase):
    """The four live-update cases from the ticket's validation approach."""

    def setUp(self) -> None:
        self.items = [
            _item(1, "10mm Pistol", "weapon"),
            _item(2, "Stimpak", "drug", count=5),
            _item(3, "Rope", "misc"),
        ]
        self.rows = inventory_list.build_rows(self.items)
        self.cursor = scroll_list.resolve_cursor(
            self.rows, ListCursor("2:none:0")
        )

    def test_selection_survives_a_stack_decrement(self) -> None:
        """The case Object::id cannot express: obj_copy re-ids the stack."""
        after = [
            _item(1, "10mm Pistol", "weapon"),
            _item(2, "Stimpak", "drug", count=4),
            _item(3, "Rope", "misc"),
        ]
        rows = inventory_list.build_rows(after)
        resolved = scroll_list.resolve_cursor(rows, self.cursor)
        self.assertEqual(resolved.selected_key, "2:none:0")
        found = inventory_list.item_for_key(after, resolved.selected_key)
        assert found is not None
        self.assertEqual(found.name, "Stimpak")

    def test_selection_survives_an_unrelated_insert_before_it(self) -> None:
        """Alphabetical ordering shifts indices; the key must still win."""
        after = self.items + [_item(9, "Aspirin", "drug")]
        rows = inventory_list.build_rows(after)
        resolved = scroll_list.resolve_cursor(rows, self.cursor)
        self.assertEqual(resolved.selected_key, "2:none:0")
        # The index really did move, so this was not a trivial pass.
        self.assertNotEqual(resolved.selected_index, self.cursor.selected_index)

    def test_vanished_selection_clamps_instead_of_jumping_to_the_top(self) -> None:
        after = [_item(1, "10mm Pistol", "weapon"), _item(3, "Rope", "misc")]
        rows = inventory_list.build_rows(after)
        resolved = scroll_list.resolve_cursor(rows, self.cursor)
        self.assertNotEqual(resolved.selected_key, scroll_list.NO_SELECTION)
        self.assertIsNotNone(
            inventory_list.item_for_key(after, resolved.selected_key)
        )
        # Not the first row: it clamped near where the selection was.
        self.assertNotEqual(resolved.selected_key, "1:none:0")

    def test_equipping_moves_the_item_between_groups(self) -> None:
        before = _labels([_item(5, "Leather Armor", "armor")])
        self.assertEqual(before, ["ARMOR", "Leather Armor"])
        rows = inventory_list.build_rows(
            [_item(5, "Leather Armor", "armor", slot="worn")]
        )
        # Same group, but the row key changed with the slot, which is what
        # makes the equipped marker update live.
        self.assertEqual([r.key for r in rows if r.selectable], ["5:worn:0"])

    def test_emptying_the_inventory_yields_an_empty_cursor(self) -> None:
        resolved = scroll_list.resolve_cursor((), self.cursor)
        self.assertEqual(resolved, ListCursor())


if __name__ == "__main__":
    unittest.main()
