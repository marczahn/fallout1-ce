"""STATUS/INVENTORY sub-section — placeholder (TASK-017).

Was a top-level page until TASK-017 moved inventory under STATUS. The real
item list, and the ``Confirm`` interaction for selecting an item, are
TASK-018.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from companion_app.render import font, palette
from companion_app.state import AppState

if TYPE_CHECKING:
    import pygame

PLACEHOLDER_TEXT: str = "NOT YET IMPLEMENTED"
_PLACEHOLDER_SIZE: int = 24


def render_inventory(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
) -> None:
    """Draw the INVENTORY placeholder into the sub-header-inset rect."""
    _ = state
    font.draw_text_centered(
        surface,
        PLACEHOLDER_TEXT,
        body_rect,
        _PLACEHOLDER_SIZE,
        palette.FOREGROUND,
    )
