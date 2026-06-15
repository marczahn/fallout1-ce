"""CRT visual effects: startup power-on, scanlines, sweep, vignette, and bezel.

All effects are pre-rendered SRCALPHA surfaces built once at startup
and blitted per frame where practical. The startup power-on effect
reuses a cached working surface and transforms the already-rendered
startup frame for a short time at launch.

Draw order for the full CRT stack (all optional, controlled by config):
  1. PowerOnEffect       — startup-only raster expansion + wobble
  2. VignetteOverlay     — dark edges, radial gradient
  3. ScanlineOverlay     — horizontal scanlines
  4. VerticalSweepOverlay — moving phosphor sweep band
  5. RoundedCornerOverlay — black bezel masking the four corners
"""
from __future__ import annotations

import math

import pygame

from companion_app.render import palette

# -- Startup power-on -------------------------------------------------

_POWER_ON_DURATION_MS: int = 720
_POWER_ON_BEAM_HOLD_MS: int = 140
_POWER_ON_MIN_HEIGHT_RATIO: float = 0.003
_POWER_ON_MAX_WOBBLE_PX: int = 18
_POWER_ON_WOBBLE_CYCLES: float = 2.75
_POWER_ON_BEAM_THICKNESS: int = 3
_POWER_ON_BEAM_GLOW_ALPHA: int = 220


def power_on_progress(
    elapsed_ms: int,
    duration_ms: int = _POWER_ON_DURATION_MS,
) -> float:
    if not isinstance(elapsed_ms, int) or not isinstance(duration_ms, int):
        raise TypeError("elapsed_ms and duration_ms must be int")
    if elapsed_ms < 0:
        raise ValueError("elapsed_ms must be >= 0")
    if duration_ms <= 0:
        raise ValueError("duration_ms must be positive")
    if elapsed_ms >= duration_ms:
        return 1.0
    return elapsed_ms / duration_ms


def power_on_visible_height(
    screen_height: int,
    elapsed_ms: int,
    duration_ms: int = _POWER_ON_DURATION_MS,
    beam_hold_ms: int = _POWER_ON_BEAM_HOLD_MS,
    min_height_ratio: float = _POWER_ON_MIN_HEIGHT_RATIO,
) -> int:
    if not isinstance(screen_height, int):
        raise TypeError("screen_height must be int")
    if screen_height <= 0:
        raise ValueError("screen_height must be positive")
    if not isinstance(min_height_ratio, (int, float)) or isinstance(min_height_ratio, bool):
        raise TypeError("min_height_ratio must be a number")
    if min_height_ratio <= 0.0 or min_height_ratio > 1.0:
        raise ValueError("min_height_ratio must be in (0, 1]")

    if not isinstance(beam_hold_ms, int):
        raise TypeError("beam_hold_ms must be int")
    if beam_hold_ms < 0 or beam_hold_ms >= duration_ms:
        raise ValueError("beam_hold_ms must be >= 0 and < duration_ms")

    if elapsed_ms < beam_hold_ms:
        return max(1, int(round(screen_height * min_height_ratio)))

    reveal_elapsed = elapsed_ms - beam_hold_ms
    reveal_duration = duration_ms - beam_hold_ms
    progress = power_on_progress(reveal_elapsed, reveal_duration)
    eased = 1.0 - ((1.0 - progress) ** 3)
    min_height = max(1, int(round(screen_height * min_height_ratio)))
    return min(
        screen_height,
        max(min_height, int(round(min_height + ((screen_height - min_height) * eased)))),
    )


