"""Tests for the local-map (automap) feature (frontend).

Display-free: the tile->pixel marker transform, the LOCAL view-state
selector, and the local-map fetch driver (refetch-on-change, in-flight
restart, chunk echo validation, reassembly) are exercised without a pygame
display, mirroring tests/test_worldmap.py.
"""
from __future__ import annotations

import base64
import time
import unittest

from companion_app.net.client import (
    LOCAL_MAP_MIN_SCHEMA_VERSION,
    LOCAL_MAP_REFRESH_SECONDS,
    NetworkClient,
)
from companion_app.state import (
    AppState,
    ConnectionState,
    PlayerSurface,
    WorldInfo,
    WorldMapStatus,
)
from companion_app.ui.pages.map import (
    LOCAL_VIEW_LOADING,
    LOCAL_VIEW_MAP,
    LOCAL_VIEW_NOT_EXPLORED,
    LOCAL_VIEW_UNAVAILABLE,
    LOCAL_VIEW_WORLD,
    MARKER_LAST_KNOWN,
    MARKER_NONE,
    local_marker_pixel,
    select_local_view,
    select_marker_mode,
)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _make_client(
    schema_version: int = 6,
    *,
    on_local: bool = True,
    map_index: int = 5,
    elevation: int = 0,
    tile: int = 20100,
) -> tuple[NetworkClient, AppState]:
    state = AppState()
    state.world = WorldInfo(
        schema_version=schema_version, game="fallout1-ce", player_available=True
    )
    if on_local:
        state.player.surface = PlayerSurface.LOCAL
        state.player.local_map_index = map_index
        state.player.elevation = elevation
        state.player.tile = tile
    client = NetworkClient(host="x", port=1, password="pw", state=state)
    # The constructor forces connection to DISCONNECTED; the fetch driver only
    # runs once READY, so set it after construction.
    state.connection = ConnectionState.READY
    return client, state


# ── F5: tile -> image-pixel marker transform ──────────────────────────


class LocalMarkerTransformTests(unittest.TestCase):
    def test_edge_and_mid_tiles(self) -> None:
        # Composition of the engine write formula (automap.cc decode_map_data)
        # and the read order (draw_top_down_map_pipboy) over the 200x200 grid.
        self.assertEqual(local_marker_pixel(0), (0, 1))
        self.assertEqual(local_marker_pixel(199), (1, 0))
        self.assertEqual(local_marker_pixel(200), (0, 2))
        self.assertEqual(local_marker_pixel(39999), (1, 199))
        # Geometric center maps to the image center.
        self.assertEqual(local_marker_pixel(20100), (100, 100))

    def test_marker_in_bounds(self) -> None:
        for tile in (0, 1, 199, 200, 20100, 39999):
            x, y = local_marker_pixel(tile)
            self.assertTrue(0 <= x < 200, f"x out of range for tile {tile}: {x}")
            self.assertTrue(0 <= y < 200, f"y out of range for tile {tile}: {y}")


# ── F6: LOCAL view-state selection ─────────────────────────────────────


class LocalViewSelectionTests(unittest.TestCase):
    def test_world_surface_overrides_everything(self) -> None:
        for status in WorldMapStatus:
            for has_img in (True, False):
                self.assertEqual(
                    select_local_view(PlayerSurface.WORLD, status, has_img, False),
                    LOCAL_VIEW_WORLD,
                )

    def test_no_image_unavailable(self) -> None:
        self.assertEqual(
            select_local_view(
                PlayerSurface.LOCAL, WorldMapStatus.UNAVAILABLE,
                has_current_image=False, is_empty=False,
            ),
            LOCAL_VIEW_UNAVAILABLE,
        )

    def test_no_image_loading(self) -> None:
        for status in (WorldMapStatus.IDLE, WorldMapStatus.FETCHING):
            self.assertEqual(
                select_local_view(
                    PlayerSurface.LOCAL, status,
                    has_current_image=False, is_empty=False,
                ),
                LOCAL_VIEW_LOADING,
            )

    def test_image_empty_is_not_explored(self) -> None:
        self.assertEqual(
            select_local_view(
                PlayerSurface.LOCAL, WorldMapStatus.READY,
                has_current_image=True, is_empty=True,
            ),
            LOCAL_VIEW_NOT_EXPLORED,
        )

    def test_image_with_content_is_map(self) -> None:
        self.assertEqual(
            select_local_view(
                PlayerSurface.LOCAL, WorldMapStatus.READY,
                has_current_image=True, is_empty=False,
            ),
            LOCAL_VIEW_MAP,
        )

    def test_background_refresh_keeps_map_no_flicker(self) -> None:
        # A periodic refresh sets status FETCHING while the current image is
        # still cached -> keep showing the map, do NOT drop to LOADING.
        self.assertEqual(
            select_local_view(
                PlayerSurface.LOCAL, WorldMapStatus.FETCHING,
                has_current_image=True, is_empty=False,
            ),
            LOCAL_VIEW_MAP,
        )

    def test_transient_error_keeps_existing_map(self) -> None:
        # A transient error after we already have an image keeps showing it.
        self.assertEqual(
            select_local_view(
                PlayerSurface.LOCAL, WorldMapStatus.UNAVAILABLE,
                has_current_image=True, is_empty=False,
            ),
            LOCAL_VIEW_MAP,
        )


