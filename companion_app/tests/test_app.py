"""Unit tests for app.py helpers (M3-T3).

Covers the pure mapping functions ``_connection_status`` and
``_body_text``. No pygame dependency.
"""
from __future__ import annotations

import unittest

from companion_app.app import _body_text, _connection_status
from companion_app.state import AppState, ConnectionState, PlayerState


class ConnectionStatusTests(unittest.TestCase):
    def test_disconnected(self) -> None:
        state = AppState()
        self.assertEqual(_connection_status(state), "--")

    def test_connecting(self) -> None:
        state = AppState(connection=ConnectionState.CONNECTING)
        self.assertEqual(_connection_status(state), "CONNECTING")

    def test_awaiting_auth(self) -> None:
        state = AppState(connection=ConnectionState.AWAITING_AUTH)
        self.assertEqual(_connection_status(state), "CONNECTING")

    def test_awaiting_world(self) -> None:
        state = AppState(connection=ConnectionState.AWAITING_WORLD)
        self.assertEqual(_connection_status(state), "CONNECTING")

    def test_awaiting_snapshot(self) -> None:
        state = AppState(connection=ConnectionState.AWAITING_SNAPSHOT)
        self.assertEqual(_connection_status(state), "CONNECTING")

    def test_ready_player_available(self) -> None:
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=True),
        )
        self.assertEqual(_connection_status(state), "OK")

    def test_ready_player_not_available(self) -> None:
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=False),
        )
        self.assertEqual(_connection_status(state), "NO SIGNAL")

    def test_reconnecting(self) -> None:
        state = AppState(connection=ConnectionState.RECONNECTING)
        self.assertEqual(_connection_status(state), "RECONNECTING")


class BodyTextTests(unittest.TestCase):
    def test_disconnected(self) -> None:
        state = AppState()
        self.assertEqual(_body_text(state), "CONNECTING\u2026")

    def test_connecting(self) -> None:
        state = AppState(connection=ConnectionState.CONNECTING)
        self.assertEqual(_body_text(state), "CONNECTING\u2026")

    def test_awaiting_auth(self) -> None:
        state = AppState(connection=ConnectionState.AWAITING_AUTH)
        self.assertEqual(_body_text(state), "CONNECTING\u2026")

    def test_ready_player_available_returns_empty(self) -> None:
        """When READY+available the active section draws its own body."""
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=True),
        )
        self.assertEqual(_body_text(state), "")

    def test_ready_player_not_available(self) -> None:
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=False),
        )
        self.assertEqual(_body_text(state), "NO SIGNAL")

    def test_reconnecting(self) -> None:
        state = AppState(connection=ConnectionState.RECONNECTING)
        self.assertEqual(_body_text(state), "CONNECTING\u2026")


if __name__ == "__main__":
    unittest.main()
