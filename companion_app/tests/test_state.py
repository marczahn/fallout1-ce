"""Unit tests for the state cache module (M3-T1).

Covers the pure-data models: defaults, construction, field access,
and enum members. No dependency on networking or pygame.
"""
from __future__ import annotations

import unittest

from companion_app.state import AppState, ConnectionState, PlayerState, WorldInfo


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
        p = PlayerState(available=True, hp=30, max_hp=40)
        self.assertTrue(p.available)
        self.assertEqual(p.hp, 30)
        self.assertEqual(p.max_hp, 40)

    def test_world_info_construction(self) -> None:
        w = WorldInfo(schema_version=3, game="fallout1-ce", player_available=True)
        self.assertEqual(w.schema_version, 3)
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
