"""Deprecated layout constants (UI refactoring).

The ``Layout`` class in ``ui/layout.py`` now owns all layout logic.
These constants are kept here for backward compat with any module
that imports them. New code should import from ``ui.layout``.
"""
from __future__ import annotations

import pygame

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



