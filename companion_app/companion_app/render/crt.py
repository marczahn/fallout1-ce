"""CRT visual effects: scanlines, sweep, vignette, and rounded-corner bezel.

All effects are pre-rendered SRCALPHA surfaces built once at startup
and blitted per frame. No per-frame surface rebuilds.

Draw order for the full CRT stack (all optional, controlled by config):
  1. VignetteOverlay     — dark edges, radial gradient
  2. ScanlineOverlay     — horizontal scanlines
  3. VerticalSweepOverlay — moving phosphor sweep band
  4. RoundedCornerOverlay — black bezel masking the four corners
"""
from __future__ import annotations

import math

import pygame

from companion_app.render import palette

# -- Scanlines --------------------------------------------------------

# 35% alpha. 0.35 * 255 = 89.25 -> 89.
_SCANLINE_ALPHA: int = 89
_SCANLINE_PERIOD: int = 2


def build_scanline_overlay(size: tuple[int, int]) -> pygame.Surface:
    if not isinstance(size, tuple) or len(size) != 2:
        raise TypeError("size must be a (width, height) tuple")
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError("size components must be int")
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {size!r}")

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))

    line_color = (palette.BACKGROUND[0], palette.BACKGROUND[1],
                  palette.BACKGROUND[2], _SCANLINE_ALPHA)
    for y in range(0, height, _SCANLINE_PERIOD):
        surface.fill(line_color, rect=pygame.Rect(0, y, width, 1))
    return surface


class ScanlineOverlay:
    def __init__(self, size: tuple[int, int]) -> None:
        self._surface = build_scanline_overlay(size)

    def draw(self, target: pygame.Surface) -> None:
        if target is None:
            raise ValueError("target surface is required")
        target.blit(self._surface, (0, 0))


# -- Vertical sweep ---------------------------------------------------

_SWEEP_DURATION_MS: int = 6800
_SWEEP_HEIGHT_RATIO: float = 0.09
_SWEEP_MAX_RGB: int = 10


def build_vertical_sweep_overlay(
    width: int,
    height: int,
) -> pygame.Surface:
    """Return a prebuilt phosphor sweep band for additive-style blitting."""
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError("width and height must be int")
    if width <= 0 or height <= 0:
        raise ValueError(
            f"width and height must be positive, got {(width, height)!r}"
        )

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))

    green = palette.FOREGROUND[1]
    max_index = max(height - 1, 1)

    for y in range(height):
        # Model the sweep as a bright leading beam with a softer trailing
        # phosphor bloom. A symmetric gradient reads like a synthetic block.
        t = y / max_index
        lead = math.exp(-((t - 0.15) / 0.09) ** 2)
        trail = 0.18 * math.exp(-((t - 0.38) / 0.22) ** 2)
        intensity = min(1.0, lead + trail)
        if intensity <= 0.0:
            continue
        green_value = int(round(green * (_SWEEP_MAX_RGB / 255.0) * intensity))
        alpha_value = int(round(110 * intensity))
        if green_value > 0:
            surface.fill(
                (0, green_value, 0, alpha_value),
                rect=pygame.Rect(0, y, width, 1),
            )

    return surface


def vertical_sweep_top(
    screen_height: int,
    sweep_height: int,
    elapsed_ms: int,
    duration_ms: int = _SWEEP_DURATION_MS,
) -> float:
    """Return the current top-edge position for the moving sweep band."""
    if not isinstance(screen_height, int) or not isinstance(sweep_height, int):
        raise TypeError("screen_height and sweep_height must be int")
    if not isinstance(elapsed_ms, int) or not isinstance(duration_ms, int):
        raise TypeError("elapsed_ms and duration_ms must be int")
    if screen_height <= 0 or sweep_height <= 0:
        raise ValueError("screen_height and sweep_height must be positive")
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")

    progress = (elapsed_ms % duration_ms) / duration_ms
    return (-sweep_height) + ((screen_height + sweep_height) * progress)


class VerticalSweepOverlay:
    def __init__(
        self,
        size: tuple[int, int],
        duration_ms: int = _SWEEP_DURATION_MS,
    ) -> None:
        if not isinstance(size, tuple) or len(size) != 2:
            raise TypeError("size must be a (width, height) tuple")
        width, height = size
        if not isinstance(width, int) or not isinstance(height, int):
            raise TypeError("size components must be int")
        if width <= 0 or height <= 0:
            raise ValueError(f"size must be positive, got {size!r}")
        if duration_ms <= 0:
            raise ValueError(f"duration_ms must be positive, got {duration_ms!r}")

        sweep_height = max(1, int(round(height * _SWEEP_HEIGHT_RATIO)))
        self._screen_height = height
        self._sweep_height = sweep_height
        self._duration_ms = duration_ms
        self._elapsed_ms = 0
        self._surface = build_vertical_sweep_overlay(width, sweep_height)

    def tick(self, dt_ms: int) -> None:
        if not isinstance(dt_ms, int):
            raise TypeError("dt_ms must be int")
        if dt_ms < 0:
            raise ValueError("dt_ms must be >= 0")
        self._elapsed_ms = (self._elapsed_ms + dt_ms) % self._duration_ms

    def draw(self, target: pygame.Surface) -> None:
        if target is None:
            raise ValueError("target surface is required")
        top = int(round(
            vertical_sweep_top(
                self._screen_height,
                self._sweep_height,
                self._elapsed_ms,
                self._duration_ms,
            )
        ))
        target.blit(self._surface, (0, top), special_flags=pygame.BLEND_RGB_ADD)


