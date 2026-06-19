"""Screen layout: header + content area + footer."""
from __future__ import annotations

import pygame

from companion_app.render import background, font, palette
from companion_app.ui.shell import (
    BODY_SIZE,
    HEADER_HEIGHT,
    HEADER_SIZE,
    PAGE_MARGIN_X,
    SEPARATOR_Y,
)

_CONSOLE_MARGIN_X = 44
_CONSOLE_MARGIN_TOP = 22
_CONSOLE_HEIGHT = 170
_CONSOLE_LABEL_GAP = 10
_CONSOLE_RULE_PADDING = 12
_CONSOLE_FRAME_BOTTOM_GAP = 12

# Centered page headline flanked by a rule on each side. Margins and gap match
# the STATUS page headline / sub-headline treatment so every page is consistent.
_HEADER_RULE_LEFT_X = PAGE_MARGIN_X
_HEADER_RULE_RIGHT_MARGIN = PAGE_MARGIN_X
_HEADER_RULE_GAP = 14


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
        # Centered headline with a rule on each side (matches the STATUS page).
        line_y = title_rect.centery
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (_HEADER_RULE_LEFT_X, line_y),
            (title_rect.left - _HEADER_RULE_GAP, line_y),
            1,
        )
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (title_rect.right + _HEADER_RULE_GAP, line_y),
            (self._width - _HEADER_RULE_RIGHT_MARGIN, line_y),
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
