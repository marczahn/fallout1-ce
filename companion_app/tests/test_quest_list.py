"""ARCHIVES/QUESTS projection tests (TASK-021).

This file carries the weight the engine side cannot: there is no C++ test
target in the repo, so the quest rules live in ``ui/quest_list`` and are
pinned here. Table-driven wherever the plan named a table.
"""
from __future__ import annotations

import unittest

from companion_app.state import PlayerState, Quest, WaterStatus
from companion_app.ui import quest_list


def quest(
    location_index: int,
    slot: int,
    *,
    location: str = "",
    text: str = "",
    completed: bool = False,
    water_chip: bool = False,
) -> Quest:
    return Quest(
        location_index=location_index,
        slot=slot,
        location=location,
        text=text,
        completed=completed,
        water_chip=water_chip,
    )


# The Vault 13 block as the engine reports it: the water chip sits in slot
# 3 and is always listed, the water thief in slot 4.
VAULT13 = (
    quest(0, 3, location="Vault 13", text="Find the water chip.", water_chip=True),
    quest(0, 4, location="Vault 13", text="Catch the water thief."),
)
JUNKTOWN = (
    quest(3, 0, location="Junktown", text="Help Saul."),
    quest(3, 1, location="Junktown", text="Kill Killian.", completed=True),
    quest(3, 6, location="Junktown", text="Find the missing caravan."),
)


class RowKeyTests(unittest.TestCase):
    def test_location_key_round_trips_for_every_location_index(self) -> None:
        # 12 is the engine's QUEST_LOCATION_COUNT; the range is deliberately
        # wider so the parser is not tuned to that constant.
        for index in range(0, 40):
            key = quest_list.location_row_key(index)
            self.assertEqual(quest_list.location_index_from_key(key), index)

    def test_quest_key_encodes_location_and_slot(self) -> None:
        self.assertEqual(quest_list.quest_row_key(3, 6), "Q3.6")

    def test_quest_keys_are_unique_per_coordinate(self) -> None:
        keys = {
            quest_list.quest_row_key(loc, slot)
            for loc in range(12)
            for slot in range(9)
        }
        self.assertEqual(len(keys), 12 * 9)

    def test_location_index_from_key_rejects_non_location_keys(self) -> None:
        for key in ("", "Q3.6", "L", "Lx", "3", "#HEADING", "L3.6", "L-1"):
            with self.subTest(key=key):
                self.assertIsNone(quest_list.location_index_from_key(key))

    def test_quest_and_location_key_spaces_are_disjoint(self) -> None:
        location_keys = {quest_list.location_row_key(i) for i in range(12)}
        quest_keys = {
            quest_list.quest_row_key(i, s) for i in range(12) for s in range(9)
        }
        self.assertEqual(location_keys & quest_keys, set())


class LocationRowTests(unittest.TestCase):
    def test_empty_input_produces_no_rows(self) -> None:
        self.assertEqual(quest_list.build_location_rows(()), ())
        self.assertEqual(quest_list.location_indexes(()), ())

    def test_one_row_per_location_ascending(self) -> None:
        rows = quest_list.build_location_rows(JUNKTOWN + VAULT13)
        self.assertEqual([row.key for row in rows], ["L0", "L3"])

    def test_every_level_one_row_is_selectable(self) -> None:
        rows = quest_list.build_location_rows(VAULT13 + JUNKTOWN)
        self.assertTrue(all(row.selectable for row in rows))

    def test_row_label_carries_engine_name_and_progress(self) -> None:
        rows = quest_list.build_location_rows(JUNKTOWN)
        self.assertEqual(rows[0].label, "Junktown 1/3")

    def test_counts_split_active_and_completed(self) -> None:
        self.assertEqual(quest_list.location_counts(JUNKTOWN, 3), (2, 1, 3))
        self.assertEqual(quest_list.location_counts(VAULT13, 0), (2, 0, 2))

    def test_a_location_the_server_never_reports_has_no_row(self) -> None:
        # The four all-zero engine locations reach the app as *absent*, not
        # as empty groups, so they can never produce a row or be drilled
        # into. Location 1 (Buried Vault) is one of them.
        rows = quest_list.build_location_rows(VAULT13 + JUNKTOWN)
        self.assertNotIn("L1", [row.key for row in rows])
        self.assertEqual(quest_list.build_quest_rows(VAULT13 + JUNKTOWN, 1), ())

    def test_location_label_falls_back_to_key_when_name_is_empty(self) -> None:
        unnamed = (quest(5, 2, location="", text="Something."),)
        self.assertEqual(quest_list.location_label(unnamed, 5), "L5")