# -- Vignette ---------------------------------------------------------

# Maximum alpha at the outer corners for the vignette.
_VIGNETTE_MAX_ALPHA: int = 180
# Power curve exponent: >1 shifts the bright center wider so the
# darkening only hits near the edges (non-linear CRT falloff).
_VIGNETTE_POWER: float = 2.5


def build_vignette_overlay(size: tuple[int, int]) -> pygame.Surface:
    """Return an SRCALPHA surface with a radial vignette gradient.

    The centre is fully transparent.  Alpha increases as a power
    function of the normalised distance from centre, reaching
    ``_VIGNETTE_MAX_ALPHA`` at the corners.  Built once at startup;
    do not rebuild per frame.
    """
    if not isinstance(size, tuple) or len(size) != 2:
        raise TypeError("size must be a (width, height) tuple")
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError("size components must be int")
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {size!r}")

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))

    cx = (width - 1) / 2.0
    cy = (height - 1) / 2.0
    max_dist = math.sqrt(cx * cx + cy * cy)

    bg = palette.BACKGROUND

    # Per-pixel radial gradient.  For 480×800 Python is fast enough at
    # startup; this is a one-time cost.
    for y in range(height):
        dy = y - cy
        dy2 = dy * dy
        for x in range(width):
            dx = x - cx
            t = math.sqrt(dx * dx + dy2) / max_dist  # 0 at centre, ~1 at corners
            if t <= 0.0:
                continue
            alpha = int(min(t ** _VIGNETTE_POWER * _VIGNETTE_MAX_ALPHA, 255))
            if alpha > 0:
                surface.set_at((x, y), (bg[0], bg[1], bg[2], alpha))

    return surface


class VignetteOverlay:
    def __init__(self, size: tuple[int, int]) -> None:
        self._surface = build_vignette_overlay(size)

    def draw(self, target: pygame.Surface) -> None:
        if target is None:
            raise ValueError("target surface is required")
        target.blit(self._surface, (0, 0))


# -- Rounded corners --------------------------------------------------

# Default corner radius in virtual pixels.
_DEFAULT_CORNER_RADIUS: int = 36
# Number of pixels over which the corner edge is softly blended.
_CORNER_SOFTNESS: int = 3


def build_rounded_corner_overlay(
    size: tuple[int, int],
    radius: int = _DEFAULT_CORNER_RADIUS,
    softness: int = _CORNER_SOFTNESS,
) -> pygame.Surface:
    """Return an SRCALPHA surface with black bezel corners.

    Four rounded corners are punched out of a fully transparent
    surface so that only the corner areas outside the display
    circle quadrant are opaque black.  The transition edge is
    anti-aliased with ``softness`` pixels of alpha ramp.
    """
    if not isinstance(size, tuple) or len(size) != 2:
        raise TypeError("size must be a (width, height) tuple")
    width, height = size
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError("size components must be int")
    if width <= 0 or height <= 0:
        raise ValueError(f"size must be positive, got {size!r}")
    if radius <= 0:
        raise ValueError(f"radius must be positive, got {radius!r}")

    surface = pygame.Surface((width, height), pygame.SRCALPHA)
    surface.fill((0, 0, 0, 0))

    # Clamp radius to not exceed half the smaller dimension.
    max_radius = min(width, height) // 2
    r = min(radius, max_radius)
    margin = r + softness

    corners: list[tuple[float, float, bool, bool]] = [
        (r, r, True, True),                           # top-left
        (width - r - 1, r, False, True),              # top-right
        (r, height - r - 1, True, False),             # bottom-left
        (width - r - 1, height - r - 1, False, False),# bottom-right
    ]

    for c_cx, c_cy, qx_lt, qy_lt in corners:
        x_start = max(0, int(c_cx - margin))
        x_end = min(width, int(c_cx + margin) + 1)
        y_start = max(0, int(c_cy - margin))
        y_end = min(height, int(c_cy + margin) + 1)

        for y in range(y_start, y_end):
            dy = y - c_cy
            dy2 = dy * dy
            for x in range(x_start, x_end):
                # Only paint pixels in the correct quadrant relative to
                # the corner centre, so the bounding boxes of opposite
                # corners don't spill into the display centre.
                if qx_lt:
                    if x >= c_cx:
                        continue
                else:
                    if x <= c_cx:
                        continue
                if qy_lt:
                    if y >= c_cy:
                        continue
                else:
                    if y <= c_cy:
                        continue

                dx = x - c_cx
                dist = math.sqrt(dx * dx + dy2)
                if dist > r:
                    if dist > r + softness:
                        alpha = 255
                    else:
                        t = (dist - r) / softness
                        alpha = int(min(t * 255, 255))
                    surface.set_at((x, y), (0, 0, 0, alpha))

    return surface


class RoundedCornerOverlay:
    def __init__(
        self,
        size: tuple[int, int],
        radius: int = _DEFAULT_CORNER_RADIUS,
    ) -> None:
        self._surface = build_rounded_corner_overlay(size, radius)

    def draw(self, target: pygame.Surface) -> None:
        if target is None:
            raise ValueError("target surface is required")
        target.blit(self._surface, (0, 0))
