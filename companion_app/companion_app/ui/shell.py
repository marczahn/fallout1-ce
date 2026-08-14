"""Pip-Boy shell geometry constants.

The shell uses a minimal title treatment while keeping the monochrome
Fallout screen language.
"""
from __future__ import annotations

import pygame

HEADER_HEIGHT: int = 56
SEPARATOR_Y: int = HEADER_HEIGHT - 1

# Shared horizontal page margin. The header bar's side rules and any page's
# sub-header (secondary navigation) both anchor to this so their left edges
# stay aligned.
PAGE_MARGIN_X: int = 28

# Vertical band reserved at the top of every section's content rect for the
# segmented sub-header; sections lay their own content out below it. Single
# definition on purpose — two copies would drift, and TASK-017 exists to make
# all three sections share one geometry.
SUBHEADER_BAND_HEIGHT: int = 56

HEADER_SIZE: int = 16
BODY_SIZE: int = 24
STATUS_SIZE: int = 14
TITLE_SIZE: int = 14

HEADER_LEFT_POS: tuple[int, int] = (28, 10)

TAB_START_X: int = 98
TAB_TOP: int = 10
TAB_WIDTH: int = 56
TAB_HEIGHT: int = 20
TAB_GAP: int = 22
TAB_BASELINE_Y: int = 30

VIRTUAL_WIDTH: int = 480
VIRTUAL_HEIGHT: int = 800

BODY_RECT: pygame.Rect = pygame.Rect(
    0, SEPARATOR_Y + 1, VIRTUAL_WIDTH, VIRTUAL_HEIGHT - (SEPARATOR_Y + 1)
)
