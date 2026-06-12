"""Unit tests for app.py helpers.

Covers the pure connection-state mapping and M5 DATA navigation
routing. No pygame dependency.
"""
from __future__ import annotations

import unittest

from companion_app.app import (
    _body_text,
    _connection_status,
    _handle_data_input,
    _route_input,
    _start_network_client,
)
from companion_app.config import Config
from companion_app.ui.console import TypewriterConsole
from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    PageButtonEvent,
)
from companion_app.state import AppState, ConnectionState, PlayerState
from companion_app.ui.pages import Page
from companion_app.ui.pages.data import DataPageUiState, DataTab


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
        self.assertEqual(_body_text(state), "CONNECTING…")

    def test_connecting(self) -> None:
        state = AppState(connection=ConnectionState.CONNECTING)
        self.assertEqual(_body_text(state), "CONNECTING…")

    def test_awaiting_auth(self) -> None:
        state = AppState(connection=ConnectionState.AWAITING_AUTH)
        self.assertEqual(_body_text(state), "CONNECTING…")

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
        self.assertEqual(_body_text(state), "CONNECTING…")


class StartupNetworkClientTests(unittest.TestCase):
    def test_start_network_client_logs_target_and_leaves_idle_cursor(self) -> None:
        state = AppState()
        console = TypewriterConsole()
        config = Config(
            server_host="127.0.0.1",
            server_port=28080,
            server_password="testpw",
        )

        client = _start_network_client(config, state, console)

        self.assertIsNotNone(client)
        self.assertEqual(len(console.lines), 1)
        self.assertEqual(console.lines[0].text, "UPLINK TARGET.........127.0.0.1:28080")
        self.assertTrue(console.show_idle_cursor)


class DataInputRoutingTests(unittest.TestCase):
    def test_encoder_right_moves_data_selection_to_holodisks(self) -> None:
        ui_state = _handle_data_input(DataPageUiState(), EncoderRightEvent())
        self.assertEqual(ui_state.selected_tab, DataTab.HOLODISKS)
        self.assertTrue(ui_state.at_root)

    def test_encoder_left_at_first_tab_is_noop(self) -> None:
        ui_state = _handle_data_input(DataPageUiState(), EncoderLeftEvent())
        self.assertEqual(ui_state, DataPageUiState())

    def test_confirm_enters_selected_subtab(self) -> None:
        ui_state = _handle_data_input(
            DataPageUiState(selected_tab=DataTab.HOLODISKS),
            ConfirmEvent(),
        )
        self.assertEqual(ui_state.active_tab, DataTab.HOLODISKS)

    def test_back_returns_to_data_root(self) -> None:
        ui_state = _handle_data_input(
            DataPageUiState(
                selected_tab=DataTab.HOLODISKS,
                active_tab=DataTab.HOLODISKS,
            ),
            BackEvent(),
        )
        self.assertEqual(ui_state, DataPageUiState(selected_tab=DataTab.HOLODISKS))

    def test_page_button_resets_data_to_root(self) -> None:
        page, ui_state = _route_input(
            Page.MAP,
            DataPageUiState(
                selected_tab=DataTab.HOLODISKS,
                active_tab=DataTab.HOLODISKS,
            ),
            PageButtonEvent(2),
        )
        self.assertEqual(page, Page.DATA)
        self.assertEqual(ui_state, DataPageUiState())

    def test_non_data_pages_ignore_encoder_confirm_and_back(self) -> None:
        data_ui = DataPageUiState(selected_tab=DataTab.HOLODISKS)
        for input_event in (
            EncoderLeftEvent(),
            EncoderRightEvent(),
            ConfirmEvent(),
            BackEvent(),
        ):
            page, ui_state = _route_input(Page.MAP, data_ui, input_event)
            self.assertEqual(page, Page.MAP)
            self.assertEqual(ui_state, data_ui)


if __name__ == "__main__":
    unittest.main()
