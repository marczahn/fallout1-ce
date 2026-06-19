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


def build_green_lut(palette_bytes: bytes) -> list[tuple[int, int, int]]:
    """Map a 768-byte RGB palette to a 256-entry green ramp.

    For each palette entry ``i``, takes ``palette_bytes[3i:3i+3]`` as
    ``(r, g, b)``, computes its luminance, and linearly interpolates from
    ``palette.BACKGROUND`` to ``palette.FOREGROUND`` by ``luminance / 255``.

    Args:
        palette_bytes: exactly 768 bytes (256 RGB triples).

    Returns:
        A list of 256 ``(r, g, b)`` green-ramp tuples.

    Raises:
        ValueError: if ``palette_bytes`` is not exactly 768 bytes.
    """
    if len(palette_bytes) != _PALETTE_BYTES:
        raise ValueError(
            f"palette must be {_PALETTE_BYTES} bytes, got {len(palette_bytes)}"
        )

    bg = palette.BACKGROUND
    fg = palette.FOREGROUND
    lut: list[tuple[int, int, int]] = []
    for i in range(_LUT_ENTRIES):
        r = palette_bytes[3 * i]
        g = palette_bytes[3 * i + 1]
        b = palette_bytes[3 * i + 2]
        t = _luminance(r, g, b) / 255.0
        lut.append(
            (
                _lerp_channel(bg[0], fg[0], t),
                _lerp_channel(bg[1], fg[1], t),
                _lerp_channel(bg[2], fg[2], t),
            )
        )
    return lut


def build_surface(
    pixels: bytes,
    width: int,
    height: int,
    palette_bytes: bytes,
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

    lut = build_green_lut(palette_bytes)
    surf = pygame.image.frombuffer(pixels, (width, height), "P")
    surf.set_palette(lut)
    if pygame.display.get_init() and pygame.display.get_surface() is not None:
        return surf.convert()
    return surf
