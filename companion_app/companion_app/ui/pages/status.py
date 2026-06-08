"""STATUS page — live HP / max HP display.

Called only when the connection is READY and the player is available.
The NO SIGNAL / CONNECTING placeholders are handled by the Layout.
"""
from __future__ import annotations

from companion_app.render import font, palette

STATUS_HP_LABEL_SIZE: int = 28
STATUS_HP_VALUE_SIZE: int = 48
STATUS_HP_LEFT: int = 48
STATUS_HP_TOP: int = 220


class StatusPage:
    """Renders the STATUS page content into the layout's content rect."""

    def render(self, surface, content_rect, state) -> None:
        _ = content_rect  # reserved for future boundary clamping
        font.draw_text_left(
            surface,
            "HP",
            (STATUS_HP_LEFT, STATUS_HP_TOP),
            STATUS_HP_LABEL_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_left(
            surface,
            f"{state.player.hp} / {state.player.max_hp}",
            (STATUS_HP_LEFT, STATUS_HP_TOP + 36),
            STATUS_HP_VALUE_SIZE,
            palette.FOREGROUND,
        )