class QuestRowTests(unittest.TestCase):
    def test_rows_are_in_slot_order(self) -> None:
        shuffled = (JUNKTOWN[2], JUNKTOWN[0], JUNKTOWN[1])
        rows = quest_list.build_quest_rows(shuffled, 3)
        self.assertEqual([row.key for row in rows], ["Q3.0", "Q3.1", "Q3.6"])

    def test_a_location_whose_only_quest_sits_in_slot_six(self) -> None:
        late = (quest(7, 6, location="Boneyard", text="Late slot."),)
        rows = quest_list.build_quest_rows(late, 7)
        self.assertEqual([row.key for row in rows], ["Q7.6"])
        self.assertEqual(rows[0].label, "Late slot.")

    def test_rows_only_cover_the_requested_location(self) -> None:
        rows = quest_list.build_quest_rows(VAULT13 + JUNKTOWN, 0)
        self.assertEqual([row.key for row in rows], ["Q0.3", "Q0.4"])

    def test_unresolved_text_renders_a_visible_placeholder(self) -> None:
        # The server emits the row with empty text rather than dropping it,
        # so the list cannot silently disagree with the in-game screen.
        broken = (quest(5, 2, location="Necropolis", text=""),)
        rows = quest_list.build_quest_rows(broken, 5)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].label, quest_list.NO_TEXT_LABEL)

    def test_quest_for_key_round_trips(self) -> None:
        found = quest_list.quest_for_key(VAULT13 + JUNKTOWN, "Q3.1")
        self.assertIsNotNone(found)
        assert found is not None
        self.assertEqual(found.text, "Kill Killian.")
        self.assertTrue(found.completed)

    def test_quest_for_key_returns_none_for_a_stale_key(self) -> None:
        self.assertIsNone(quest_list.quest_for_key(VAULT13, "Q9.9"))
        self.assertIsNone(quest_list.quest_for_key(VAULT13, "L0"))
        self.assertIsNone(quest_list.quest_for_key(VAULT13, ""))


class WaterRowKeyTests(unittest.TestCase):
    def test_finds_the_row_the_server_flagged(self) -> None:
        self.assertEqual(quest_list.water_row_key(VAULT13 + JUNKTOWN), "Q0.3")

    def test_empty_when_no_row_is_flagged(self) -> None:
        self.assertEqual(quest_list.water_row_key(JUNKTOWN), "")
        self.assertEqual(quest_list.water_row_key(()), "")

    def test_the_key_matches_a_real_level_two_row(self) -> None:
        key = quest_list.water_row_key(VAULT13)
        rows = quest_list.build_quest_rows(VAULT13, 0)
        self.assertIn(key, [row.key for row in rows])


def player_with_water(days: int, active: bool) -> PlayerState:
    return PlayerState(water=WaterStatus(days_remaining=days, countdown_active=active))


