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
from companion_app.state import AppState, ConnectionState, InventoryItem, PlayerState
from companion_app.ui import sections
from companion_app.ui.pages import Page, StartupPage
from companion_app.ui.pages.boot import BootPhase, BootSequence


def _route_state() -> AppState:
    """A connected player carrying enough to make a multi-row list.

    ``_route_input`` derives the active sub-section's rows from state, so
    routing tests need an inventory whenever activation is in play. Two
    groups and three items, so wrapping and heading-skipping are both
    exercised by a single encoder step.
    """
    return AppState(
        connection=ConnectionState.READY,
        player=PlayerState(
            available=True,
            inventory=[
                InventoryItem(pid=1, name="10mm Pistol", item_type="weapon", count=1),
                InventoryItem(pid=2, name="Stimpak", item_type="drug", count=5),
                InventoryItem(pid=3, name="Leather Armor", item_type="armor", count=1),
            ],
        ),
    )


_ROUTE_STATE = _route_state()


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
            page, out_ui = _route_input(Page.STATUS, ui, PageButtonEvent(index), _ROUTE_STATE)
            self.assertEqual(page, expected)
            self.assertEqual(out_ui, ui)

    def test_button_four_is_inert(self) -> None:
        """Index 4 is the close/shutdown button, not a section.

        It must not resolve to a Page (which would raise ValueError) and
        must not disturb the current section or any selection.
        """
        ui = sections.handle_input(
            sections.default_sections_ui(), Page.AUTOMAPS, EncoderRightEvent()
        )
        page, out_ui = _route_input(Page.AUTOMAPS, ui, PageButtonEvent(4), _ROUTE_STATE)
        self.assertEqual(page, Page.AUTOMAPS)
        self.assertEqual(out_ui, ui)

    def test_encoder_cycles_the_active_section(self) -> None:
        ui = sections.default_sections_ui()
        page, ui = _route_input(Page.AUTOMAPS, ui, EncoderRightEvent(), _ROUTE_STATE)
        self.assertEqual(page, Page.AUTOMAPS)
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "WORLD")

    def test_encoder_left_wraps_to_last_subsection(self) -> None:
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.AUTOMAPS, ui, EncoderLeftEvent(), _ROUTE_STATE)
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "ATLAS")

    def test_encoder_leaves_other_sections_untouched(self) -> None:
        base = sections.default_sections_ui()
        _page, ui = _route_input(Page.AUTOMAPS, base, EncoderRightEvent(), _ROUTE_STATE)
        self.assertEqual(ui.status, base.status)
        self.assertEqual(ui.archives, base.archives)

    def test_confirm_and_back_are_inert_on_non_activatable_subsections(self) -> None:
        """Replaces TASK-017's blanket no-op test.

        Only STATUS/INVENTORY became activatable in TASK-018; CHARACTER,
        QUESTS and HOLODISKS must still swallow Confirm and Back. The
        sub-sections selected here are each section's default, none of
        which is INVENTORY.
        """
        base = sections.default_sections_ui()
        for page in (Page.STATUS, Page.AUTOMAPS, Page.ARCHIVES):
            for input_event in (ConfirmEvent(), BackEvent()):
                out_page, out_ui = _route_input(page, base, input_event, _ROUTE_STATE)
                self.assertEqual(out_page, page)
                self.assertEqual(out_ui, base)
                self.assertFalse(out_ui.activated)

    def test_selection_is_preserved_across_section_switches(self) -> None:
        """Selected sub-sections survive leaving and re-entering a section."""
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.AUTOMAPS, ui, EncoderRightEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.ARCHIVES, ui, EncoderRightEvent(), _ROUTE_STATE)

        page = Page.ARCHIVES
        for index in (1, 2, 3):
            page, ui = _route_input(page, ui, PageButtonEvent(index), _ROUTE_STATE)

        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")
        self.assertEqual(sections.for_page(ui, Page.AUTOMAPS).selected_key, "WORLD")
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key, "HOLODISKS"
        )


class SubSectionActivationTests(unittest.TestCase):
    """TASK-018: Confirm hands the encoder to a sub-section's content."""

    def _on_inventory(self) -> sections.SectionsUiState:
        """STATUS with INVENTORY selected, not yet activated."""
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")
        return ui

    def test_confirm_activates_inventory(self) -> None:
        ui = self._on_inventory()
        page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        self.assertEqual(page, Page.STATUS)
        self.assertTrue(ui.activated)
        # Seeded onto a real item row (pid:slot:occurrence), never onto a
        # group heading (which is prefixed and carries no colons).
        self.assertIn(":", ui.inventory_cursor.selected_key)
        self.assertFalse(ui.inventory_cursor.selected_key.startswith("#"))

    def test_encoder_while_activated_moves_cursor_not_subsection(self) -> None:
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        first = ui.inventory_cursor.selected_key
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        self.assertNotEqual(ui.inventory_cursor.selected_key, first)
        # The sub-section itself did not move.
        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")

    def test_back_deactivates_and_keeps_the_cursor(self) -> None:
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        moved = ui.inventory_cursor
        _page, ui = _route_input(Page.STATUS, ui, BackEvent(), _ROUTE_STATE)
        self.assertFalse(ui.activated)
        self.assertEqual(ui.inventory_cursor, moved)

    def test_confirm_after_back_resumes_the_same_row(self) -> None:
        """The deactivated list outlines a row; re-entry must honour it."""
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        resumed_on = ui.inventory_cursor.selected_key
        _page, ui = _route_input(Page.STATUS, ui, BackEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        self.assertTrue(ui.activated)
        self.assertEqual(ui.inventory_cursor.selected_key, resumed_on)

    def test_section_switch_deactivates_but_preserves_cursor(self) -> None:
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        cursor = ui.inventory_cursor

        page, ui = _route_input(Page.STATUS, ui, PageButtonEvent(2), _ROUTE_STATE)
        self.assertEqual(page, Page.AUTOMAPS)
        self.assertFalse(ui.activated)

        page, ui = _route_input(page, ui, PageButtonEvent(1), _ROUTE_STATE)
        self.assertEqual(page, Page.STATUS)
        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")
        self.assertFalse(ui.activated)
        self.assertEqual(ui.inventory_cursor, cursor)

    def test_confirm_is_inert_on_an_empty_inventory(self) -> None:
        """Activating an empty list would trap the encoder with nothing to move."""
        ui = self._on_inventory()
        empty = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=True),
        )
        _page, out = _route_input(Page.STATUS, ui, ConfirmEvent(), empty)
        self.assertFalse(out.activated)
        self.assertEqual(out, ui)

    def test_encoder_at_the_subsection_row_still_cycles(self) -> None:
        """Not activated: the encoder belongs to the sub-header as before."""
        ui = sections.default_sections_ui()
        _page, ui = _route_input(Page.STATUS, ui, EncoderRightEvent(), _ROUTE_STATE)
        self.assertEqual(sections.for_page(ui, Page.STATUS).selected_key, "INVENTORY")
        self.assertFalse(ui.activated)

    def test_confirm_is_inert_while_already_activated(self) -> None:
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        activated = ui
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _ROUTE_STATE)
        self.assertEqual(ui, activated)


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
