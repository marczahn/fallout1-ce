from __future__ import annotations

import unittest

from companion_app.state import InventoryItem
from companion_app.ui import item_actions


class ItemActionsTests(unittest.TestCase):
    def test_drug_offers_only_self_use(self) -> None:
        actions = item_actions.actions_for(InventoryItem(item_type="drug"))
        self.assertEqual(
            [(a.label, a.command) for a in actions],
            [("USE", "useSelf"), ("CANCEL", "cancel")],
        )

    def test_armor_offers_equip(self) -> None:
        actions = item_actions.actions_for(InventoryItem(item_type="armor"))
        self.assertEqual(actions[0].command, "equipArmor")

    def test_one_handed_item_offers_each_hand(self) -> None:
        actions = item_actions.actions_for(InventoryItem(item_type="weapon"))
        self.assertEqual(
            [a.command for a in actions],
            ["equipLeftHand", "equipRightHand", "cancel"],
        )

    def test_two_handed_weapon_offers_both_hands_only(self) -> None:
        actions = item_actions.actions_for(InventoryItem(item_type="weapon", two_handed=True))
        self.assertEqual([a.command for a in actions], ["equipBothHands", "cancel"])

    def test_item_without_an_action_still_offers_cancel(self) -> None:
        self.assertEqual(
            item_actions.actions_for(InventoryItem(item_type="container")),
            (item_actions.Action("CANCEL", "cancel"),),
        )

    def test_modal_selection_wraps(self) -> None:
        state = item_actions.move(item_actions.ModalState(open=True), 2, -1)
        self.assertEqual(state.index, 1)


if __name__ == "__main__":
    unittest.main()
