"""Background fill helper (M2-T2)."""
from __future__ import annotations

from typing import TYPE_CHECKING

from companion_app.render import palette

if TYPE_CHECKING:
    import pygame


def fill_background(surface: "pygame.Surface") -> None:
    """Fill `surface` with the Pip-Boy `BACKGROUND` color."""
    if surface is None:
        raise ValueError("surface must not be None")
    surface.fill(palette.BACKGROUND)
