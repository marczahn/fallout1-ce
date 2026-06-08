"""Pip-Boy shell geometry constants.

The shell now uses a compact title row plus a four-tab strip inspired
by the Fallout 4 companion app while staying inside the monochrome
Fallout 1 screen treatment.
"""
from __future__ import annotations

import pygame

HEADER_HEIGHT: int = 86
SEPARATOR_Y: int = HEADER_HEIGHT - 1

HEADER_SIZE: int = 16
BODY_SIZE: int = 24
STATUS_SIZE: int = 14

HEADER_LEFT_POS: tuple[int, int] = (18, 8)
HEADER_RIGHT_POS: tuple[int, int] = (462, 8)

TAB_START_X: int = 18
TAB_TOP: int = 28
TAB_WIDTH: int = 94
TAB_HEIGHT: int = 34
TAB_GAP: int = 8

VIRTUAL_WIDTH: int = 480
VIRTUAL_HEIGHT: int = 800

BODY_RECT: pygame.Rect = pygame.Rect(
    0, SEPARATOR_Y + 1, VIRTUAL_WIDTH, VIRTUAL_HEIGHT - (SEPARATOR_Y + 1)
)
