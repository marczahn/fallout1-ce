"""Screen layout: header + content area + footer (UI refactoring).

Owns the Pip-Boy screen chrome — background fill, title row,
Fallout-4-style tab strip, separator rule, and the content rect that
pages render into. Footer is a reserved slot (currently empty) so
future footer content does not require a layout reshuffle.
"""
from __future__ import annotations

import pygame

from companion_app.render import background, font, palette
from companion_app.ui.pages import Page
from companion_app.ui.shell import (
    BODY_SIZE,
    HEADER_LEFT_POS,
    HEADER_RIGHT_POS,
    HEADER_SIZE,
    SEPARATOR_Y,
    STATUS_SIZE,
    TAB_GAP,
    TAB_HEIGHT,
    TAB_START_X,
    TAB_TOP,
    TAB_WIDTH,
)

_TAB_FILL = (0, 28, 0)
_CONSOLE_MARGIN_X = 24
_CONSOLE_MARGIN_TOP = 18
_CONSOLE_HEIGHT = 214


class Layout:
    """Pip-Boy screen layout with header, content area, and footer."""

    def __init__(self, virtual_size: tuple[int, int]) -> None:
        self._width, self._height = virtual_size
        self._content_rect = pygame.Rect(
            0,
            SEPARATOR_Y + 1,
            self._width,
            self._height - (SEPARATOR_Y + 1),
        )
        self._console_rect = pygame.Rect(
            _CONSOLE_MARGIN_X,
            self._content_rect.top + _CONSOLE_MARGIN_TOP,
            self._width - (_CONSOLE_MARGIN_X * 2),
            _CONSOLE_HEIGHT,
        )
        self._footer_rect = pygame.Rect(
            0,
            self._height,
            self._width,
            0,
        )

    @property
    def content_rect(self) -> pygame.Rect:
        return self._content_rect.copy()

    @property
    def console_rect(self) -> pygame.Rect:
        return self._console_rect.copy()

    @property
    def footer_rect(self) -> pygame.Rect:
        return self._footer_rect.copy()

    def draw(
        self,
        surface: pygame.Surface,
        current_page: Page,
        connection_status: str,
    ) -> None:
        """Render chrome: background, title row, tab strip, separator."""
        background.fill_background(surface)

        font.draw_text_left(
            surface,
            "PIP-BOY 2000",
            HEADER_LEFT_POS,
            STATUS_SIZE,
            palette.DIM,
        )
        font.draw_text_right(
            surface,
            connection_status,
            HEADER_RIGHT_POS,
            STATUS_SIZE,
            palette.FOREGROUND,
        )

        for page, rect in self._tab_rects():
            is_active = page is current_page
            if is_active:
                pygame.draw.rect(surface, _TAB_FILL, rect)
                pygame.draw.rect(surface, palette.FOREGROUND, rect, 2)
                label_color = palette.FOREGROUND
            else:
                pygame.draw.rect(surface, palette.DIM, rect, 1)
                pygame.draw.line(
                    surface,
                    palette.DIM,
                    (rect.left, rect.bottom),
                    (rect.right, rect.bottom),
                    1,
                )
                label_color = palette.DIM

            label_rect = font.draw_text_centered(
                surface,
                page.tab_label,
                rect,
                HEADER_SIZE,
                label_color,
            )
            if is_active:
                pygame.draw.line(
                    surface,
                    palette.FOREGROUND,
                    (label_rect.left, rect.bottom - 5),
                    (label_rect.right, rect.bottom - 5),
                    1,
                )

        pygame.draw.line(
            surface,
            palette.DIM,
            (0, SEPARATOR_Y),
            (self._width - 1, SEPARATOR_Y),
            1,
        )

    def draw_placeholder(
        self,
        surface: pygame.Surface,
        text: str,
    ) -> None:
        """Center ``text`` in the content area."""
        font.draw_text_centered(
            surface,
            text,
            self._content_rect,
            BODY_SIZE,
            palette.FOREGROUND,
        )

    def _tab_rects(self) -> list[tuple[Page, pygame.Rect]]:
        pages = list(Page)
        rects: list[tuple[Page, pygame.Rect]] = []
        x = TAB_START_X
        for page in pages:
            rects.append((page, pygame.Rect(x, TAB_TOP, TAB_WIDTH, TAB_HEIGHT)))
            x += TAB_WIDTH + TAB_GAP
        return rects
