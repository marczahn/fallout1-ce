"""World-map image build layer (green-reduction).

The server ships the Fallout world map as a palette-indexed 8-bit buffer
plus a 768-byte RGB palette. The Pip-Boy is monochrome green, so the
original colors are discarded: each palette entry is reduced to its
luminance and mapped onto a single green ramp from ``palette.BACKGROUND``
to ``palette.FOREGROUND``.

``build_green_lut`` is pure and pygame-free so it is unit-testable without
a display. ``build_surface`` performs the one-time pygame Surface build
and keeps its pygame import local.
"""
from __future__ import annotations

from companion_app.render import palette

_LUT_ENTRIES: int = 256
_PALETTE_BYTES: int = _LUT_ENTRIES * 3


def _luminance(r: int, g: int, b: int) -> float:
    """Rec.601 luma of an 8-bit RGB triple, in [0, 255]."""
    return 0.299 * r + 0.587 * g + 0.114 * b


def _lerp_channel(lo: int, hi: int, t: float) -> int:
    return int(round(lo + (hi - lo) * t))


def _posterize(t: float, levels: int) -> float:
    """Snap a [0,1] intensity to one of ``levels`` evenly-spaced steps.

    ``levels >= 256`` is a no-op (full smooth ramp). ``levels == 2`` gives a
    1-bit (black/foreground) result. Fewer levels read as cheaper, more
    limited display hardware.
    """
    if levels >= _LUT_ENTRIES:
        return t
    steps = levels - 1
    return round(t * steps) / steps


def build_green_lut(
    palette_bytes: bytes, levels: int = _LUT_ENTRIES
) -> list[tuple[int, int, int]]:
    """Map a 768-byte RGB palette to a 256-entry green ramp.

    For each palette entry ``i``, takes ``palette_bytes[3i:3i+3]`` as
    ``(r, g, b)``, computes its luminance, posterizes it to ``levels``
    discrete steps, and linearly interpolates from ``palette.BACKGROUND`` to
    ``palette.FOREGROUND``.

    Args:
        palette_bytes: exactly 768 bytes (256 RGB triples).
        levels: number of distinct green shades (2..256). ``256`` is a
            smooth ramp; lower values are chunkier / more retro.

    Returns:
        A list of 256 ``(r, g, b)`` green-ramp tuples.

    Raises:
        ValueError: if ``palette_bytes`` is not exactly 768 bytes.
    """
    if len(palette_bytes) != _PALETTE_BYTES:
        raise ValueError(
            f"palette must be {_PALETTE_BYTES} bytes, got {len(palette_bytes)}"
        )
    levels = max(2, min(_LUT_ENTRIES, levels))

    bg = palette.BACKGROUND
    fg = palette.FOREGROUND
    lut: list[tuple[int, int, int]] = []
    for i in range(_LUT_ENTRIES):
        r = palette_bytes[3 * i]
        g = palette_bytes[3 * i + 1]
        b = palette_bytes[3 * i + 2]
        t = _posterize(_luminance(r, g, b) / 255.0, levels)
        lut.append(
            (
                _lerp_channel(bg[0], fg[0], t),
                _lerp_channel(bg[1], fg[1], t),
                _lerp_channel(bg[2], fg[2], t),
            )
        )
    return lut


def coarse_dims(dest_w: int, dest_h: int, blocks_across: int) -> tuple[int, int]:
    """Coarse (downsampled) size for pixelating a ``dest_w x dest_h`` blit.

    Returns the low-resolution size to scale down to before scaling back up
    with nearest-neighbor, giving ~``blocks_across`` chunky blocks across the
    width. Clamped so it never upsamples (coarse <= dest).
    """
    if dest_w <= 0 or dest_h <= 0:
        return (1, 1)
    cw = max(1, min(blocks_across, dest_w))
    ch = max(1, min(int(round(blocks_across * dest_h / dest_w)), dest_h))
    return (cw, ch)


def pixelate(surf, dest_w: int, dest_h: int, blocks_across: int):
    """Scale ``surf`` to ``dest_w x dest_h`` as ``blocks_across`` chunky blocks.

    Downsamples to a coarse grid then nearest-neighbor upscales, producing
    blocky "low-res hardware" pixels. ``blocks_across`` large enough to equal
    or exceed ``dest_w`` degrades to a plain nearest-neighbor scale.
    """
    import pygame

    dest_w = max(1, dest_w)
    dest_h = max(1, dest_h)
    cw, ch = coarse_dims(dest_w, dest_h, blocks_across)
    small = pygame.transform.scale(surf, (cw, ch))
    return pygame.transform.scale(small, (dest_w, dest_h))


def build_surface(
    pixels: bytes,
    width: int,
    height: int,
    palette_bytes: bytes,
    levels: int = _LUT_ENTRIES,
):  # -> pygame.Surface
    """Build a green-reduced ``pygame.Surface`` from an indexed buffer.

    This is the ONE-TIME build: an 8-bit palette-indexed Surface is created
    from ``pixels`` and its palette is replaced with the green LUT. The
    result is ``.convert()``-ed when a display is available (skipped in
    headless test runs so the call does not raise).

    Args:
        pixels: ``width * height`` 8-bit palette indices.
        width: image width in pixels.
        height: image height in pixels.
        palette_bytes: 768-byte RGB palette (reduced via ``build_green_lut``).

    Returns:
        A ``pygame.Surface`` ready to scale and blit.
    """
    import pygame

    lut = build_green_lut(palette_bytes, levels)
    surf = pygame.image.frombuffer(pixels, (width, height), "P")
    surf.set_palette(lut)
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return surf.convert()
    return surf
