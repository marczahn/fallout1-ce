"""DATA page with M5 placeholder sub-tab navigation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState


class DataTab(Enum):
    QUESTS = "QUESTS"
    HOLODISKS = "HOLODISKS"


@dataclass(frozen=True)
class DataPageUiState:
    selected_tab: DataTab = DataTab.QUESTS
    active_tab: DataTab | None = None

    @property
    def at_root(self) -> bool:
        return self.active_tab is None


_TAB_TOP = 88
_TAB_GAP = 184
_TAB_LINE_Y = 126
_DETAIL_TITLE_TOP = 210
_DETAIL_BODY_TOP = 282
_TAB_SIZE = 24
_DETAIL_TITLE_SIZE = 26
_DETAIL_BODY_SIZE = 22


def move_selection_left(ui_state: DataPageUiState) -> DataPageUiState:
    if not ui_state.at_root or ui_state.selected_tab is DataTab.QUESTS:
        return ui_state
    return DataPageUiState(selected_tab=DataTab.QUESTS)


def move_selection_right(ui_state: DataPageUiState) -> DataPageUiState:
    if not ui_state.at_root or ui_state.selected_tab is DataTab.HOLODISKS:
        return ui_state
    return DataPageUiState(selected_tab=DataTab.HOLODISKS)


def enter_selected_tab(ui_state: DataPageUiState) -> DataPageUiState:
    if not ui_state.at_root:
        return ui_state
    return DataPageUiState(
        selected_tab=ui_state.selected_tab,
        active_tab=ui_state.selected_tab,
    )


def return_to_root(ui_state: DataPageUiState) -> DataPageUiState:
    if ui_state.at_root:
        return ui_state
    return DataPageUiState(selected_tab=ui_state.active_tab)


class DataPage:
    """DATA page with root sub-tab selection and placeholder bodies."""

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        ui_state: DataPageUiState,
    ) -> None:
        _ = state
        if ui_state.at_root:
            self._render_root(surface, content_rect, ui_state)
            return
        self._render_detail(surface, content_rect, ui_state.active_tab)

    def _render_root(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        ui_state: DataPageUiState,
    ) -> None:
        quests_pos = (content_rect.left + 44, content_rect.top + _TAB_TOP)
        holodisks_pos = (content_rect.left + 44 + _TAB_GAP, content_rect.top + _TAB_TOP)

        self._draw_tab_label(
            surface,
            "QUESTS",
            quests_pos,
            selected=ui_state.selected_tab is DataTab.QUESTS,
        )
        self._draw_tab_label(
            surface,
            "HOLODISKS",
            holodisks_pos,
            selected=ui_state.selected_tab is DataTab.HOLODISKS,
        )
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (content_rect.left + 36, content_rect.top + _TAB_LINE_Y),
            (content_rect.right - 36, content_rect.top + _TAB_LINE_Y),
            1,
        )

    def _render_detail(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        tab: DataTab | None,
    ) -> None:
        if tab is None:
            return

        title_rect = content_rect.copy()
        title_rect.top += _DETAIL_TITLE_TOP
        title_rect.height = 40

        body_rect = content_rect.copy()
        body_rect.top += _DETAIL_BODY_TOP
        body_rect.height = 36

        font.draw_text_centered(
            surface,
            tab.value,
            title_rect,
            _DETAIL_TITLE_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_centered(
            surface,
            "NOT YET IMPLEMENTED",
            body_rect,
            _DETAIL_BODY_SIZE,
            palette.FOREGROUND,
        )

    def _draw_tab_label(
        self,
        surface: pygame.Surface,
        label: str,
        pos: tuple[int, int],
        *,
        selected: bool,
    ) -> None:
        color = palette.FOREGROUND
        text_rect = font.draw_text_left(
            surface,
            label,
            pos,
            _TAB_SIZE,
            color,
        )
        if selected:
            pygame.draw.line(
                surface,
                palette.FOREGROUND,
                (text_rect.left, text_rect.bottom + 4),
                (text_rect.right, text_rect.bottom + 4),
                1,
            )
