"""MAP page — LOCAL / ATLAS / WORLD world-map view.

Three sub-header segments:

* ``LOCAL``  -- the in-town/local map (still a placeholder).
* ``ATLAS``  -- the whole Fallout world map fit to the screen, letterboxed.
* ``WORLD``  -- the world map zoomed in and scrolled to follow the player,
  clamped at the map borders.

The green-reduced ``pygame.Surface`` is built once (lazily) and cached on
the ``MapPage`` instance, keyed to the underlying pixel buffer. All the
fit / viewport / marker geometry lives in pure module-level helpers so it
is unit-testable without a display.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from companion_app.render import font, palette
from companion_app.render import worldmap_image
from companion_app.state import AppState, PlayerSurface, WorldMapStatus
from companion_app.ui import segmented_header
from companion_app.ui.segmented_header import Segment, SegmentedHeaderState
from companion_app.ui.shell import PAGE_MARGIN_X
from companion_app.config import DEFAULT_MAP_GREEN_LEVELS, DEFAULT_MAP_PIXEL_BLOCKS

if TYPE_CHECKING:
    import pygame

_MAP_BODY_TOP: int = 56
# Keep the map inset from the screen border like the other pages: the same
# horizontal page margin on the left/right, and a matching bottom margin.
_MAP_MARGIN_BOTTOM: int = PAGE_MARGIN_X
_BODY_SIZE: int = 22
_LABEL_SIZE: int = 14

# WORLD zoom: 1 map pixel -> this many screen pixels. ~448px content width
# over a ~1400px-wide Fallout world map: a modest zoom that keeps the
# player's surroundings legible while still scrolling.
WORLD_ZOOM: float = 2.0

# Marker: a full-span "plotter" crosshair — one vertical and one horizontal
# line through the player, spanning the whole map panel. A 1px dark backing
# keeps the thin bright lines legible over bright-green land. On WORLD the
# lines stay centered until the view clamps at a map border.
_MARKER_LINE_W: int = 1
_MARKER_BACKING_W: int = 3

# Marker draw modes (F7 selector outputs).
MARKER_LIVE: str = "live"
MARKER_LAST_KNOWN: str = "last-known"
MARKER_NONE: str = "no-fix"


def default_map_ui() -> SegmentedHeaderState:
    """Initial MAP control state: LOCAL, ATLAS, WORLD; LOCAL selected."""
    return segmented_header.create(
        (
            Segment("LOCAL", "LOCAL"),
            Segment("ATLAS", "ATLAS"),
            Segment("WORLD", "WORLD"),
        )
    )


# ── pure geometry helpers (unit-testable, no pygame) ───────────────────


@dataclass(frozen=True)
class AtlasFit:
    """Result of fitting a map into a view with letterboxing."""

    scale: float
    dest_w: int
    dest_h: int
    offset_x: int
    offset_y: int


def compute_atlas_fit(
    map_w: int, map_h: int, view_w: int, view_h: int
) -> AtlasFit:
    """Fit ``map_w x map_h`` inside ``view_w x view_h`` preserving aspect.

    Returns the uniform scale factor, the scaled destination size, and the
    top-left letterbox offset that centers the scaled image in the view.
    """
    if map_w <= 0 or map_h <= 0 or view_w <= 0 or view_h <= 0:
        return AtlasFit(scale=0.0, dest_w=0, dest_h=0, offset_x=0, offset_y=0)

    scale = min(view_w / map_w, view_h / map_h)
    dest_w = max(1, int(map_w * scale))
    dest_h = max(1, int(map_h * scale))
    offset_x = (view_w - dest_w) // 2
    offset_y = (view_h - dest_h) // 2
    return AtlasFit(
        scale=scale,
        dest_w=dest_w,
        dest_h=dest_h,
        offset_x=offset_x,
        offset_y=offset_y,
    )


def atlas_marker_pos(fit: AtlasFit, player_x: int, player_y: int) -> tuple[int, int]:
    """Map an image-pixel player position to view-pixel coordinates."""
    return (
        fit.offset_x + int(player_x * fit.scale),
        fit.offset_y + int(player_y * fit.scale),
    )


def compute_world_viewport(
    map_w: int,
    map_h: int,
    zoom: float,
    view_w: int,
    view_h: int,
    player_x: int,
    player_y: int,
) -> tuple[tuple[int, int, int, int], tuple[int, int]]:
    """Center a zoomed viewport on the player, clamped to the map borders.

    The view shows a ``view_w x view_h`` window of the map scaled by
    ``zoom``. The source window covers ``view_w/zoom x view_h/zoom`` map
    pixels and is centered on the player, then clamped so it never extends
    past a map edge. When clamped, the marker shifts toward that edge
    rather than the view scrolling further.

    Returns:
        ``(src_rect, marker_xy_in_view)`` where ``src_rect`` is
        ``(left, top, w, h)`` in MAP-pixel space and ``marker_xy_in_view``
        is in scaled VIEW-pixel space.
    """
    # Size of the source window in map pixels (clamped to the map itself).
    src_w = min(map_w, max(1, int(round(view_w / zoom))))
    src_h = min(map_h, max(1, int(round(view_h / zoom))))

    # Center on the player, then clamp the top-left so the window stays
    # inside [0, map - src].
    left = player_x - src_w // 2
    top = player_y - src_h // 2
    left = max(0, min(left, map_w - src_w))
    top = max(0, min(top, map_h - src_h))

    # Marker position relative to the (clamped) source window, scaled.
    marker_x = int((player_x - left) * zoom)
    marker_y = int((player_y - top) * zoom)
    return (left, top, src_w, src_h), (marker_x, marker_y)


def select_marker_mode(surface: PlayerSurface, has_world_fix: bool) -> str:
    """Decide which marker to draw on ATLAS/WORLD.

    * On the WORLD surface there are live coords -> a live marker.
    * On a LOCAL surface, fall back to the last-known position if one was
      ever seen, else no marker at all.
    """
    if surface is PlayerSurface.WORLD:
        return MARKER_LIVE
    if has_world_fix:
        return MARKER_LAST_KNOWN
    return MARKER_NONE


# ── page ────────────────────────────────────────────────────────────


class MapPage:
    """MAP page with a LOCAL / ATLAS / WORLD sub-header segmented control."""

    title = "MAP"

    def __init__(
        self,
        green_levels: int = DEFAULT_MAP_GREEN_LEVELS,
        pixel_blocks: int = DEFAULT_MAP_PIXEL_BLOCKS,
    ) -> None:
        # Rendering knobs (config-driven; see config.map.greenLevels /
        # config.map.pixelBlocks). Fixed per run.
        self._green_levels = green_levels
        self._pixel_blocks = pixel_blocks
        # Cached green surface plus the identity of the pixels it was built
        # from, so we rebuild only when a fresh buffer arrives.
        self._surface: "pygame.Surface | None" = None
        self._built_pixels_id: int | None = None
        self._built_len: int = 0

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        ui_state: SegmentedHeaderState,
    ) -> None:
        segmented_header.render(surface, content_rect, ui_state)

        # Inset the map body from the screen border to match the other pages:
        # PAGE_MARGIN_X on the left/right and a matching bottom margin.
        body_rect = content_rect.copy()
        body_rect.top += _MAP_BODY_TOP
        body_rect.left += PAGE_MARGIN_X
        body_rect.width = content_rect.width - 2 * PAGE_MARGIN_X
        body_rect.height = content_rect.height - _MAP_BODY_TOP - _MAP_MARGIN_BOTTOM

        key = ui_state.selected_key
        if key == "ATLAS":
            self._render_atlas(surface, body_rect, state)
        elif key == "WORLD":
            self._render_world(surface, body_rect, state)
        else:
            self._render_local(surface, body_rect)

    # ── LOCAL ──────────────────────────────────────────────────────

    def _render_local(self, surface: pygame.Surface, body_rect: pygame.Rect) -> None:
        font.draw_text_centered(
            surface, "LOCAL MAP - NOT YET IMPLEMENTED", body_rect, _BODY_SIZE,
            palette.FOREGROUND,
        )

    # ── shared map-surface plumbing ────────────────────────────────

    def _ensure_surface(self, state: AppState) -> "pygame.Surface | None":
        """Return the cached green surface, rebuilding if the pixels changed."""
        wm = state.world_map
        if wm.status is not WorldMapStatus.READY or not wm.pixels:
            return None
        if (
            self._surface is not None
            and self._built_pixels_id == id(wm.pixels)
            and self._built_len == len(wm.pixels)
        ):
            return self._surface
        self._surface = worldmap_image.build_surface(
            wm.pixels, wm.width, wm.height, wm.palette, self._green_levels
        )
        self._built_pixels_id = id(wm.pixels)
        self._built_len = len(wm.pixels)
        return self._surface

    def _draw_status_message(
        self, surface: pygame.Surface, body_rect: pygame.Rect, state: AppState
    ) -> bool:
        """Draw a LOADING / UNAVAILABLE message if the map is not READY.

        Returns ``True`` if a message was drawn (caller should stop).
        """
        status = state.world_map.status
        if status is WorldMapStatus.UNAVAILABLE:
            font.draw_text_centered(
                surface, "MAP UNAVAILABLE", body_rect, _BODY_SIZE, palette.DIM
            )
            return True
        if status in (WorldMapStatus.IDLE, WorldMapStatus.FETCHING):
            font.draw_text_centered(
                surface, "LOADING MAP...", body_rect, _BODY_SIZE, palette.DIM
            )
            return True
        return False

    def _draw_marker(
        self,
        surface: pygame.Surface,
        body_rect: pygame.Rect,
        view_xy: tuple[int, int],
        map_rect: "pygame.Rect | None" = None,
    ) -> None:
        import pygame

        # The crosshair spans the drawn MAP rectangle, not the whole panel:
        # in ATLAS the map is letterboxed, so spanning the panel would run the
        # lines into the empty bars. Defaults to the panel (WORLD fills it).
        extent = body_rect if map_rect is None else map_rect

        cx = body_rect.left + view_xy[0]
        cy = body_rect.top + view_xy[1]
        # Only draw if the player falls within the drawn map area.
        if not extent.collidepoint(cx, cy):
            return

        bg = palette.BACKGROUND  # black: the contrast backing
        fg = palette.FOREGROUND

        # Clip so the lines stay within the map rectangle.
        prev_clip = surface.get_clip()
        surface.set_clip(extent)

        # Full-span plotter crosshair: a vertical line through the player's x
        # and a horizontal line through the player's y, each a thin bright line
        # over a slightly wider dark backing so it reads on bright-green land.
        for color, w in ((bg, _MARKER_BACKING_W), (fg, _MARKER_LINE_W)):
            pygame.draw.line(surface, color, (cx, extent.top), (cx, extent.bottom), w)
            pygame.draw.line(surface, color, (extent.left, cy), (extent.right, cy), w)

        surface.set_clip(prev_clip)

    def _dim_overlay(
        self, surface: pygame.Surface, rect: pygame.Rect
    ) -> None:
        import pygame

        overlay = pygame.Surface((rect.width, rect.height), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        surface.blit(overlay, rect.topleft)

    # ── ATLAS ──────────────────────────────────────────────────────

    def _render_atlas(
        self, surface: pygame.Surface, body_rect: pygame.Rect, state: AppState
    ) -> None:
        import pygame

        if self._draw_status_message(surface, body_rect, state):
            return
        green = self._ensure_surface(state)
        if green is None:
            font.draw_text_centered(
                surface, "MAP UNAVAILABLE", body_rect, _BODY_SIZE, palette.DIM
            )
            return

        wm = state.world_map
        fit = compute_atlas_fit(wm.width, wm.height, body_rect.width, body_rect.height)
        if fit.scale <= 0.0:
            return

        scaled = worldmap_image.pixelate(
            green, fit.dest_w, fit.dest_h, self._pixel_blocks
        )
        dest = (body_rect.left + fit.offset_x, body_rect.top + fit.offset_y)
        surface.blit(scaled, dest)

        mode = select_marker_mode(state.player.surface, state.has_world_fix)
        if mode == MARKER_NONE:
            # Map shown, but no fix to mark: dim + advise (LOCAL fallback).
            self._dim_overlay(surface, body_rect)
            font.draw_text_centered(
                surface, "NO WORLD FIX", body_rect, _LABEL_SIZE, palette.FOREGROUND
            )
            return

        if mode == MARKER_LAST_KNOWN:
            self._dim_overlay(surface, body_rect)
            px, py = state.last_known_world_x, state.last_known_world_y
            font.draw_text_left(
                surface, "LAST KNOWN",
                (body_rect.left + fit.offset_x + 4, body_rect.top + fit.offset_y + 4),
                _LABEL_SIZE, palette.FOREGROUND,
            )
        else:
            px, py = state.player.world_x, state.player.world_y

        marker_view = (
            fit.offset_x + int(px * fit.scale),
            fit.offset_y + int(py * fit.scale),
        )
        map_rect = pygame.Rect(
            body_rect.left + fit.offset_x,
            body_rect.top + fit.offset_y,
            fit.dest_w,
            fit.dest_h,
        )
        self._draw_marker(surface, body_rect, marker_view, map_rect)

    # ── WORLD ──────────────────────────────────────────────────────

    def _render_world(
        self, surface: pygame.Surface, body_rect: pygame.Rect, state: AppState
    ) -> None:
        import pygame

        if self._draw_status_message(surface, body_rect, state):
            return
        green = self._ensure_surface(state)
        if green is None:
            font.draw_text_centered(
                surface, "MAP UNAVAILABLE", body_rect, _BODY_SIZE, palette.DIM
            )
            return

        wm = state.world_map
        mode = select_marker_mode(state.player.surface, state.has_world_fix)

        if mode == MARKER_NONE:
            # No fix ever: show the whole map dimmed and advise.
            fit = compute_atlas_fit(
                wm.width, wm.height, body_rect.width, body_rect.height
            )
            if fit.scale > 0.0:
                scaled = worldmap_image.pixelate(
                    green, fit.dest_w, fit.dest_h, self._pixel_blocks
                )
                surface.blit(
                    scaled, (body_rect.left + fit.offset_x, body_rect.top + fit.offset_y)
                )
            self._dim_overlay(surface, body_rect)
            font.draw_text_centered(
                surface, "NO WORLD FIX", body_rect, _LABEL_SIZE, palette.FOREGROUND
            )
            return

        if mode == MARKER_LAST_KNOWN:
            px, py = state.last_known_world_x, state.last_known_world_y
        else:
            px, py = state.player.world_x, state.player.world_y

        src_rect, marker_view = compute_world_viewport(
            wm.width, wm.height, WORLD_ZOOM,
            body_rect.width, body_rect.height, px, py,
        )
        left, top, src_w, src_h = src_rect
        # Crop the needed source region, then scale only that region.
        cropped = green.subsurface(pygame.Rect(left, top, src_w, src_h))
        dest_w = int(src_w * WORLD_ZOOM)
        dest_h = int(src_h * WORLD_ZOOM)
        scaled = worldmap_image.pixelate(
            cropped, max(1, dest_w), max(1, dest_h), self._pixel_blocks
        )
        # The scaled region may be larger than the body; clip the blit.
        surface.blit(scaled, body_rect.topleft, area=pygame.Rect(0, 0, body_rect.width, body_rect.height))

        if mode == MARKER_LAST_KNOWN:
            self._dim_overlay(surface, body_rect)
            font.draw_text_left(
                surface, "LAST KNOWN",
                (body_rect.left + 4, body_rect.top + 4),
                _LABEL_SIZE, palette.FOREGROUND,
            )
        self._draw_marker(surface, body_rect, marker_view)
