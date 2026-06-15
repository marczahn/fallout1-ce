"""STATUS page — live HP / max HP display.

Called only when the connection is READY and the player is available.
The NO SIGNAL / CONNECTING placeholders are handled by the Layout.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState

if TYPE_CHECKING:
    import pygame

STATUS_HP_LABEL_SIZE: int = 22
STATUS_HP_VALUE_SIZE: int = 36
_STATUS_MARGIN_X: int = 36
_STATUS_RULE_OFFSET: int = 300
_STATUS_LABEL_OFFSET: int = 322
_STATUS_VALUE_OFFSET: int = 352


class StatusPage:
    """Renders the STATUS page content into the layout's content rect."""

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
    ) -> None:
        left = content_rect.left + _STATUS_MARGIN_X
        rule_y = content_rect.top + _STATUS_RULE_OFFSET
        label_y = content_rect.top + _STATUS_LABEL_OFFSET
        value_y = content_rect.top + _STATUS_VALUE_OFFSET

        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (left, rule_y),
            (content_rect.right - _STATUS_MARGIN_X, rule_y),
            1,
        )
        font.draw_text_left(
            surface,
            "HP",
            (left, label_y),
            STATUS_HP_LABEL_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_left(
            surface,
            f"{state.player.hp}/{state.player.max_hp}",
            (left, value_y),
            STATUS_HP_VALUE_SIZE,
            palette.FOREGROUND,
        )
