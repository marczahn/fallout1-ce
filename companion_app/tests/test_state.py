"""Unit tests for the state cache module (M3-T1).

Covers the pure-data models: defaults, construction, field access,
and enum members. No dependency on networking or pygame.
"""
from __future__ import annotations

import unittest

from companion_app.state import (
    AppState,
    ConnectionState,
    InventoryItem,
    PlayerState,
    PlayerSurface,
    WorldInfo,
)


class AppStateTests(unittest.TestCase):
    def test_default_connection_is_disconnected(self) -> None:
        state = AppState()
        self.assertEqual(state.connection, ConnectionState.DISCONNECTED)

    def test_default_player_is_not_available(self) -> None:
        state = AppState()
        self.assertFalse(state.player.available)

    def test_default_world_is_none(self) -> None:
        state = AppState()
        self.assertIsNone(state.world)

    def test_default_player_hp_zero(self) -> None:
        state = AppState()
        self.assertEqual(state.player.hp, 0)

    def test_default_player_max_hp_zero(self) -> None:
        state = AppState()
        self.assertEqual(state.player.max_hp, 0)

    def test_player_state_construction(self) -> None:
        p = PlayerState(
            available=True,
            hp=30,
            max_hp=40,
            surface=PlayerSurface.LOCAL,
            location="Vault 13",
            armor_class=12,
            current_carry_weight=50,
            carry_weight=125,
            melee_damage=3,
            damage_resistance=10,
            radiation=3,
            poison=1,
            level=4,
            experience=7650,
            next_level_exp=8000,
            strength=5,
            inventory=[InventoryItem(pid=40, count=2)],
        )
        self.assertTrue(p.available)
        self.assertEqual(p.hp, 30)
        self.assertEqual(p.max_hp, 40)
        self.assertEqual(p.surface, PlayerSurface.LOCAL)
        self.assertEqual(p.location, "Vault 13")
        self.assertEqual(p.armor_class, 12)
        self.assertEqual(p.current_carry_weight, 50)
        self.assertEqual(p.carry_weight, 125)
        self.assertEqual(p.melee_damage, 3)
        self.assertEqual(p.damage_resistance, 10)
        self.assertEqual(p.radiation, 3)
        self.assertEqual(p.poison, 1)
        self.assertEqual(p.level, 4)
        self.assertEqual(p.experience, 7650)
        self.assertEqual(p.next_level_exp, 8000)
        self.assertEqual(p.strength, 5)
        self.assertEqual(len(p.inventory), 1)

    def test_player_state_defaults_for_status_fields(self) -> None:
        p = PlayerState()
        self.assertEqual(p.surface, PlayerSurface.UNKNOWN)
        self.assertEqual(p.location, "")
        self.assertEqual(p.location_id, "")
        self.assertEqual(p.armor_class, 0)
        self.assertEqual(p.current_carry_weight, 0)
        self.assertEqual(p.carry_weight, 0)
        self.assertEqual(p.melee_damage, 0)
        self.assertEqual(p.damage_resistance, 0)
        self.assertEqual(p.radiation, 0)
        self.assertEqual(p.poison, 0)
        self.assertEqual(p.level, 0)
        self.assertEqual(p.experience, 0)
        self.assertEqual(p.next_level_exp, 0)
        self.assertEqual(p.luck, 0)
        self.assertEqual(p.inventory, [])

    def test_world_info_construction(self) -> None:
        w = WorldInfo(schema_version=4, game="fallout1-ce", player_available=True)
        self.assertEqual(w.schema_version, 4)
        self.assertEqual(w.game, "fallout1-ce")
        self.assertTrue(w.player_available)

    def test_world_info_defaults(self) -> None:
        w = WorldInfo()
        self.assertEqual(w.schema_version, 0)
        self.assertEqual(w.game, "")
        self.assertFalse(w.player_available)

    def test_connection_state_all_members(self) -> None:
        members = {s.name for s in ConnectionState}
        expected = {
            "DISCONNECTED", "CONNECTING", "AWAITING_AUTH",
            "AWAITING_WORLD", "AWAITING_SNAPSHOT", "READY", "RECONNECTING",
        }
        self.assertEqual(members, expected)

    def test_connection_state_values_distinct(self) -> None:
        values = [s.value for s in ConnectionState]
        self.assertEqual(len(values), len(set(values)))

if __name__ == "__main__":
    unittest.main()
