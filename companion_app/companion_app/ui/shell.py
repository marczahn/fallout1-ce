"""Static screen shell: header + body composition (M2-T3).

Layout (virtual pixel coordinates, 480x800 surface):

- Header occupies the top 40 px.
- Section name is left-anchored at (16, 8) (top-left).
- Status text is right-anchored at (464, 8) (top-right) i.e. 16 px
  right margin.
- A 1-px DIM separator rule sits at y = 40.
- Body rect runs from (0, 41) to (480, 800); body text is centered
  within it.

`draw_shell` is a pure draw call: it takes its strings as parameters
so M3+ can pass live values without rewriting this module. It does
NOT initialize pygame, mutate module-level state, or know about the
input layer, config, or debug overlay.

Reserved connection-status vocabulary (M3+, documented now so the
header layout does not need to be renegotiated): `OK`, `NO SIGNAL`,
`CONNECTING`, `RECONNECTING`. M2 only ever passes `--`. M2 always
renders the status in FOREGROUND; state-driven colors land with M3.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from companion_app.render import background, font, palette

if TYPE_CHECKING:
    pass

HEADER_HEIGHT: int = 40
SEPARATOR_Y: int = 40

HEADER_SIZE: int = 22
BODY_SIZE: int = 32

HEADER_LEFT_POS: tuple[int, int] = (16, 8)
HEADER_RIGHT_POS: tuple[int, int] = (464, 8)  # 480 - 16 right margin

VIRTUAL_WIDTH: int = 480
VIRTUAL_HEIGHT: int = 800

BODY_RECT: pygame.Rect = pygame.Rect(
    0, SEPARATOR_Y + 1, VIRTUAL_WIDTH, VIRTUAL_HEIGHT - (SEPARATOR_Y + 1)
)


def draw_shell(
    surface: pygame.Surface,
    section_name: str,
    status: str,
    body_text: str,
) -> None:
    """Render the static Pip-Boy screen shell onto `surface`.

    Args:
        surface: the 480x800 virtual surface.
        section_name: left-aligned header label (e.g. `STATUS`).
        status: right-aligned connection indicator (e.g. `--`).
        body_text: centered placeholder text in the body rect.
    """
    background.fill_background(surface)

    font.draw_text_left(
        surface, section_name, HEADER_LEFT_POS, HEADER_SIZE, palette.FOREGROUND
    )
    font.draw_text_right(
        surface, status, HEADER_RIGHT_POS, HEADER_SIZE, palette.FOREGROUND
    )

    pygame.draw.line(
        surface,
        palette.DIM,
        (0, SEPARATOR_Y),
        (VIRTUAL_WIDTH - 1, SEPARATOR_Y),
        1,
    )

    font.draw_text_centered(
        surface, body_text, BODY_RECT, BODY_SIZE, palette.FOREGROUND
    )
