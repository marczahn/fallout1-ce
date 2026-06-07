"""Font loader for the vendored Fallout webfont (M2-T1).

The font ships inside the installed package as `assets/jh_fallout-webfont.ttf`
and is resolved via `importlib.resources` so editable installs and built
wheels both work.

Missing or unreadable font assets are fatal at startup. There is no
fallback to the pygame default font: the M2 visual identity depends on
this specific face (Resolved Decision 12).

Importing this module does NOT initialize `pygame.display`. The first
`load_font(...)` call requires `pygame.freetype.init()` (which calls
`pygame.init()` indirectly if needed); callers are expected to have
already initialized pygame via the normal startup path.
"""
from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable
from typing import TYPE_CHECKING

import pygame

if TYPE_CHECKING:
    import pygame.freetype

# The font ships inside the `companion_app` package under `assets/`
# and is declared as `[tool.setuptools.package-data]` in pyproject.toml
# so it survives editable installs and wheels.
FONT_RESOURCE_PACKAGE = "companion_app.assets"
FONT_FILENAME = "jh_fallout-webfont.ttf"


class FontLoadError(RuntimeError):
    """Raised when the vendored font asset cannot be located or read."""


_font_bytes_cache: bytes | None = None


def _resolve_font_traversable() -> Traversable:
    """Locate the font file inside the installed package layout."""
    try:
        candidate = resources.files(FONT_RESOURCE_PACKAGE) / FONT_FILENAME
    except (ModuleNotFoundError, FileNotFoundError) as e:
        raise FontLoadError(
            f"font asset package {FONT_RESOURCE_PACKAGE!r} not importable: {e}"
        ) from e
    if not candidate.is_file():
        raise FontLoadError(
            f"font asset {FONT_FILENAME!r} not found at {candidate!s}"
        )
    return candidate


def _load_font_bytes() -> bytes:
    global _font_bytes_cache
    if _font_bytes_cache is not None:
        return _font_bytes_cache
    traversable = _resolve_font_traversable()
    try:
        data = traversable.read_bytes()
    except OSError as e:
        raise FontLoadError(
            f"cannot read font asset at {traversable!s}: {e}"
        ) from e
    if not data:
        raise FontLoadError(f"font asset at {traversable!s} is empty")
    _font_bytes_cache = data
    return data


def load_font(size: int) -> "pygame.freetype.Font":
    """Return a `pygame.freetype.Font` for the vendored font at `size` px.

    Raises:
        ValueError: if `size` is not a positive integer.
        FontLoadError: if the asset cannot be located or read.
    """
    if not isinstance(size, int) or isinstance(size, bool):
        raise TypeError(f"size must be int, got {type(size).__name__}")
    if size <= 0:
        raise ValueError(f"size must be > 0, got {size}")

    import io

    import pygame.freetype

    if not pygame.freetype.was_init():
        pygame.freetype.init()

    data = _load_font_bytes()
    return pygame.freetype.Font(io.BytesIO(data), size=size)


_font_size_cache: "dict[int, pygame.freetype.Font]" = {}


def _get_font(size: int) -> "pygame.freetype.Font":
    cached = _font_size_cache.get(size)
    if cached is not None:
        return cached
    font = load_font(size)
    _font_size_cache[size] = font
    return font


def _validate_text_args(
    surface: "pygame.Surface | None",
    text: str,
    size: int,
) -> None:
    if surface is None:
        raise ValueError("surface must not be None")
    if not isinstance(text, str):
        raise TypeError(f"text must be str, got {type(text).__name__}")
    if not isinstance(size, int) or isinstance(size, bool):
        raise TypeError(f"size must be int, got {type(size).__name__}")
    if size <= 0:
        raise ValueError(f"size must be > 0, got {size}")


def draw_text_left(
    surface: "pygame.Surface",
    text: str,
    pos: tuple[int, int],
    size: int,
    color: tuple[int, int, int],
) -> "pygame.Rect":
    """Draw `text` left-anchored at `pos` (top-left in virtual pixels).

    Returns the blitted rect.
    """
    _validate_text_args(surface, text, size)
    font = _get_font(size)
    rect = font.get_rect(text, size=size)
    rect.topleft = pos
    font.render_to(surface, rect.topleft, text, color, size=size)
    return rect


def draw_text_right(
    surface: "pygame.Surface",
    text: str,
    right_pos: tuple[int, int],
    size: int,
    color: tuple[int, int, int],
) -> "pygame.Rect":
    """Draw `text` right-anchored: `right_pos` is the top-right corner."""
    _validate_text_args(surface, text, size)
    font = _get_font(size)
    rect = font.get_rect(text, size=size)
    rect.topright = right_pos
    font.render_to(surface, rect.topleft, text, color, size=size)
    return rect


def draw_text_centered(
    surface: "pygame.Surface",
    text: str,
    rect: "pygame.Rect",
    size: int,
    color: tuple[int, int, int],
) -> "pygame.Rect":
    """Draw `text` centered inside `rect`. Returns the blitted rect."""
    _validate_text_args(surface, text, size)
    font = _get_font(size)
    text_rect = font.get_rect(text, size=size)
    text_rect.center = rect.center
    font.render_to(surface, text_rect.topleft, text, color, size=size)
    return text_rect


def font_render_surface(
    text: str,
    size: int,
    color: tuple[int, int, int] | pygame.Color,
) -> pygame.Surface | None:
    """Render `text` to a new transparent surface and return it.

    Returns ``None`` if the text is empty (nothing to blit).
    """
    if not text:
        return None
    font = _get_font(size)
    rect = font.get_rect(text, size=size)
    surf = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
    font.render_to(surf, (0, 0), text, color, size=size)
    return surf
