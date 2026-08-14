"""Unit and smoke tests for the STATUS section."""
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
from companion_app.ui import shell
from companion_app.ui.layout import Layout
from companion_app.ui.pages import status as status_page_module
from companion_app.ui.pages.status import (
    StatusSection,
    character_content_bottom,
    synthesize_state_label,
    synthesize_status_fx_label,
    synthesize_stim_counts,
)


class StatusSectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()
        pygame.font.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def setUp(self) -> None:
        self.surface = pygame.Surface((480, 800))
        self.layout = Layout((480, 800))
        self.page = StatusSection()

    def _make_state(self, **player_overrides: object) -> AppState:
        player = PlayerState(
            available=True,
            hp=43,
            max_hp=43,
            armor_class=7,
            current_carry_weight=132,
            carry_weight=200,
            melee_damage=2,
            damage_resistance=10,
            level=4,
            experience=7650,
            next_level_exp=8000,
            strength=10,
            perception=4,
            endurance=9,
            charisma=4,
            intelligence=4,
            agility=7,
            luck=4,
            inventory=[
                InventoryItem(pid=40, count=9),
                InventoryItem(pid=144, count=9),
            ],
        )
        for field, value in player_overrides.items():
            setattr(player, field, value)
        return AppState(connection=ConnectionState.READY, player=player)

    def test_state_synthesis_critical_priority(self) -> None:
        player = PlayerState(hp=15, max_hp=60, radiation=50, poison=10)
        self.assertEqual(synthesize_state_label(player), "CRITICAL")

    def test_state_synthesis_injured_priority(self) -> None:
        player = PlayerState(hp=30, max_hp=60, radiation=50)
        self.assertEqual(synthesize_state_label(player), "INJURED")

    def test_state_synthesis_irradiated_without_hp_alert(self) -> None:
        player = PlayerState(hp=55, max_hp=60, radiation=1, poison=4)
        self.assertEqual(synthesize_state_label(player), "IRRADIATED")

    def test_state_synthesis_poisoned_without_more_urgent_state(self) -> None:
        player = PlayerState(hp=55, max_hp=60, radiation=0, poison=4)
        self.assertEqual(synthesize_state_label(player), "POISONED")

    def test_state_synthesis_zero_max_hp_avoids_division(self) -> None:
        player = PlayerState(hp=10, max_hp=0, radiation=0, poison=0)
        self.assertEqual(synthesize_state_label(player), "STABLE")

    def test_stim_counts_sum_regular_and_super_stimpaks(self) -> None:
        player = PlayerState(
            inventory=[
                InventoryItem(pid=40, count=9),
                InventoryItem(pid=144, count=2),
                InventoryItem(pid=12, count=99),
            ]
        )
        self.assertEqual(synthesize_stim_counts(player), (9, 2))

    def test_status_fx_label_is_none(self) -> None:
        self.assertEqual(synthesize_status_fx_label(PlayerState()), "NONE")

    def test_render_draws_full_draft_layout(self) -> None:
        # Since TASK-017 the section renders into the shared content rect,
        # beneath the segmented sub-header — not the full screen.
        self.page.render(
            self.surface,
            self.layout.content_rect,
            self._make_state(radiation=4, poison=2),
            "CHARACTER",
        )

    def test_render_handles_empty_inventory(self) -> None:
        self.page.render(
            self.surface,
            self.layout.content_rect,
            self._make_state(inventory=[]),
            "CHARACTER",
        )

    def test_render_handles_irradiated_state_without_column_overlap(self) -> None:
        # Worst-case left value ("IRRADIATED", 10 chars) must not crash or run
        # off-surface alongside the right column.
        self.page.render(
            self.surface,
            self.layout.content_rect,
            self._make_state(hp=43, max_hp=43, radiation=12),
            "CHARACTER",
        )

    def test_character_content_fits_inside_the_content_rect(self) -> None:
        """Guard the TASK-017 vertical budget.

        pygame clips at the surface edge without error, so an overflowing
        block simply disappears — there is nothing in the rendered output
        to scan for. The bound has to be checked arithmetically.
        """
        content_rect = self.layout.content_rect
        self.assertLessEqual(
            character_content_bottom(content_rect),
            content_rect.bottom - 20,
        )

    def test_character_content_clears_the_subheader_band(self) -> None:
        self.assertGreaterEqual(
            status_page_module._BOX_TOP,
            shell.SUBHEADER_BAND_HEIGHT,
        )

    def test_special_header_rule_uses_same_phosphor_color_as_text(self) -> None:
        content_rect = self.layout.content_rect
        self.page.render(
            self.surface,
            content_rect,
            self._make_state(),
            "CHARACTER",
        )
        rule_y = (
            content_rect.top
            + status_page_module._SPECIAL_TITLE_Y
            + status_page_module._SECTION_RULE_Y_OFFSET
        )
        # x is past the section title text, within the trailing rule span.
        px = tuple(self.surface.get_at((400, rule_y)))[:3]
        self.assertEqual(px, palette.FOREGROUND)


if __name__ == "__main__":
    unittest.main()