def power_on_wobble_offset(
    elapsed_ms: int,
    duration_ms: int = _POWER_ON_DURATION_MS,
    beam_hold_ms: int = _POWER_ON_BEAM_HOLD_MS,
    max_wobble_px: int = _POWER_ON_MAX_WOBBLE_PX,
) -> int:
    if not isinstance(max_wobble_px, int):
        raise TypeError("max_wobble_px must be int")
    if max_wobble_px < 0:
        raise ValueError("max_wobble_px must be >= 0")

    if not isinstance(beam_hold_ms, int):
        raise TypeError("beam_hold_ms must be int")
    if beam_hold_ms < 0 or beam_hold_ms >= duration_ms:
        raise ValueError("beam_hold_ms must be >= 0 and < duration_ms")

    if elapsed_ms < beam_hold_ms:
        return 0

    progress = power_on_progress(elapsed_ms - beam_hold_ms, duration_ms - beam_hold_ms)
    if progress >= 1.0 or max_wobble_px == 0:
        return 0

    envelope = (1.0 - progress) ** 2
    angle = progress * math.tau * _POWER_ON_WOBBLE_CYCLES
    return int(round(math.sin(angle) * max_wobble_px * envelope))


def power_on_beam_visible(
    elapsed_ms: int,
    beam_hold_ms: int = _POWER_ON_BEAM_HOLD_MS,
) -> bool:
    if not isinstance(elapsed_ms, int) or not isinstance(beam_hold_ms, int):
        raise TypeError("elapsed_ms and beam_hold_ms must be int")
    if elapsed_ms < 0:
        raise ValueError("elapsed_ms must be >= 0")
    if beam_hold_ms < 0:
        raise ValueError("beam_hold_ms must be >= 0")
    return elapsed_ms < beam_hold_ms


class PowerOnEffect:
    def __init__(
        self,
        size: tuple[int, int],
        duration_ms: int = _POWER_ON_DURATION_MS,
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

        self._width = width
        self._height = height
        self._duration_ms = duration_ms
        self._elapsed_ms = 0
        self._working = pygame.Surface((width, height))
        self._beam_hold_ms = _POWER_ON_BEAM_HOLD_MS

    @property
    def is_complete(self) -> bool:
        return self._elapsed_ms >= self._duration_ms

    def tick(self, dt_ms: int) -> None:
        if not isinstance(dt_ms, int):
            raise TypeError("dt_ms must be int")
        if dt_ms < 0:
            raise ValueError("dt_ms must be >= 0")
        self._elapsed_ms = min(self._duration_ms, self._elapsed_ms + dt_ms)

    def apply(self, target: pygame.Surface) -> None:
        if target is None:
            raise ValueError("target surface is required")
        if self.is_complete:
            return

        self._working.blit(target, (0, 0))
        center_y = self._height // 2
        target.fill(palette.BACKGROUND)
        if power_on_beam_visible(self._elapsed_ms, self._beam_hold_ms):
            beam_rect = pygame.Rect(
                0,
                center_y - (_POWER_ON_BEAM_THICKNESS // 2),
                self._width,
                _POWER_ON_BEAM_THICKNESS,
            )
            target.fill(palette.FOREGROUND, beam_rect)
            glow_half = max(3, self._height // 40)
            glow = pygame.Surface((self._width, glow_half * 2), pygame.SRCALPHA)
            for y in range(glow.get_height()):
                dist = abs(y - glow_half) / max(glow_half, 1)
                alpha = int(round(max(0.0, 1.0 - dist) * _POWER_ON_BEAM_GLOW_ALPHA))
                if alpha <= 0:
                    continue
                glow.fill((palette.FOREGROUND[0], palette.FOREGROUND[1], palette.FOREGROUND[2], alpha),
                          rect=pygame.Rect(0, y, self._width, 1))
            target.blit(glow, (0, center_y - glow_half))
            return

        visible_height = power_on_visible_height(
            self._height,
            self._elapsed_ms,
            self._duration_ms,
            self._beam_hold_ms,
        )
        wobble_x = power_on_wobble_offset(
            self._elapsed_ms,
            self._duration_ms,
            self._beam_hold_ms,
        )

        scaled = pygame.transform.smoothscale(
            self._working,
            (self._width, visible_height),
        )
        dest_y = (self._height - visible_height) // 2
        target.blit(scaled, (wobble_x, dest_y))

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

    def reset(self) -> None:
        self._elapsed_ms = 0

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
