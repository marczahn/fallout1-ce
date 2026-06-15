"""MAP page — stub (post-MVP)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from companion_app.render import font, palette
from companion_app.state import AppState

if TYPE_CHECKING:
    import pygame


class MapPage:
    """Placeholder MAP page."""

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
    ) -> None:
        _ = state
        font.draw_text_centered(
            surface,
            "NOT YET IMPLEMENTED",
            content_rect,
            24,
            palette.FOREGROUND,
        )
