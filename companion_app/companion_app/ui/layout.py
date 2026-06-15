"""Screen layout: header + content area + footer."""
from __future__ import annotations

import pygame

from companion_app.render import background, font, palette
from companion_app.ui.shell import (
    BODY_SIZE,
    HEADER_HEIGHT,
    HEADER_SIZE,
    SEPARATOR_Y,
)

_CONSOLE_MARGIN_X = 44
_CONSOLE_MARGIN_TOP = 22
_CONSOLE_HEIGHT = 170
_UNDERLINE_GAP = 4
_CONSOLE_LABEL_GAP = 10
_CONSOLE_RULE_PADDING = 12
_CONSOLE_FRAME_BOTTOM_GAP = 12


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
        title: str | None,
    ) -> None:
        """Render background and the top header."""
        background.fill_background(surface)
        if not title:
            return

        page_rect = pygame.Rect(0, 0, self._width, HEADER_HEIGHT)
        title_rect = font.draw_text_centered(
            surface,
            title,
            page_rect,
            HEADER_SIZE,
            palette.FOREGROUND,
        )
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (title_rect.left, title_rect.bottom + _UNDERLINE_GAP),
            (title_rect.right, title_rect.bottom + _UNDERLINE_GAP),
            1,
        )

    def draw_console_frame(self, surface: pygame.Surface) -> None:
        label_rect = font.draw_text_left(
            surface,
            'CONSOLE',
            (self._console_rect.left, self._console_rect.top),
            HEADER_SIZE,
            palette.FOREGROUND,
        )
        rule_y = label_rect.bottom + _CONSOLE_LABEL_GAP
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (self._console_rect.left, rule_y),
            (self._console_rect.right - _CONSOLE_RULE_PADDING, rule_y),
            1,
        )
        bottom_y = self._console_rect.bottom + _CONSOLE_FRAME_BOTTOM_GAP
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (self._console_rect.left, bottom_y),
            (self._console_rect.right - _CONSOLE_RULE_PADDING, bottom_y),
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
