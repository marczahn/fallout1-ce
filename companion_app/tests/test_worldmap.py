"""Tests for the world-map feature (frontend).

Display-free: the network state machine, chunk reassembly, the green LUT,
and all the fit / viewport / marker geometry are exercised without a
pygame display.
"""
from __future__ import annotations

import base64
import unittest

from companion_app.net.client import (
    MAP_MAX_RETRIES,
    MAP_REQUEST_TIMEOUT_SECONDS,
    NetworkClient,
)
from companion_app.render import palette
from companion_app.render.worldmap_image import build_green_lut
from companion_app.state import AppState, PlayerSurface, WorldInfo, WorldMapStatus
from companion_app.ui.pages.map import (
    MARKER_LAST_KNOWN,
    MARKER_LIVE,
    MARKER_NONE,
    WORLD_ZOOM,
    compute_atlas_fit,
    compute_world_viewport,
    default_map_ui,
    select_marker_mode,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _make_client(schema_version: int = 5) -> tuple[NetworkClient, AppState]:
    state = AppState()
    state.world = WorldInfo(schema_version=schema_version, game="fallout1-ce", player_available=True)
    client = NetworkClient(host="x", port=1, password="pw", state=state)
    return client, state


# ── F3: fetch state machine + chunk reassembly ─────────────────────────


class MapFetchTests(unittest.TestCase):
    def test_start_fetch_on_ready_sends_getMap(self) -> None:
        client, state = _make_client(schema_version=5)
        client._maybe_start_map_fetch()
        self.assertEqual(state.world_map.status, WorldMapStatus.FETCHING)
        self.assertIn(b"getMap", client._write_buf)

    def test_schema_below_5_is_unavailable(self) -> None:
        client, state = _make_client(schema_version=4)
        client._maybe_start_map_fetch()
        self.assertEqual(state.world_map.status, WorldMapStatus.UNAVAILABLE)
        self.assertNotIn(b"getMap", client._write_buf)

    def test_full_reassembly_even_chunks(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        # 2x3 = 6 pixels, chunk_bytes=3 -> 2 full chunks.
        pixels = bytes([1, 2, 3, 4, 5, 6])
        palette_bytes = bytes(range(256)) * 3  # 768 bytes
        client._dispatch({
            "type": "mapHeader", "width": 2, "height": 3,
            "paletteB64": _b64(palette_bytes), "chunkCount": 2, "chunkBytes": 3,
        })
        self.assertEqual(state.world_map.status, WorldMapStatus.FETCHING)
        self.assertIn(b"getMapChunk", client._write_buf)
        client._dispatch({"type": "mapChunk", "index": 0, "dataB64": _b64(pixels[0:3])})
        client._dispatch({"type": "mapChunk", "index": 1, "dataB64": _b64(pixels[3:6])})
        self.assertEqual(state.world_map.status, WorldMapStatus.READY)
        self.assertEqual(state.world_map.pixels, pixels)
        self.assertEqual(state.world_map.width, 2)
        self.assertEqual(state.world_map.height, 3)

    def test_partial_last_chunk(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        # 5 pixels, chunk_bytes=2 -> chunks of 2,2,1.
        pixels = bytes([10, 20, 30, 40, 50])
        palette_bytes = bytes(768)
        client._dispatch({
            "type": "mapHeader", "width": 5, "height": 1,
            "paletteB64": _b64(palette_bytes), "chunkCount": 3, "chunkBytes": 2,
        })
        client._dispatch({"type": "mapChunk", "index": 0, "dataB64": _b64(pixels[0:2])})
        client._dispatch({"type": "mapChunk", "index": 1, "dataB64": _b64(pixels[2:4])})
        self.assertEqual(state.world_map.status, WorldMapStatus.FETCHING)
        client._dispatch({"type": "mapChunk", "index": 2, "dataB64": _b64(pixels[4:5])})
        self.assertEqual(state.world_map.status, WorldMapStatus.READY)
        self.assertEqual(state.world_map.pixels, pixels)

    def test_length_mismatch_is_unavailable(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        palette_bytes = bytes(768)
        # Header claims 6 px but the chunk only supplies 3.
        client._dispatch({
            "type": "mapHeader", "width": 2, "height": 3,
            "paletteB64": _b64(palette_bytes), "chunkCount": 1, "chunkBytes": 6,
        })
        client._dispatch({"type": "mapChunk", "index": 0, "dataB64": _b64(bytes([1, 2, 3]))})
        self.assertEqual(state.world_map.status, WorldMapStatus.UNAVAILABLE)

    def test_bad_palette_length_is_unavailable(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        client._dispatch({
            "type": "mapHeader", "width": 2, "height": 3,
            "paletteB64": _b64(bytes(100)), "chunkCount": 1, "chunkBytes": 6,
        })
        self.assertEqual(state.world_map.status, WorldMapStatus.UNAVAILABLE)

    def test_map_error_is_unavailable(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        client._dispatch({"type": "mapError", "reason": "no map loaded"})
        self.assertEqual(state.world_map.status, WorldMapStatus.UNAVAILABLE)

    def test_out_of_order_chunk_ignored(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        client._dispatch({
            "type": "mapHeader", "width": 2, "height": 1,
            "paletteB64": _b64(bytes(768)), "chunkCount": 2, "chunkBytes": 1,
        })
        # Wrong index: ignored, next_index unchanged.
        client._dispatch({"type": "mapChunk", "index": 5, "dataB64": _b64(bytes([9]))})
        self.assertEqual(state.world_map.next_index, 0)
        self.assertEqual(state.world_map.status, WorldMapStatus.FETCHING)

    def test_timeout_retries_then_gives_up(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        wm = state.world_map
        # Force the clock far past the timeout for each tick.
        for _ in range(MAP_MAX_RETRIES):
            wm.last_request_at = -1e9
            client._tick_map_fetch()
            self.assertEqual(wm.status, WorldMapStatus.FETCHING)
        wm.last_request_at = -1e9
        client._tick_map_fetch()
        self.assertEqual(wm.status, WorldMapStatus.UNAVAILABLE)

    def test_timeout_not_triggered_within_window(self) -> None:
        import time as _time
        client, state = _make_client()
        client._maybe_start_map_fetch()
        state.world_map.last_request_at = _time.monotonic()
        client._tick_map_fetch()
        self.assertEqual(state.world_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.world_map.retries, 0)
        self.assertGreater(MAP_REQUEST_TIMEOUT_SECONDS, 0)

    def test_reconnect_resets_map(self) -> None:
        client, state = _make_client()
        client._maybe_start_map_fetch()
        state.world_map.status = WorldMapStatus.READY
        client._close_socket()
        self.assertEqual(state.world_map.status, WorldMapStatus.IDLE)

    def test_apply_world_location_tracks_last_known(self) -> None:
        client, state = _make_client()
        self.assertFalse(state.has_world_fix)
        client._apply_world_location({"x": 120, "y": 240})
        self.assertTrue(state.has_world_fix)
        self.assertEqual(state.last_known_world_x, 120)
        self.assertEqual(state.last_known_world_y, 240)


# ── F4: green LUT ──────────────────────────────────────────────────────


class GreenLutTests(unittest.TestCase):
    def test_length_and_zero_and_max(self) -> None:
        # Grayscale ramp: entry i has rgb (i, i, i).
        pal = bytes(b for i in range(256) for b in (i, i, i))
        lut = build_green_lut(pal)
        self.assertEqual(len(lut), 256)
        self.assertEqual(lut[0], palette.BACKGROUND)
        self.assertEqual(lut[255], palette.FOREGROUND)

    def test_monotonic_ramp(self) -> None:
        pal = bytes(b for i in range(256) for b in (i, i, i))
        lut = build_green_lut(pal)
        greens = [g for (_r, g, _b) in lut]
        self.assertTrue(all(greens[i] <= greens[i + 1] for i in range(255)))

    def test_bad_palette_raises(self) -> None:
        with self.assertRaises(ValueError):
            build_green_lut(bytes(10))

    def test_posterize_collapses_to_n_distinct_shades(self) -> None:
        pal = bytes(b for i in range(256) for b in (i, i, i))
        lut = build_green_lut(pal, levels=4)
        # A 256-entry grayscale ramp posterized to 4 levels yields exactly 4
        # distinct output colors, and still spans BACKGROUND..FOREGROUND.
        distinct = {rgb for rgb in lut}
        self.assertEqual(len(distinct), 4)
        self.assertEqual(lut[0], palette.BACKGROUND)
        self.assertEqual(lut[255], palette.FOREGROUND)

    def test_posterize_two_levels_is_one_bit(self) -> None:
        pal = bytes(b for i in range(256) for b in (i, i, i))
        lut = build_green_lut(pal, levels=2)
        self.assertEqual({rgb for rgb in lut}, {palette.BACKGROUND, palette.FOREGROUND})

    def test_levels_256_is_smooth(self) -> None:
        pal = bytes(b for i in range(256) for b in (i, i, i))
        self.assertEqual(build_green_lut(pal, levels=256), build_green_lut(pal))


class CoarseDimsTests(unittest.TestCase):
    def test_blocks_across_sets_width_and_keeps_aspect(self) -> None:
        from companion_app.render.worldmap_image import coarse_dims

        cw, ch = coarse_dims(400, 200, 100)
        self.assertEqual(cw, 100)
        self.assertEqual(ch, 50)  # 100 * 200/400

    def test_never_upsamples(self) -> None:
        from companion_app.render.worldmap_image import coarse_dims

        # blocks larger than the destination clamp to the destination size.
        self.assertEqual(coarse_dims(40, 20, 1000), (40, 20))

    def test_degenerate(self) -> None:
        from companion_app.render.worldmap_image import coarse_dims

        self.assertEqual(coarse_dims(0, 0, 10), (1, 1))


# ── F5: atlas fit math ─────────────────────────────────────────────────


class AtlasFitTests(unittest.TestCase):
    def test_wide_map_letterboxed_vertically(self) -> None:
        # 200x100 map into 100x100 view -> scale 0.5, dest 100x50.
        fit = compute_atlas_fit(200, 100, 100, 100)
        self.assertAlmostEqual(fit.scale, 0.5)
        self.assertEqual((fit.dest_w, fit.dest_h), (100, 50))
        self.assertEqual(fit.offset_x, 0)
        self.assertEqual(fit.offset_y, 25)

    def test_tall_map_letterboxed_horizontally(self) -> None:
        fit = compute_atlas_fit(100, 200, 100, 100)
        self.assertAlmostEqual(fit.scale, 0.5)
        self.assertEqual((fit.dest_w, fit.dest_h), (50, 100))
        self.assertEqual(fit.offset_x, 25)
        self.assertEqual(fit.offset_y, 0)

    def test_degenerate_returns_zero(self) -> None:
        fit = compute_atlas_fit(0, 0, 100, 100)
        self.assertEqual(fit.scale, 0.0)


# ── F6: world viewport / clamp / marker ────────────────────────────────


class WorldViewportTests(unittest.TestCase):
    # map 100x100, zoom 2 -> source window 50x50 (view 100x100).
    MAP = 100
    VIEW = 100
    ZOOM = 2.0
    HALF = 25  # src_w//2 with src_w=50

    def _vp(self, px: int, py: int):
        return compute_world_viewport(
            self.MAP, self.MAP, self.ZOOM, self.VIEW, self.VIEW, px, py
        )

    def test_centered(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(50, 50)
        self.assertEqual((w, h), (50, 50))
        self.assertEqual((left, top), (25, 25))
        # Marker centered in the view.
        self.assertEqual((mx, my), (50, 50))

    def test_clamp_left(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(5, 50)
        self.assertEqual(left, 0)  # cannot scroll past left edge
        self.assertEqual(mx, int(5 * self.ZOOM))  # marker moves toward edge

    def test_clamp_right(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(95, 50)
        self.assertEqual(left, self.MAP - w)  # 50
        self.assertEqual(mx, int((95 - left) * self.ZOOM))

    def test_clamp_top(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(50, 5)
        self.assertEqual(top, 0)
        self.assertEqual(my, int(5 * self.ZOOM))

    def test_clamp_bottom(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(50, 95)
        self.assertEqual(top, self.MAP - h)
        self.assertEqual(my, int((95 - top) * self.ZOOM))

    def test_corner(self) -> None:
        (left, top, w, h), (mx, my) = self._vp(0, 0)
        self.assertEqual((left, top), (0, 0))
        self.assertEqual((mx, my), (0, 0))


# ── F7: marker-mode selector ───────────────────────────────────────────


class MarkerModeTests(unittest.TestCase):
    def test_world_surface_is_live(self) -> None:
        self.assertEqual(select_marker_mode(PlayerSurface.WORLD, False), MARKER_LIVE)
        self.assertEqual(select_marker_mode(PlayerSurface.WORLD, True), MARKER_LIVE)

    def test_local_with_fix_is_last_known(self) -> None:
        self.assertEqual(select_marker_mode(PlayerSurface.LOCAL, True), MARKER_LAST_KNOWN)

    def test_local_without_fix_is_none(self) -> None:
        self.assertEqual(select_marker_mode(PlayerSurface.LOCAL, False), MARKER_NONE)

    def test_unknown_without_fix_is_none(self) -> None:
        self.assertEqual(select_marker_mode(PlayerSurface.UNKNOWN, False), MARKER_NONE)


class DefaultMapUiTests(unittest.TestCase):
    def test_three_segments_local_default(self) -> None:
        ui = default_map_ui()
        self.assertEqual([s.key for s in ui.segments], ["LOCAL", "ATLAS", "WORLD"])
        self.assertEqual(ui.selected_key, "LOCAL")
        self.assertTrue(all(s.enabled for s in ui.segments))


if __name__ == "__main__":
    unittest.main()
