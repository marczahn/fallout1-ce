"""Smoke tests for section rendering (STATUS / AUTOMAPS / ARCHIVES)."""
from __future__ import annotations

import unittest

import pygame

from companion_app.app import _body_text, _render_section
from companion_app.render import palette
from companion_app.state import (
    AppState,
    ConnectionState,
    PlayerState,
    PlayerSurface,
    WorldMapState,
    WorldMapStatus,
)
from companion_app.ui import sections, shell
from companion_app.ui.layout import Layout
from companion_app.ui.pages import Page
from companion_app.ui.pages.archives import ArchivesSection
from companion_app.ui.pages.automaps import AutomapsSection
from companion_app.ui.pages.boot import BootPage, SplashPage
from companion_app.ui.pages.status import StatusSection
from companion_app.ui.scroll_list import ListCursor

# A deactivated focus: these renders exercise layout, not activation.
_FOCUS = sections.SubSectionFocus(activated=False, cursor=ListCursor())


class SectionRenderTests(unittest.TestCase):
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
        self.state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=True, hp=50, max_hp=100),
        )

    # ── every section x sub-section renders ────────────────────────

    def test_status_renders_character_subsection(self) -> None:
        StatusSection().render(
            self.surface, self.layout.content_rect, self.state, "CHARACTER", _FOCUS
        )

    def test_status_renders_inventory_subsection(self) -> None:
        StatusSection().render(
            self.surface, self.layout.content_rect, self.state, "INVENTORY", _FOCUS
        )

    def test_archives_renders_quests_subsection(self) -> None:
        ArchivesSection().render(
            self.surface, self.layout.content_rect, self.state, "QUESTS", _FOCUS
        )

    def test_archives_renders_holodisks_subsection(self) -> None:
        ArchivesSection().render(
            self.surface, self.layout.content_rect, self.state, "HOLODISKS", _FOCUS
        )

    def test_automaps_renders_local_subsection(self) -> None:
        AutomapsSection().render(
            self.surface, self.layout.content_rect, self.state, "LOCAL", _FOCUS
        )

    def test_automaps_renders_world_subsection(self) -> None:
        AutomapsSection().render(
            self.surface, self.layout.content_rect, self.state, "WORLD", _FOCUS
        )

    def test_automaps_renders_atlas_subsection(self) -> None:
        AutomapsSection().render(
            self.surface, self.layout.content_rect, self.state, "ATLAS", _FOCUS
        )

    # ── map states (unchanged behavior, new call shape) ────────────

    def _ready_world_map(self, w: int = 16, h: int = 16) -> WorldMapState:
        return WorldMapState(
            status=WorldMapStatus.READY,
            width=w,
            height=h,
            palette=bytes(b for i in range(256) for b in (i, i, i)),
            pixels=bytes((i * 7) % 256 for i in range(w * h)),
        )

    def _render_automaps(self, key: str) -> None:
        AutomapsSection().render(
            self.surface, self.layout.content_rect, self.state, key, _FOCUS
        )

    def test_map_atlas_renders_ready_map_with_live_marker(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.WORLD
        self.state.player.world_x = 8
        self.state.player.world_y = 8
        self._render_automaps("ATLAS")

    def test_map_world_renders_ready_map_with_live_marker(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.WORLD
        self.state.player.world_x = 2
        self.state.player.world_y = 14
        self._render_automaps("WORLD")

    def test_map_atlas_local_fallback_last_known(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.LOCAL
        self.state.has_world_fix = True
        self.state.last_known_world_x = 4
        self.state.last_known_world_y = 4
        self._render_automaps("ATLAS")

    def test_map_world_local_fallback_no_fix(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.LOCAL
        self.state.has_world_fix = False
        self._render_automaps("WORLD")

    def test_map_atlas_unavailable_message(self) -> None:
        self.state.world_map = WorldMapState(status=WorldMapStatus.UNAVAILABLE)
        self._render_automaps("ATLAS")

    def test_map_world_loading_message(self) -> None:
        self.state.world_map = WorldMapState(status=WorldMapStatus.FETCHING)
        self._render_automaps("WORLD")

    def test_sections_expose_titles_locally(self) -> None:
        self.assertEqual(StatusSection().title, "STATUS")
        self.assertEqual(AutomapsSection().title, "AUTOMAPS")
        self.assertEqual(ArchivesSection().title, "ARCHIVES")
        self.assertIsNone(SplashPage().title)
        self.assertIsNone(BootPage((480, 800)).title)


class DisconnectedRenderTests(unittest.TestCase):
    """The sub-header must not appear on the CONNECTING… / NO SIGNAL screen.

    Before TASK-017 the sub-header was drawn by the page renderer, which
    the frame loop skips while ``_body_text`` is non-empty, so it never
    showed there. Hoisting it into the frame loop could have changed that
    silently; this pins the behavior.
    """

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
        self.renderers = {
            Page.STATUS: StatusSection(),
            Page.AUTOMAPS: AutomapsSection(),
            Page.ARCHIVES: ArchivesSection(),
        }
        self.ui = sections.default_sections_ui()

    def _subheader_has_ink(self) -> bool:
        """Any foreground pixel inside the sub-header band."""
        content_rect = self.layout.content_rect
        band_top = content_rect.top
        band_bottom = content_rect.top + shell.SUBHEADER_BAND_HEIGHT
        for y in range(band_top, band_bottom):
            for x in range(content_rect.left, content_rect.right):
                if tuple(self.surface.get_at((x, y)))[:3] == palette.FOREGROUND:
                    return True
        return False

    def test_disconnected_draws_no_subheader_on_any_section(self) -> None:
        state = AppState()
        self.assertEqual(_body_text(state), "CONNECTING…")
        for page in (Page.STATUS, Page.AUTOMAPS, Page.ARCHIVES):
            with self.subTest(page=page):
                self.surface.fill(palette.BACKGROUND)
                _render_section(
                    self.surface,
                    self.layout,
                    page,
                    self.ui,
                    state,
                    _body_text(state),
                    self.renderers,
                )
                self.assertFalse(self._subheader_has_ink())

    def test_player_unavailable_draws_no_subheader(self) -> None:
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=False),
        )
        self.assertEqual(_body_text(state), "NO SIGNAL")
        self.surface.fill(palette.BACKGROUND)
        _render_section(
            self.surface,
            self.layout,
            Page.AUTOMAPS,
            self.ui,
            state,
            _body_text(state),
            self.renderers,
        )
        self.assertFalse(self._subheader_has_ink())

    def test_connected_does_draw_the_subheader(self) -> None:
        """Sanity check: the band-scan can actually see the sub-header."""
        state = AppState(
            connection=ConnectionState.READY,
            player=PlayerState(available=True),
        )
        for page in (Page.STATUS, Page.AUTOMAPS, Page.ARCHIVES):
            with self.subTest(page=page):
                self.surface.fill(palette.BACKGROUND)
                _render_section(
                    self.surface,
                    self.layout,
                    page,
                    self.ui,
                    state,
                    _body_text(state),
                    self.renderers,
                )
                self.assertTrue(self._subheader_has_ink())


if __name__ == "__main__":
    unittest.main()
