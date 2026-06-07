"""STATUS section — live HP / maxHP display (M4).

Renders HP data from the companion server when a player is loaded, or
NO SIGNAL when the server reports playerUnavailable.
"""
from __future__ import annotations

import pygame

from companion_app.render import font, palette
from companion_app.ui.shell import BODY_RECT, BODY_SIZE, HEADER_SIZE

STATUS_HP_LABEL_SIZE: int = 28
STATUS_HP_VALUE_SIZE: int = 48
STATUS_HP_LEFT: int = 48
STATUS_HP_TOP: int = 220
STATUS_LABEL_COLOR: tuple[int, int, int] = palette.FOREGROUND
STATUS_VALUE_COLOR: tuple[int, int, int] = palette.FOREGROUND
STATUS_NO_SIGNAL_COLOR: tuple[int, int, int] = palette.DIM


def draw_status(
    surface: pygame.Surface,
    player_available: bool,
    hp: int,
    max_hp: int,
) -> None:
    """Render the STATUS section body onto *surface*."""
    if not player_available:
        font.draw_text_centered(
            surface,
            "NO SIGNAL",
            BODY_RECT,
            BODY_SIZE,
            STATUS_NO_SIGNAL_COLOR,
        )
        return

    font.draw_text_left(
        surface,
        "HP",
        (STATUS_HP_LEFT, STATUS_HP_TOP),
        STATUS_HP_LABEL_SIZE,
        STATUS_LABEL_COLOR,
    )

    font.draw_text_left(
        surface,
        f"{hp} / {max_hp}",
        (STATUS_HP_LEFT, STATUS_HP_TOP + 36),
        STATUS_HP_VALUE_SIZE,
        STATUS_VALUE_COLOR,
    )
