"""Drawn equipped-slot marks for the STATUS/INVENTORY list (TASK-018).

Replaces the ``[R.HAND]`` / ``[L.HAND]`` / ``[WORN]`` text tags with small
symbols: a right hand, a left hand, and a torso for worn armor.

**These have to be drawn, not typed.** The vendored Fallout webfont
(``render/font.py``) is ASCII-only -- probed with ``Font.get_metrics``, it
has no ``☚ ☛ ☜ ☞``, no ``← →``, no ``◀ ▶``, not even ``■`` or ``●`` -- and
there is deliberately no fallback face (Resolved Decision 12), so a missing
glyph draws nothing at all. Composing the marks from ``pygame.draw``
primitives is the same route ``_draw_corner_box`` and ``_draw_scroll_gutter``
already take.

**Silhouettes, not line art.** The marks are read at a 26px row height on a
480x800 virtual surface and then pushed through the CRT filter, so interior
detail does not survive. Each icon is one or two filled blocks whose outline
carries the whole meaning: hands are mittens distinguished only by which side
the thumb sticks out, and the torso is a wide shoulder bar over a narrower
body.

The colour is passed in rather than taken from the palette, because a
selected + activated row inverts: its text flips to ``palette.BACKGROUND``
and the icon has to flip with it or it vanishes into the fill.
"""
from __future__ import annotations

from typing import Callable

import pygame

# One box for every slot, so a row's layout does not shift when the item in
# it changes hands.
ICON_WIDTH: int = 10
ICON_HEIGHT: int = 10

_Color = tuple[int, int, int]

# Mitten geometry, as offsets inside the icon box. The thumb side is what
# distinguishes left from right; everything else is identical.
_PALM_WIDTH: int = 6
_PALM_TOP: int = 1
_PALM_HEIGHT: int = 9
_THUMB_WIDTH: int = 3
_THUMB_TOP: int = 3
_THUMB_HEIGHT: int = 4

# Torso: shoulder bar over a narrower body.
_SHOULDER_TOP: int = 1
_SHOULDER_HEIGHT: int = 3
_BODY_INSET_X: int = 2
_BODY_TOP: int = 4
_BODY_HEIGHT: int = 6


def _draw_hand(
    surface: pygame.Surface,
    rect: pygame.Rect,
    color: _Color,
    *,
    thumb_on_right: bool,
) -> None:
    """A mitten with the thumb on one side; the side is the only cue."""
    palm_left = rect.left if thumb_on_right else rect.right - _PALM_WIDTH
    thumb_left = (
        rect.left + _PALM_WIDTH if thumb_on_right else rect.right - _PALM_WIDTH - _THUMB_WIDTH
    )
    pygame.draw.rect(
        surface,
        color,
        pygame.Rect(palm_left, rect.top + _PALM_TOP, _PALM_WIDTH, _PALM_HEIGHT),
    )
    pygame.draw.rect(
        surface,
        color,
        pygame.Rect(
            thumb_left, rect.top + _THUMB_TOP, _THUMB_WIDTH, _THUMB_HEIGHT
        ),
    )


def _draw_right_hand(
    surface: pygame.Surface, rect: pygame.Rect, color: _Color
) -> None:
    _draw_hand(surface, rect, color, thumb_on_right=True)


def _draw_left_hand(
    surface: pygame.Surface, rect: pygame.Rect, color: _Color
) -> None:
    _draw_hand(surface, rect, color, thumb_on_right=False)


def _draw_torso(
    surface: pygame.Surface, rect: pygame.Rect, color: _Color
) -> None:
    """Shoulders over a body -- a vest read from the front."""
    pygame.draw.rect(
        surface,
        color,
        pygame.Rect(rect.left, rect.top + _SHOULDER_TOP, rect.width, _SHOULDER_HEIGHT),
    )
    pygame.draw.rect(
        surface,
        color,
        pygame.Rect(
            rect.left + _BODY_INSET_X,
            rect.top + _BODY_TOP,
            rect.width - 2 * _BODY_INSET_X,
            _BODY_HEIGHT,
        ),
    )


_Renderer = Callable[[pygame.Surface, pygame.Rect, _Color], None]

# Keyed by the wire's `slot` values. A slot with no entry -- `none`, or
# anything a future schema adds -- simply draws nothing, so an unknown value
# can never blank out a row or raise mid-render.
_ICONS: dict[str, _Renderer] = {
    "rightHand": _draw_right_hand,
    "leftHand": _draw_left_hand,
    "worn": _draw_torso,
}


def has_icon(slot: str) -> bool:
    """Whether ``slot`` has a mark to draw."""
    return slot in _ICONS


def draw_midleft(
    surface: pygame.Surface,
    slot: str,
    midleft: tuple[int, int],
    color: _Color,
) -> pygame.Rect | None:
    """Draw ``slot``'s mark with its left edge and vertical centre at ``midleft``.

    Returns the icon's rect, or ``None`` when the slot has no mark.
    """
    renderer = _ICONS.get(slot)
    if renderer is None:
        return None
    left, centery = midleft
    rect = pygame.Rect(left, centery - ICON_HEIGHT // 2, ICON_WIDTH, ICON_HEIGHT)
    renderer(surface, rect, color)
    return rect


def draw_midright(
    surface: pygame.Surface,
    slot: str,
    midright: tuple[int, int],
    color: _Color,
) -> pygame.Rect | None:
    """As ``draw_midleft``, anchored by the right edge instead."""
    right, centery = midright
    return draw_midleft(surface, slot, (right - ICON_WIDTH, centery), color)