class WaterStateTests(unittest.TestCase):
    def test_the_countdown_table(self) -> None:
        # (days_remaining, countdown_active) -> label, running
        cases = (
            (150, True, "WATER: 150 DAYS", True),
            (100, True, "WATER: 100 DAYS", True),
            (50, True, "WATER: 50 DAYS", True),
            (1, True, "WATER: 1 DAYS", True),
            (0, True, quest_list.WATER_DEPLETED, False),
            (0, False, quest_list.WATER_SECURED, False),
            (42, False, quest_list.WATER_SECURED, False),
            (150, False, quest_list.WATER_SECURED, False),
        )
        for days, active, label, running in cases:
            with self.subTest(days=days, active=active):
                display = quest_list.water_state(player_with_water(days, active))
                self.assertEqual(display.label, label)
                self.assertEqual(display.running, running)

    def test_secured_never_shows_a_day_number(self) -> None:
        # Chip delivered with 42 days left on the clock: the number must
        # not survive, or a dead deadline reads as a live one.
        display = quest_list.water_state(player_with_water(42, False))
        self.assertEqual(display.label, quest_list.WATER_SECURED)
        self.assertNotIn("42", display.label)
        self.assertFalse(any(ch.isdigit() for ch in display.label))

    def test_depleted_is_not_rendered_as_zero_days(self) -> None:
        # "0 DAYS" would read as "you still have today" when the engine has
        # already reached its losing state.
        display = quest_list.water_state(player_with_water(0, True))
        self.assertEqual(display.label, quest_list.WATER_DEPLETED)
        self.assertNotIn("0", display.label)

    def test_a_never_connected_app_reads_secured_not_depleted(self) -> None:
        # A default PlayerState has countdown_active False, so the label is
        # a terminal word rather than a fabricated deadline.
        display = quest_list.water_state(PlayerState())
        self.assertEqual(display.label, quest_list.WATER_SECURED)

    def test_divergent_state_keeps_both_signals_and_does_not_merge_them(self) -> None:
        """The engine's water-chip variable above 2.

        ``PipStatus`` treats any value > 1 as completed, while the
        countdown's own guard is ``!= 2``, so at 3+ the quest is finished
        *and* the water is still draining. The server sends both flags and
        this projection must keep them independent: struck-through row,
        running label. If anyone later "simplifies" the two flags into one,
        this test is what fails.
        """
        divergent_quest = quest(
            0, 3, location="Vault 13", text="Find the water chip.",
            completed=True, water_chip=True,
        )
        player = PlayerState(
            quests=[divergent_quest],
            water=WaterStatus(days_remaining=90, countdown_active=True),
        )

        display = quest_list.water_state(player)
        self.assertEqual(display.label, "WATER: 90 DAYS")
        self.assertTrue(display.running)
        # ...while the same row is simultaneously completed.
        self.assertTrue(player.quests[0].completed)

    def test_water_chip_at_each_engine_value(self) -> None:
        """The water-chip quest across the values the engine can hold.

        Value 0 and 1: listed and active (the engine forces the row
        visible). Value 2: completed, countdown stopped. Value 3: completed
        *and* countdown running -- the divergence.
        """
        cases = (
            (0, False, True),  # not started -> active, countdown running
            (1, False, True),  # in progress -> active, countdown running
            (2, True, False),  # delivered   -> completed, countdown stopped
            (3, True, True),  # divergent   -> completed, countdown running
        )
        for value, completed, countdown_active in cases:
            with self.subTest(gvar=value):
                row = quest(
                    0, 3, location="Vault 13", text="Find the water chip.",
                    completed=completed, water_chip=True,
                )
                player = PlayerState(
                    quests=[row],
                    water=WaterStatus(
                        days_remaining=100, countdown_active=countdown_active
                    ),
                )
                # The row is always present, whatever the value.
                rows = quest_list.build_quest_rows(player.quests, 0)
                self.assertEqual(len(rows), 1)
                self.assertEqual(quest_list.water_row_key(player.quests), "Q0.3")
                # And the two flags stay independent.
                self.assertEqual(player.quests[0].completed, completed)
                self.assertEqual(
                    quest_list.water_state(player).running, countdown_active
                )


class OrderingAcrossLocationsTests(unittest.TestCase):
    def test_engine_order_survives_an_arbitrary_input_order(self) -> None:
        scrambled = (JUNKTOWN[1], VAULT13[1], JUNKTOWN[2], VAULT13[0], JUNKTOWN[0])
        self.assertEqual(quest_list.location_indexes(scrambled), (0, 3))
        self.assertEqual(
            [row.key for row in quest_list.build_quest_rows(scrambled, 3)],
            ["Q3.0", "Q3.1", "Q3.6"],
        )

    def test_a_location_index_above_the_engine_table_still_projects(self) -> None:
        # Nothing here assumes the 12-row table; a modded server reporting
        # location 20 gets a row rather than an exception.
        modded = (quest(20, 0, location="Modded", text="Do a thing."),)
        rows = quest_list.build_location_rows(modded)
        self.assertEqual([row.key for row in rows], ["L20"])
        self.assertEqual(quest_list.location_index_from_key("L20"), 20)


if __name__ == "__main__":
    unittest.main()
