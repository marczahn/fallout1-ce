"""Smoke tests for DATA / INVENTORY / MAP page rendering."""
from __future__ import annotations

import unittest

import pygame

from companion_app.state import AppState, ConnectionState, PlayerState
from companion_app.ui.layout import Layout
from companion_app.ui.pages.boot import BootPage, SplashPage
from companion_app.ui.pages.data import DataPage, DataPageUiState, DataTab
from companion_app.ui.pages.inventory import InventoryPage
from companion_app.ui.pages.map import MapPage
from companion_app.ui.pages.status import StatusPage


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

    def test_map_page_renders_placeholder(self) -> None:
        MapPage().render(self.surface, self.layout.content_rect, self.state)

    def test_pages_expose_titles_locally(self) -> None:
        self.assertEqual(StatusPage().title, "STATUS")
        self.assertEqual(DataPage().title, "DATA")
        self.assertEqual(InventoryPage().title, "INVENTORY")
        self.assertEqual(MapPage().title, "MAP")
        self.assertIsNone(SplashPage().title)
        self.assertIsNone(BootPage((480, 800)).title)


if __name__ == "__main__":
    unittest.main()
