"""Screen layout: header + content area + footer."""
from __future__ import annotations

import pygame

from companion_app.render import background, font, palette
from companion_app.ui.pages import Page
from companion_app.ui.shell import (
    BODY_SIZE,
    HEADER_HEIGHT,
    HEADER_SIZE,
    SEPARATOR_Y,
)

_CONSOLE_MARGIN_X = 44
_CONSOLE_MARGIN_TOP = 22
_CONSOLE_HEIGHT = 170
_HEADER_RIGHT_MARGIN = 28
_UNDERLINE_GAP = 4


class Layout:
    """Pip-Boy screen layout with a live section/status header."""

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
        self._footer_rect = pygame.Rect(0, self._height, self._width, 0)

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
        """Render background and the top header."""
        background.fill_background(surface)

        page_rect = pygame.Rect(0, 0, self._width, HEADER_HEIGHT)
        title_rect = font.draw_text_centered(
            surface,
            current_page.name,
            page_rect,
            HEADER_SIZE,
            palette.FOREGROUND,
        )
        if connection_status and connection_status != "OK":
            font.draw_text_right(
                surface,
                connection_status,
                (self._width - _HEADER_RIGHT_MARGIN, title_rect.top),
                HEADER_SIZE,
                palette.DIM,
            )
        pygame.draw.line(
            surface,
            palette.DIM,
            (title_rect.left, title_rect.bottom + _UNDERLINE_GAP),
            (title_rect.right, title_rect.bottom + _UNDERLINE_GAP),
            1,
        )

    def draw_placeholder(self, surface: pygame.Surface, text: str) -> None:
        font.draw_text_centered(
            surface,
            text,
            self._content_rect,
            BODY_SIZE,
            palette.FOREGROUND,
        )
