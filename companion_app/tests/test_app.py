"""Unit tests for app.py helpers.

Covers the pure connection-state mapping and the TASK-017 section
routing. No pygame dependency.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

from companion_app.app import (
    _active_rows,
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
from companion_app.state import (
    AppState,
    ConnectionState,
    InventoryItem,
    PlayerState,
    Quest,
    WaterStatus,
)
from companion_app.ui import quest_list, sections
from companion_app.ui.scroll_list import ListCursor
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


def _quest_route_state() -> AppState:
    """An inventory *and* two locations' worth of quests (TASK-021).

    ``_route_input`` derives the active sub-section's rows from state, so
    the QUESTS navigation tests need real quest data — with an empty list
    ``Confirm`` is inert via the empty-list guard and the drill-down path
    is never reached. Two locations, and a location with three quests, so
    a drilled level-2 list has somewhere to wrap around to.
    """
    state = _route_state()
    state.player.quests = [
        Quest(location_index=0, slot=3, location="Vault 13",
              text="Find the water chip.", water_chip=True),
        Quest(location_index=0, slot=4, location="Vault 13",
              text="Catch the water thief.", completed=True),
        Quest(location_index=3, slot=0, location="Junktown", text="Help Saul."),
        Quest(location_index=3, slot=1, location="Junktown",
              text="Kill Killian.", completed=True),
        Quest(location_index=3, slot=2, location="Junktown", text="Find the caravan."),
    ]
    state.player.water = WaterStatus(days_remaining=137, countdown_active=True)
    return state


_QUEST_ROUTE_STATE = _quest_route_state()

# A player who is connected but has no quests at all, for the empty-list
# guard: activation must refuse rather than trap the encoder.
_NO_QUEST_STATE = _route_state()


def _with_subsection(
    ui: sections.SectionsUiState,
    page: Page,
    sub_section: str,
) -> sections.SectionsUiState:
    """``ui`` with ``page``'s sub-header selection forced to ``sub_section``.

    Set directly rather than cycled to: a test that walks the encoder to
    reach a sub-section fails for two different reasons at once.
    """
    seg = sections.for_page(ui, page)
    return sections.with_page(ui, page, replace(seg, selected_key=sub_section))


def _archives_quests(
    ui: sections.SectionsUiState | None = None,
) -> sections.SectionsUiState:
    """State with ARCHIVES/QUESTS selected — which is its default."""
    base = ui if ui is not None else sections.default_sections_ui()
    return _with_subsection(base, Page.ARCHIVES, sections.ARCHIVES_QUESTS)


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
        """Narrowed from TASK-017's blanket no-op test, twice.

        TASK-018 made STATUS/INVENTORY activatable and narrowed this to
        CHARACTER, QUESTS and TRANSMISSIONS. TASK-021 makes ARCHIVES/QUESTS
        activatable too, so QUESTS is out and only **CHARACTER and
        TRANSMISSIONS** remain guaranteed inert — narrowed rather than deleted,
        because the guarantee still has to hold for the sub-sections that
        keep it.

        Each sub-section is selected explicitly here. Relying on each
        section's *default* selection is what let this test keep passing
        after QUESTS became activatable: ARCHIVES defaults to QUESTS, and
        ``Confirm`` was still inert on it only because the fixture had no
        quest data, so the empty-list guard caught it. The activation path
        for a QUESTS list that *does* have rows is covered in
        ``QuestNavigationTests``.
        """
        base = sections.default_sections_ui()
        cases = (
            (Page.STATUS, sections.STATUS_CHARACTER),
            (Page.ARCHIVES, sections.ARCHIVES_TRANSMISSIONS),
        )
        for page, sub_section in cases:
            ui = _with_subsection(base, page, sub_section)
            self.assertEqual(sections.for_page(ui, page).selected_key, sub_section)
            for input_event in (ConfirmEvent(), BackEvent()):
                with self.subTest(page=page, sub_section=sub_section):
                    out_page, out_ui = _route_input(
                        page, ui, input_event, _QUEST_ROUTE_STATE
                    )
                    self.assertEqual(out_page, page)
                    self.assertEqual(out_ui, ui)
                    self.assertFalse(out_ui.activated)
                    self.assertEqual(out_ui.quest_drill_key, "")

    def test_automaps_subsections_are_all_inert(self) -> None:
        """AUTOMAPS has no activatable sub-section at all."""
        base = sections.default_sections_ui()
        for sub_section in (
            sections.AUTOMAPS_LOCAL,
            sections.AUTOMAPS_WORLD,
            sections.AUTOMAPS_ATLAS,
        ):
            ui = _with_subsection(base, Page.AUTOMAPS, sub_section)
            for input_event in (ConfirmEvent(), BackEvent()):
                with self.subTest(sub_section=sub_section):
                    _page, out_ui = _route_input(
                        Page.AUTOMAPS, ui, input_event, _QUEST_ROUTE_STATE
                    )
                    self.assertEqual(out_ui, ui)

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
        # One encoder step from QUESTS lands on HOLODISKS: ARCHIVES has
        # three sub-sections since TASK-024's subject correction.
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

    def test_confirm_is_still_inert_on_an_activated_inventory(self) -> None:
        """Drill-down is QUESTS-only; INVENTORY keeps TASK-018's behaviour.

        ``DRILLABLE`` is an allow-list precisely so the second meaning of
        ``Confirm`` cannot leak to the other activatable sub-section.
        """
        ui = self._on_inventory()
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _QUEST_ROUTE_STATE)
        activated = ui
        _page, ui = _route_input(Page.STATUS, ui, ConfirmEvent(), _QUEST_ROUTE_STATE)
        self.assertEqual(ui, activated)
        self.assertEqual(ui.quest_drill_key, "")


class QuestNavigationTests(unittest.TestCase):
    """TASK-021: activation plus the two-level drill-down on ARCHIVES/QUESTS."""

    def _on_quests(self) -> sections.SectionsUiState:
        """ARCHIVES with QUESTS selected, not yet activated."""
        ui = _archives_quests()
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key, sections.ARCHIVES_QUESTS
        )
        self.assertFalse(ui.activated)
        return ui

    def _activated(self) -> sections.SectionsUiState:
        ui = self._on_quests()
        _page, ui = _route_input(
            Page.ARCHIVES, ui, ConfirmEvent(), _QUEST_ROUTE_STATE
        )
        self.assertTrue(ui.activated)
        return ui

    def _drilled(self) -> sections.SectionsUiState:
        ui = self._activated()
        _page, ui = _route_input(
            Page.ARCHIVES, ui, ConfirmEvent(), _QUEST_ROUTE_STATE
        )
        self.assertNotEqual(ui.quest_drill_key, "")
        return ui

    def test_quests_is_activatable(self) -> None:
        self.assertTrue(
            sections.is_activatable(Page.ARCHIVES, sections.ARCHIVES_QUESTS)
        )

    def test_confirm_activates_level_one_onto_a_location_row(self) -> None:
        ui = self._activated()
        self.assertEqual(ui.quest_drill_key, "", "activation is not drill-down")
        self.assertIsNotNone(
            quest_list.location_index_from_key(ui.quest_cursor.selected_key)
        )

    def test_activation_uses_the_quest_cursor_not_the_inventory_cursor(self) -> None:
        ui = self._activated()
        self.assertEqual(ui.inventory_cursor, ListCursor())
        self.assertNotEqual(ui.quest_cursor, ListCursor())

    def test_encoder_scrolls_level_one_between_locations(self) -> None:
        ui = self._activated()
        first = ui.quest_cursor.selected_key
        _page, ui = _route_input(
            Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
        )
        self.assertNotEqual(ui.quest_cursor.selected_key, first)
        # The sub-section itself did not move.
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key, sections.ARCHIVES_QUESTS
        )

    def test_confirm_at_level_one_drills_into_the_location_under_the_cursor(
        self,
    ) -> None:
        ui = self._activated()
        selected = ui.quest_cursor.selected_key
        _page, ui = _route_input(
            Page.ARCHIVES, ui, ConfirmEvent(), _QUEST_ROUTE_STATE
        )
        self.assertEqual(ui.quest_drill_key, selected)
        self.assertTrue(ui.activated)

    def test_level_two_rows_belong_to_the_drilled_location(self) -> None:
        ui = self._drilled()
        location_index = quest_list.location_index_from_key(ui.quest_drill_key)
        assert location_index is not None
        rows = _active_rows(Page.ARCHIVES, ui, _QUEST_ROUTE_STATE)
        self.assertTrue(rows)
        for row in rows:
            self.assertTrue(row.key.startswith(f"Q{location_index}."))

    def test_encoder_wraps_within_level_two_only(self) -> None:
        ui = self._drilled()
        rows = _active_rows(Page.ARCHIVES, ui, _QUEST_ROUTE_STATE)
        keys = [row.key for row in rows]
        seen = []
        for _step in range(len(keys) + 1):
            _page, ui = _route_input(
                Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
            )
            seen.append(ui.quest_cursor.selected_key)
        # Every visited key is a level-2 row of this location, and the walk
        # wrapped rather than escaping to level 1.
        for key in seen:
            self.assertIn(key, keys)
        self.assertEqual(len(set(seen)), len(keys))
        self.assertNotEqual(ui.quest_drill_key, "")

    def test_back_at_level_two_returns_to_level_one_same_location(self) -> None:
        """The acceptance criterion: Back leaves the location selected."""
        ui = self._drilled()
        drilled_into = ui.quest_drill_key
        # Move around inside level 2 first, so the cursor genuinely holds a
        # level-2 key that has to be replaced on the way out.
        _page, ui = _route_input(
            Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
        )
        _page, ui = _route_input(Page.ARCHIVES, ui, BackEvent(), _QUEST_ROUTE_STATE)

        self.assertEqual(ui.quest_drill_key, "", "Back goes up one level")
        self.assertTrue(ui.activated, "...and not out of the list entirely")
        self.assertEqual(ui.quest_cursor.selected_key, drilled_into)

    def test_back_at_level_one_deactivates(self) -> None:
        ui = self._activated()
        cursor = ui.quest_cursor
        _page, ui = _route_input(Page.ARCHIVES, ui, BackEvent(), _QUEST_ROUTE_STATE)
        self.assertFalse(ui.activated)
        self.assertEqual(ui.quest_drill_key, "")
        self.assertEqual(ui.quest_cursor, cursor, "the cursor survives")

    def test_two_backs_from_level_two_reach_the_subsection_row(self) -> None:
        ui = self._drilled()
        _page, ui = _route_input(Page.ARCHIVES, ui, BackEvent(), _QUEST_ROUTE_STATE)
        self.assertTrue(ui.activated)
        _page, ui = _route_input(Page.ARCHIVES, ui, BackEvent(), _QUEST_ROUTE_STATE)
        self.assertFalse(ui.activated)
        self.assertEqual(ui.quest_drill_key, "")

    def test_drilling_in_seeds_the_first_quest_of_the_location(self) -> None:
        """Entering a location starts at its top, deterministically.

        One cursor field serves both levels, so a level-1 key left in it
        would resolve against level 2 by *index* and land on an arbitrary
        quest.
        """
        ui = self._drilled()
        rows = _active_rows(Page.ARCHIVES, ui, _QUEST_ROUTE_STATE)
        # The cursor is fresh; the renderer and router both resolve it to
        # the first selectable row.
        from companion_app.ui import scroll_list

        resolved = scroll_list.resolve_cursor(rows, ui.quest_cursor)
        self.assertEqual(resolved.selected_key, rows[0].key)

    def test_section_switch_clears_activation_and_depth_but_keeps_cursors(
        self,
    ) -> None:
        """The documented rule, applied to a two-level list."""
        ui = self._drilled()
        _page, ui = _route_input(
            Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
        )
        quest_cursor = ui.quest_cursor

        page, ui = _route_input(
            Page.ARCHIVES, ui, PageButtonEvent(1), _QUEST_ROUTE_STATE
        )
        self.assertEqual(page, Page.STATUS)
        self.assertFalse(ui.activated)
        self.assertEqual(ui.quest_drill_key, "", "depth must not survive")

        page, ui = _route_input(page, ui, PageButtonEvent(3), _QUEST_ROUTE_STATE)
        self.assertEqual(page, Page.ARCHIVES)
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key, sections.ARCHIVES_QUESTS
        )
        self.assertFalse(ui.activated)
        self.assertEqual(ui.quest_drill_key, "")
        self.assertEqual(ui.quest_cursor, quest_cursor, "the cursor survives")

    def test_confirm_is_inert_with_no_quest_data(self) -> None:
        """Activating an empty list would trap the encoder."""
        ui = self._on_quests()
        _page, out = _route_input(
            Page.ARCHIVES, ui, ConfirmEvent(), _NO_QUEST_STATE
        )
        self.assertFalse(out.activated)
        self.assertEqual(out, ui)

    def test_encoder_at_the_subsection_row_still_switches_subsections(self) -> None:
        """Not activated, the encoder belongs to the sub-header as before."""
        ui = self._on_quests()
        _page, ui = _route_input(
            Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
        )
        self.assertEqual(
            sections.for_page(ui, Page.ARCHIVES).selected_key,
            sections.ARCHIVES_HOLODISKS,
        )
        self.assertFalse(ui.activated)

    def test_the_two_lists_keep_separate_cursors(self) -> None:
        """Inventory and quests must not clobber each other's position."""
        ui = self._activated()
        _page, ui = _route_input(
            Page.ARCHIVES, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE
        )
        quest_cursor = ui.quest_cursor

        page, ui = _route_input(
            Page.ARCHIVES, ui, PageButtonEvent(1), _QUEST_ROUTE_STATE
        )
        ui = _with_subsection(ui, Page.STATUS, sections.STATUS_INVENTORY)
        _page, ui = _route_input(page, ui, ConfirmEvent(), _QUEST_ROUTE_STATE)
        _page, ui = _route_input(page, ui, EncoderRightEvent(), _QUEST_ROUTE_STATE)

        self.assertNotEqual(ui.inventory_cursor, ListCursor())
        self.assertEqual(
            ui.quest_cursor, quest_cursor, "the inventory must not move the quest cursor"
        )

    def test_active_rows_switch_level_with_the_depth_key(self) -> None:
        level_one = _active_rows(
            Page.ARCHIVES, self._activated(), _QUEST_ROUTE_STATE
        )
        level_two = _active_rows(Page.ARCHIVES, self._drilled(), _QUEST_ROUTE_STATE)
        self.assertTrue(all(key.key.startswith("L") for key in level_one))
        self.assertTrue(all(key.key.startswith("Q") for key in level_two))

    def test_active_rows_falls_back_to_level_one_on_an_undecodable_key(self) -> None:
        ui = replace(self._activated(), quest_drill_key="not-a-key")
        rows = _active_rows(Page.ARCHIVES, ui, _QUEST_ROUTE_STATE)
        self.assertTrue(rows)
        self.assertTrue(all(row.key.startswith("L") for row in rows))

    def test_transmissions_with_no_disks_has_no_rows_and_cannot_be_activated(self) -> None:
        """Rewritten by TASK-024, not deleted.

        This asserted TRANSMISSIONS was inert *because it was a placeholder*.
        It is now a live sub-section, so the property it protects — you
        cannot activate into an empty list and trap the encoder — is
        re-expressed against an ARCHIVES state that reports no transmissions.
        The activation case is covered by ``TransmissionNavigationTests``.
        """
        ui = _with_subsection(
            sections.default_sections_ui(), Page.ARCHIVES, sections.ARCHIVES_TRANSMISSIONS
        )
        self.assertEqual(list(_active_rows(Page.ARCHIVES, ui, _QUEST_ROUTE_STATE)), [])
        _page, out = _route_input(
            Page.ARCHIVES, ui, ConfirmEvent(), _QUEST_ROUTE_STATE
        )
        self.assertEqual(out, ui)


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
