"""Row metrics and chrome shared by every scrolling list body (TASK-021).

Extracted from ``ui/pages/inventory.py`` when ARCHIVES/QUESTS became the
second scrolling list on the device. The values are unchanged — this is a
move, not a redesign — and they live here so the two lists cannot drift
into two different row heights, paddings or gutter widths.

Only what is genuinely shared moved. Anything inventory-specific (the
detail readout's geometry, group-heading row height, the slot-symbol
columns) stayed with the inventory: this module is the common denominator,
not a dumping ground.

Pure geometry plus two drawing helpers. Sizes are in the app's 480x800
virtual pixels.
"""
from __future__ import annotations

import pygame

from companion_app.render import palette
from companion_app.ui.shell import PAGE_MARGIN_X

# A selectable row: height, and where its text sits inside it.
ROW_HEIGHT: int = 26
ROW_PAD_X: int = 6
ROW_PAD_Y: int = 5
ROW_SIZE: int = 14

# Selection outline weight when the list does *not* hold the encoder.
OUTLINE_WIDTH: int = 1

# Vertical breathing room inside a section body. The bottom margin is
# load-bearing, not decoration: pygame clips silently at the surface edge,
# so a block that overflows simply disappears rather than erroring.
BODY_MARGIN_TOP: int = 6
BODY_MARGIN_BOTTOM: int = 20

# Scroll gutter on the right, drawn only when the list overflows.
GUTTER_WIDTH: int = 4
GUTTER_GAP: int = 10


def body_inner_rect(body_rect: pygame.Rect) -> pygame.Rect:
    """The body inset to the shared page margin on both sides.

    ``content_rect`` spans the full 480px virtual width (its left edge is
    0), and the sections forward it insetting only the top — so the
    horizontal margin has to be applied here or a list would run to the
    screen edge. Matches how AUTOMAPS insets its map body.
    """
    inner = body_rect.copy()
    inner.left = body_rect.left + PAGE_MARGIN_X
    inner.width = body_rect.width - 2 * PAGE_MARGIN_X
    inner.top = body_rect.top + BODY_MARGIN_TOP
    inner.height = body_rect.height - BODY_MARGIN_TOP - BODY_MARGIN_BOTTOM
    return inner


def draw_scroll_gutter(
    surface: pygame.Surface,
    rect: pygame.Rect,
    row_count: int,
    first_index: int,
    visible_count: int,
) -> None:
    """Filled scroll thumb on a dim track, echoing the S.P.E.C.I.A.L. bars.

    Drawn only when the list actually overflows: a list that fits has no
    scroll position worth reporting, and an always-present full-height
    thumb would be noise.
    """
    if visible_count <= 0 or row_count <= visible_count:
        return

    pygame.draw.rect(surface, palette.DIM, rect)

    span = row_count - visible_count
    thumb_height = max(ROW_HEIGHT, int(rect.height * visible_count / row_count))
    travel = rect.height - thumb_height
    thumb_top = rect.top + int(travel * min(max(first_index, 0), span) / span)
    pygame.draw.rect(
        surface,
        palette.FOREGROUND,
        pygame.Rect(rect.left, thumb_top, rect.width, thumb_height),
    )
