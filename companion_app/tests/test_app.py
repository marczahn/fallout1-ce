"""Unit tests for app.py helpers.

Covers the pure connection-state mapping and the TASK-017 section
routing. No pygame dependency.
"""
from __future__ import annotations

import unittest

from companion_app.app import (
    _body_text,
    _handle_tab_key,
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
from companion_app.ui import sections
from companion_app.ui.pages import Page, StartupPage
from companion_app.ui.pages.boot import BootPhase, BootSequence


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


class SectionRoutingTests(unittest.TestCase):
    """TASK-017: one navigation model shared by all three sections."""

    def test_section_buttons_select_their_section(self) -> None:
        ui = sections.default_sections_ui()
        for index, expected in (
            (1, Page.STATUS),
            (2, Page.AUTOMAPS),
            (3, Page.ARCHIVES),
        ):
            page, out_ui = _route_input(Page.STATUS, ui, PageButtonEvent(index))
            self.assertEqual(page, expected)
            self.assertEqual(out_ui, ui)

    def test_button_four_is_inert(self) -> None:
        """Index 4 is the close/shutdown button, not a section.

        It must not resolve to a Page (which would raise ValueError) and
        must not disturb the current section or any selection.
        """
        ui = sections.handle_encoder(
            sections.default_sections_ui(), Page.AUTOMAPS, EncoderRightEvent()
        )
        page, out_ui = _route_input(Page.AUTOMAPS, ui, PageButtonEvent(4))
        self.assertEqual(page, Page.AUTOMAPS)
        self.assertEqual(out_ui, ui)

    def test_encoder_cycles_the_active_section(self) -> None:
        ui = sections.default_sections_ui()
        page, ui = _route_input(Page.AUTOMAPS, ui, EncoderRightEvent())
        self.assertEqual(page, Page.AUTOMAPS)
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "WORLD")

    def test_encoder_left_wraps_to_last_subsection(self) -> None:
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.AUTOMAPS, ui, EncoderLeftEvent())
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "ATLAS")

    def test_encoder_leaves_other_sections_untouched(self) -> None:
        base = sections.default_sections_ui()
        _page, ui = _route_input(Page.AUTOMAPS, base, EncoderRightEvent())
        self.assertEqual(ui.status, base.status)
        self.assertEqual(ui.archives, base.archives)

    def test_confirm_and_back_are_noops_on_every_section(self) -> None:
        """Nothing is activatable yet — that is TASK-018."""
        base = sections.default_sections_ui()
        for page in (Page.STATUS, Page.AUTOMAPS, Page.ARCHIVES):
            for input_event in (ConfirmEvent(), BackEvent()):
                out_page, out_ui = _route_input(page, base, input_event)
                self.assertEqual(out_page, page)
                self.assertEqual(out_ui, base)

    def test_selection_is_preserved_across_section_switches(self) -> None:
        """Selected sub-sections survive leaving and re-entering a section."""
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent())
        _page, ui = _route_input(Page.AUTOMAPS, ui, EncoderRightEvent())
        _page, ui = _route_input(Page.ARCHIVES, ui, EncoderRightEvent())

        page = Page.ARCHIVES
        for index in (1, 2, 3):
            page, ui = _route_input(page, ui, PageButtonEvent(index))

        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "WORLD")
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key, "HOLODISKS"
        )


class VisiblePageTests(unittest.TestCase):
    def test_returns_splash_before_boot_console(self) -> None:
        sequence = BootSequence(phase=BootPhase.SPLASH)
        self.assertEqual(_visible_page(sequence, Page.STATUS), StartupPage.SPLASH)

    def test_returns_boot_during_boot_console_phases(self) -> None:
        sequence = BootSequence(phase=BootPhase.BOOTING)
        self.assertEqual(_visible_page(sequence, Page.STATUS), StartupPage.BOOT)

    def test_returns_current_main_page_after_startup(self) -> None:
        sequence = BootSequence(phase=BootPhase.COMPLETE)
        self.assertEqual(_visible_page(sequence, Page.AUTOMAPS), Page.AUTOMAPS)


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
