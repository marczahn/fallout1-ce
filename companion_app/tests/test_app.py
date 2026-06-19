"""Unit tests for app.py helpers.

Covers the pure connection-state mapping and M5 DATA navigation
routing. No pygame dependency.
"""
from __future__ import annotations

import unittest

from companion_app.app import (
    _body_text,
    _handle_tab_key,
    _handle_data_input,
    _handle_map_input,
    _route_input,
    _start_network_client,
    _visible_page,
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
from companion_app.ui.pages import Page, StartupPage
from companion_app.ui.pages.boot import BootPhase, BootSequence
from companion_app.ui.pages.data import DataPageUiState, DataTab
from companion_app.ui.pages.map import default_map_ui


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
        page, ui_state, _map_ui = _route_input(
            Page.MAP,
            DataPageUiState(
                selected_tab=DataTab.HOLODISKS,
                active_tab=DataTab.HOLODISKS,
            ),
            default_map_ui(),
            PageButtonEvent(2),
        )
        self.assertEqual(page, Page.DATA)
        self.assertEqual(ui_state, DataPageUiState())

    def test_non_map_non_data_pages_ignore_encoder_confirm_and_back(self) -> None:
        data_ui = DataPageUiState(selected_tab=DataTab.HOLODISKS)
        map_ui = default_map_ui()
        for input_event in (
            EncoderLeftEvent(),
            EncoderRightEvent(),
            ConfirmEvent(),
            BackEvent(),
        ):
            page, ui_state, out_map_ui = _route_input(
                Page.STATUS, data_ui, map_ui, input_event
            )
            self.assertEqual(page, Page.STATUS)
            self.assertEqual(ui_state, data_ui)
            self.assertEqual(out_map_ui, map_ui)


class MapInputRoutingTests(unittest.TestCase):
    def test_handle_map_input_encoder_right_advances(self) -> None:
        map_ui = _handle_map_input(default_map_ui(), EncoderRightEvent())
        self.assertEqual(map_ui.selected_key, "ATLAS")

    def test_handle_map_input_encoder_left_wraps(self) -> None:
        # LOCAL is first; encoder-left wraps endlessly to the last segment.
        map_ui = _handle_map_input(default_map_ui(), EncoderLeftEvent())
        self.assertEqual(map_ui.selected_key, "WORLD")

    def test_handle_map_input_confirm_and_back_are_noops(self) -> None:
        base = default_map_ui()
        self.assertEqual(_handle_map_input(base, ConfirmEvent()), base)
        self.assertEqual(_handle_map_input(base, BackEvent()), base)

    def test_route_input_cycles_map_and_leaves_data_untouched(self) -> None:
        data_ui = DataPageUiState(selected_tab=DataTab.HOLODISKS)
        page, out_data, out_map = _route_input(
            Page.MAP, data_ui, default_map_ui(), EncoderRightEvent()
        )
        self.assertEqual(page, Page.MAP)
        self.assertEqual(out_data, data_ui)
        self.assertEqual(out_map.selected_key, "ATLAS")

    def test_map_selection_persists_across_navigation(self) -> None:
        data_ui = DataPageUiState()
        # Cycle MAP to ATLAS, leave to STATUS, then return to MAP.
        _page, data_ui, map_ui = _route_input(
            Page.MAP, data_ui, default_map_ui(), EncoderRightEvent()
        )
        self.assertEqual(map_ui.selected_key, "ATLAS")
        page, data_ui, map_ui = _route_input(
            Page.MAP, data_ui, map_ui, PageButtonEvent(1)
        )
        self.assertEqual(page, Page.STATUS)
        page, data_ui, map_ui = _route_input(
            Page.STATUS, data_ui, map_ui, PageButtonEvent(4)
        )
        self.assertEqual(page, Page.MAP)
        self.assertEqual(map_ui.selected_key, "ATLAS")

    def test_data_still_resets_on_entry(self) -> None:
        # Pin the divergence: DATA resets while MAP persists.
        page, data_ui, _map_ui = _route_input(
            Page.STATUS,
            DataPageUiState(selected_tab=DataTab.HOLODISKS),
            default_map_ui(),
            PageButtonEvent(2),
        )
        self.assertEqual(page, Page.DATA)
        self.assertEqual(data_ui, DataPageUiState())


class VisiblePageTests(unittest.TestCase):
    def test_returns_splash_before_boot_console(self) -> None:
        sequence = BootSequence(phase=BootPhase.SPLASH)
        self.assertEqual(_visible_page(sequence, Page.STATUS), StartupPage.SPLASH)

    def test_returns_boot_during_boot_console_phases(self) -> None:
        sequence = BootSequence(phase=BootPhase.BOOTING)
        self.assertEqual(_visible_page(sequence, Page.STATUS), StartupPage.BOOT)

    def test_returns_current_main_page_after_startup(self) -> None:
        sequence = BootSequence(phase=BootPhase.COMPLETE)
        self.assertEqual(_visible_page(sequence, Page.MAP), Page.MAP)


class TabKeyHandlingTests(unittest.TestCase):
    def test_tab_skips_startup_and_starts_network_before_connect_phase(self) -> None:
        state = AppState()
        console = TypewriterConsole()
        sequence = BootSequence(phase=BootPhase.SPLASH)
        config = Config(
            server_host="127.0.0.1",
            server_port=28080,
            server_password="testpw",
        )

        net = _handle_tab_key(
            sequence,
            console,
            config=config,
            state=state,
            net=None,
        )

        self.assertIsNotNone(net)
        self.assertEqual(sequence.phase, BootPhase.COMPLETE)

    def test_tab_toggles_console_after_startup_complete(self) -> None:
        state = AppState()
        console = TypewriterConsole(visible=True)
        sequence = BootSequence(phase=BootPhase.COMPLETE)
        config = Config(
            server_host="127.0.0.1",
            server_port=28080,
            server_password="testpw",
        )

        net = _handle_tab_key(
            sequence,
            console,
            config=config,
            state=state,
            net=None,
        )

        self.assertIsNone(net)
        self.assertFalse(console.visible)


if __name__ == "__main__":
    unittest.main()