# ── F1: localLocation plumbs tile / elevation / map ───────────────────


class LocalLocationApplyTests(unittest.TestCase):
    def test_apply_local_location_stores_tile_elevation_map(self) -> None:
        client, state = _make_client(on_local=False)
        client._dispatch({
            "type": "update", "kind": "player.localLocation", "playerAvailable": True,
            "payload": {
                "tile": 12345, "elevation": 2, "map": 7,
                "location": "Vault 13", "locationId": "VAULT13",
            },
        })
        player = state.player
        self.assertEqual(player.surface, PlayerSurface.LOCAL)
        self.assertEqual(player.tile, 12345)
        self.assertEqual(player.elevation, 2)
        self.assertEqual(player.local_map_index, 7)
        self.assertEqual(player.location, "Vault 13")
        self.assertEqual(player.location_id, "VAULT13")

    def test_local_location_world_fields_set_world_fix(self) -> None:
        # TASK-013: worldX/worldY on localLocation give a world fix on a local
        # surface, so ATLAS/WORLD can mark the player immediately.
        client, state = _make_client(on_local=False)
        client._dispatch({
            "type": "update", "kind": "player.localLocation", "playerAvailable": True,
            "payload": {
                "tile": 100, "elevation": 0, "map": 6,
                "location": "Hub", "locationId": "HUB",
                "worldX": 620, "worldY": 380,
            },
        })
        self.assertTrue(state.has_world_fix)
        self.assertEqual(state.last_known_world_x, 620)
        self.assertEqual(state.last_known_world_y, 380)
        # The marker path is now satisfied on a LOCAL surface.
        self.assertEqual(
            select_marker_mode(state.player.surface, state.has_world_fix),
            MARKER_LAST_KNOWN,
        )

    def test_local_location_without_world_fields_preserves_state(self) -> None:
        # Older server: no worldX/worldY -> no fabricated fix, no crash.
        client, state = _make_client(on_local=False)
        client._dispatch({
            "type": "update", "kind": "player.localLocation", "playerAvailable": True,
            "payload": {
                "tile": 100, "elevation": 0, "map": 6,
                "location": "Hub", "locationId": "HUB",
            },
        })
        self.assertFalse(state.has_world_fix)
        self.assertEqual(
            select_marker_mode(state.player.surface, state.has_world_fix),
            MARKER_NONE,
        )


# ── F3: local-map fetch driver ─────────────────────────────────────────


