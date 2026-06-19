"""Smoke tests for DATA / INVENTORY / MAP page rendering."""
from __future__ import annotations

import unittest

import pygame

from companion_app.state import (
    AppState,
    ConnectionState,
    PlayerState,
    PlayerSurface,
    WorldMapState,
    WorldMapStatus,
)
from companion_app.ui.layout import Layout
from companion_app.ui.pages.boot import BootPage, SplashPage
from companion_app.ui.pages.data import DataPage, DataPageUiState, DataTab
from companion_app.ui.pages.inventory import InventoryPage
from companion_app.ui.pages.map import MapPage, default_map_ui
from companion_app.ui.pages.status import StatusPage
from companion_app.ui.segmented_header import cycle_next


class PlaceholderPageTests(unittest.TestCase):
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

    def test_data_page_renders_root_view(self) -> None:
        DataPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            DataPageUiState(),
        )

    def test_data_page_renders_quests_placeholder_body(self) -> None:
        DataPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            DataPageUiState(selected_tab=DataTab.QUESTS, active_tab=DataTab.QUESTS),
        )

    def test_data_page_renders_holodisks_placeholder_body(self) -> None:
        DataPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            DataPageUiState(
                selected_tab=DataTab.HOLODISKS,
                active_tab=DataTab.HOLODISKS,
            ),
        )

    def test_inventory_page_renders_placeholder(self) -> None:
        InventoryPage().render(self.surface, self.layout.content_rect, self.state)

    def test_map_page_renders_local_segment(self) -> None:
        local_ui = default_map_ui()
        self.assertEqual(local_ui.selected_key, "LOCAL")
        MapPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            local_ui,
        )

    def test_map_page_renders_atlas_segment(self) -> None:
        atlas_ui = cycle_next(default_map_ui())
        self.assertEqual(atlas_ui.selected_key, "ATLAS")
        MapPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            atlas_ui,
        )

    def test_map_page_renders_world_segment(self) -> None:
        world_ui = cycle_next(cycle_next(default_map_ui()))
        self.assertEqual(world_ui.selected_key, "WORLD")
        MapPage().render(
            self.surface,
            self.layout.content_rect,
            self.state,
            world_ui,
        )

    def _ready_world_map(self, w: int = 16, h: int = 16) -> WorldMapState:
        return WorldMapState(
            status=WorldMapStatus.READY,
            width=w,
            height=h,
            palette=bytes(b for i in range(256) for b in (i, i, i)),
            pixels=bytes((i * 7) % 256 for i in range(w * h)),
        )

    def _atlas_ui(self):
        return cycle_next(default_map_ui())

    def _world_ui(self):
        return cycle_next(cycle_next(default_map_ui()))

    def test_map_atlas_renders_ready_map_with_live_marker(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.WORLD
        self.state.player.world_x = 8
        self.state.player.world_y = 8
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._atlas_ui())

    def test_map_world_renders_ready_map_with_live_marker(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.WORLD
        self.state.player.world_x = 2
        self.state.player.world_y = 14
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._world_ui())

    def test_map_atlas_local_fallback_last_known(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.LOCAL
        self.state.has_world_fix = True
        self.state.last_known_world_x = 4
        self.state.last_known_world_y = 4
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._atlas_ui())

    def test_map_world_local_fallback_no_fix(self) -> None:
        self.state.world_map = self._ready_world_map()
        self.state.player.surface = PlayerSurface.LOCAL
        self.state.has_world_fix = False
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._world_ui())

    def test_map_atlas_unavailable_message(self) -> None:
        self.state.world_map = WorldMapState(status=WorldMapStatus.UNAVAILABLE)
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._atlas_ui())

    def test_map_world_loading_message(self) -> None:
        self.state.world_map = WorldMapState(status=WorldMapStatus.FETCHING)
        MapPage().render(self.surface, self.layout.content_rect, self.state, self._world_ui())

    def test_pages_expose_titles_locally(self) -> None:
        self.assertEqual(StatusPage().title, "STATUS")
        self.assertEqual(DataPage().title, "DATA")
        self.assertEqual(InventoryPage().title, "INVENTORY")
        self.assertEqual(MapPage().title, "MAP")
        self.assertIsNone(SplashPage().title)
        self.assertIsNone(BootPage((480, 800)).title)


if __name__ == "__main__":
    unittest.main()
