"""Screen layout: header + content area + footer (UI refactoring).

Owns the Pip-Boy screen chrome — background fill, header line
(active page name + connection status), separator rule, and the
content rect that pages render into. Footer is a reserved slot
(currently empty) so future footer content does not require a
layout reshuffle.

``Layout`` is a single-instance object built once at startup. It
pre-computes all rects from the virtual surface size and exposes
them as read-only properties.
"""
from __future__ import annotations

import pygame

from companion_app.render import background, font, palette
from companion_app.ui.shell import (
    HEADER_HEIGHT,
    HEADER_LEFT_POS,
    HEADER_RIGHT_POS,
    HEADER_SIZE,
    BODY_SIZE,
    SEPARATOR_Y,
    VIRTUAL_WIDTH,
    VIRTUAL_HEIGHT,
)


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
    def footer_rect(self) -> pygame.Rect:
        return self._footer_rect.copy()

    def draw(
        self,
        surface: pygame.Surface,
        page_name: str,
        connection_status: str,
    ) -> None:
        """Render chrome: background, header, separator.

        Args:
            surface: the 480x800 virtual surface.
            page_name: left-aligned header label (e.g. ``STATUS``).
            connection_status: right-aligned indicator (e.g. ``OK``).
        """
        background.fill_background(surface)

        font.draw_text_left(
            surface,
            page_name,
            HEADER_LEFT_POS,
            HEADER_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_right(
            surface,
            connection_status,
            HEADER_RIGHT_POS,
            HEADER_SIZE,
            palette.FOREGROUND,
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
        """Center ``text`` in the content area.

        Used for connection-state placeholders (``CONNECTING…``,
        ``NO SIGNAL``) when the page cannot render live data.
        """
        font.draw_text_centered(
            surface,
            text,
            self._content_rect,
            BODY_SIZE,
            palette.FOREGROUND,
        )