class LocalMapFetchTests(unittest.TestCase):
    def test_start_fetch_on_local_ready(self) -> None:
        client, state = _make_client(map_index=5, elevation=1)
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.fetch_map, 5)
        self.assertEqual(state.local_map.fetch_elevation, 1)
        self.assertIn(b"getLocalMap", client._write_buf)

    def test_schema_below_6_unavailable(self) -> None:
        client, state = _make_client(schema_version=5)
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.UNAVAILABLE)
        self.assertNotIn(b"getLocalMap", client._write_buf)

    def test_no_fetch_on_world_surface(self) -> None:
        client, state = _make_client(on_local=False)
        state.player.surface = PlayerSurface.WORLD
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.IDLE)
        self.assertNotIn(b"getLocalMap", client._write_buf)

    def test_full_reassembly_and_identity(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        pixels = bytes([0, 1, 2, 0])
        palette = bytes(768)
        client._dispatch({
            "type": "localMapHeader", "map": 5, "elevation": 0,
            "width": 2, "height": 2, "paletteB64": _b64(palette),
            "chunkCount": 1, "chunkBytes": 4,
        })
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertIn(b"getLocalMapChunk", client._write_buf)
        client._dispatch({
            "type": "localMapChunk", "index": 0, "map": 5, "elevation": 0,
            "dataB64": _b64(pixels),
        })
        lm = state.local_map
        self.assertEqual(lm.status, WorldMapStatus.READY)
        self.assertEqual(lm.pixels, pixels)
        self.assertEqual(lm.map_index, 5)
        self.assertEqual(lm.elevation, 0)
        self.assertEqual(lm.image_tile, state.player.tile)

    def test_header_for_stale_target_is_ignored(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        client._write_buf.clear()
        # Header echoes a different map than the in-flight fetch target.
        client._dispatch({
            "type": "localMapHeader", "map": 9, "elevation": 0,
            "width": 2, "height": 2, "paletteB64": _b64(bytes(768)),
            "chunkCount": 1, "chunkBytes": 4,
        })
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.width, 0)  # header not applied
        self.assertNotIn(b"getLocalMapChunk", client._write_buf)

    def test_chunk_target_drift_restarts(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        client._dispatch({
            "type": "localMapHeader", "map": 5, "elevation": 0,
            "width": 4, "height": 1, "paletteB64": _b64(bytes(768)),
            "chunkCount": 2, "chunkBytes": 2,
        })
        client._write_buf.clear()
        # A chunk echoing a different map means the player moved mid-fetch.
        client._dispatch({
            "type": "localMapChunk", "index": 0, "map": 9, "elevation": 0,
            "dataB64": _b64(bytes([1, 2])),
        })
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.next_index, 0)  # reset
        self.assertIn(b"getLocalMap", client._write_buf)

    def test_local_map_error_unavailable(self) -> None:
        client, state = _make_client()
        client._tick_local_map_fetch()
        client._dispatch({"type": "localMapError", "reason": "noLocalMap"})
        self.assertEqual(state.local_map.status, WorldMapStatus.UNAVAILABLE)

    def test_unavailable_does_not_busyloop(self) -> None:
        # A first-fetch error must NOT re-request every frame (cached identity
        # stays the (-1,-1) sentinel; retry is gated by backoff instead).
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        client._dispatch({"type": "localMapError", "reason": "noLocalMap"})
        client._write_buf.clear()
        client._tick_local_map_fetch()  # same target, within backoff
        self.assertEqual(state.local_map.status, WorldMapStatus.UNAVAILABLE)
        self.assertNotIn(b"getLocalMap", client._write_buf)

    def test_unavailable_retries_after_backoff(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        client._dispatch({"type": "localMapError", "reason": "noLocalMap"})
        client._write_buf.clear()
        state.local_map.last_request_at = 0.0  # backoff elapsed
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertIn(b"getLocalMap", client._write_buf)

    def test_unavailable_retries_immediately_on_target_change(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        client._dispatch({"type": "localMapError", "reason": "noLocalMap"})
        client._write_buf.clear()
        state.player.local_map_index = 6  # moved, still within backoff
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.fetch_map, 6)
        self.assertIn(b"getLocalMap", client._write_buf)

    def _ready(self, client: NetworkClient, state: AppState) -> None:
        """Drive a fetch to READY for the player's current map/elevation."""
        client._tick_local_map_fetch()
        lm = state.local_map
        client._dispatch({
            "type": "localMapHeader", "map": lm.fetch_map, "elevation": lm.fetch_elevation,
            "width": 2, "height": 1, "paletteB64": _b64(bytes(768)),
            "chunkCount": 1, "chunkBytes": 2,
        })
        client._dispatch({
            "type": "localMapChunk", "index": 0,
            "map": lm.fetch_map, "elevation": lm.fetch_elevation,
            "dataB64": _b64(bytes([1, 2])),
        })
        assert state.local_map.status is WorldMapStatus.READY

    def test_refetch_on_map_change(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        self._ready(client, state)
        client._write_buf.clear()
        state.player.local_map_index = 6
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.fetch_map, 6)
        self.assertIn(b"getLocalMap", client._write_buf)

    def test_refetch_on_elevation_change(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        self._ready(client, state)
        client._write_buf.clear()
        state.player.elevation = 1
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.fetch_elevation, 1)

    def test_no_refetch_when_unchanged_and_recent(self) -> None:
        client, state = _make_client()
        self._ready(client, state)
        client._write_buf.clear()
        state.local_map.last_ready_at = time.monotonic()  # just now
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.READY)
        self.assertNotIn(b"getLocalMap", client._write_buf)

    def test_refresh_after_interval_and_move(self) -> None:
        client, state = _make_client(tile=20100)
        self._ready(client, state)
        client._write_buf.clear()
        # Interval elapsed AND the player moved since the image was captured.
        state.local_map.last_ready_at = 0.0
        state.local_map.image_tile = 10
        state.player.tile = 20
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertIn(b"getLocalMap", client._write_buf)

    def test_no_refresh_without_move(self) -> None:
        client, state = _make_client()
        self._ready(client, state)
        client._write_buf.clear()
        # Interval elapsed but the player has not moved since the last image.
        state.local_map.last_ready_at = 0.0
        state.local_map.image_tile = 20
        state.player.tile = 20
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.READY)
        self.assertNotIn(b"getLocalMap", client._write_buf)

    def test_inflight_target_change_restarts(self) -> None:
        client, state = _make_client(map_index=5, elevation=0)
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.fetch_map, 5)
        client._write_buf.clear()
        # Player moves to a new map while the fetch is still in flight.
        state.player.local_map_index = 7
        client._tick_local_map_fetch()
        self.assertEqual(state.local_map.status, WorldMapStatus.FETCHING)
        self.assertEqual(state.local_map.fetch_map, 7)
        self.assertIn(b"getLocalMap", client._write_buf)


if __name__ == "__main__":
    unittest.main()
