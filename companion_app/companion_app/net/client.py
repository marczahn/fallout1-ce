"""Non-blocking TCP client for the companion server (M3-T2).

Owns the socket lifecycle, the auth+handshake state machine, and the
dispatch of inbound messages into ``AppState``.
"""
from __future__ import annotations

import base64
import binascii
import errno
import os
import socket
import sys
import time
from typing import Any, Callable

from companion_app.net.framing import encode_line, read_line
from companion_app.state import (
    AppState,
    ConnectionState,
    LocalMapState,
    PlayerSurface,
    WorldMapState,
    WorldMapStatus,
)


RECONNECT_DELAY_SECONDS: float = 1.0

# Schema version that introduced the world-map wire protocol (getMap etc.).
MAP_MIN_SCHEMA_VERSION: int = 5
# Seconds to wait for a map reply before re-sending the outstanding request.
MAP_REQUEST_TIMEOUT_SECONDS: float = 5.0
# Re-sends before giving up and marking the map UNAVAILABLE.
MAP_MAX_RETRIES: int = 2
# 256 RGB triples.
MAP_PALETTE_BYTES: int = 768

# Schema version that introduced the local-map wire protocol (getLocalMap).
LOCAL_MAP_MIN_SCHEMA_VERSION: int = 6
# While on a LOCAL surface, re-fetch the (unchanged-map) automap at most this
# often to pick up newly explored tiles -- and only after the player moved.
LOCAL_MAP_REFRESH_SECONDS: float = 4.0


class NetworkClient:
    """Non-blocking TCP client for the companion server.

    Args:
        host: server hostname or IP.
        port: server TCP port.
        password: companion server auth password.
        state: shared ``AppState`` mutated by inbound messages.
    """

    def __init__(
        self,
        host: str,
        port: int,
        password: str,
        state: AppState,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self._host = host
        self._port = port
        self._password = password
        self._state = state
        self._log_fn = log_fn

        self._sock: socket.socket | None = None
        self._read_buf: bytearray = bytearray()
        self._write_buf: bytearray = bytearray()

        self._state.connection = ConnectionState.DISCONNECTED
        self._active: bool = True
        self._next_connect_at: float = 0.0

    # ── public API ────────────────────────────────────────────────

    def poll(self) -> None:
        """Drive the client lifecycle.

        Call once per frame from the main loop. Non-blocking.
        """
        if not self._active:
            return

        st = self._state.connection

        if st in (ConnectionState.DISCONNECTED, ConnectionState.RECONNECTING):
            if time.monotonic() < self._next_connect_at:
                return
            self._connect()
            return

        if self._sock is None:
            self._on_error("socket lost")
            return

        self._try_recv()
        self._flush_write()

        # After recv, check if the socket is still alive.
        if self._sock is None:
            return

        # Drive connection-completion for non-blocking connect.
        if st is ConnectionState.CONNECTING:
            self._check_connected()

        # Re-send a stalled map request (timeout-based, never busy-spins).
        self._tick_map_fetch()
        # Drive the local-map fetch: (re)start on map/elevation change or a
        # throttled refresh, and re-send stalled requests.
        self._tick_local_map_fetch()

    def cleanup(self) -> None:
        """Close the socket and reset the state to DISCONNECTED."""
        self._close_socket()
        self._state.connection = ConnectionState.DISCONNECTED
        self._next_connect_at = 0.0

    # ── connection lifecycle ──────────────────────────────────────

    def _connect(self) -> None:
        """Initiate a non-blocking TCP connection."""
        self._close_socket()
        self._read_buf.clear()
        self._write_buf.clear()

        sock: socket.socket | None = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            err = sock.connect_ex((self._host, self._port))
            if err != 0 and err != errno.EINPROGRESS:
                raise OSError(err, os.strerror(err))
            self._sock = sock
            self._state.connection = ConnectionState.CONNECTING
            self._log(f"connecting to {self._host}:{self._port}", visible=False)
        except OSError as e:
            if sock is not None:
                sock.close()
            self._log(f"connect failed: {e}", visible=False)
            self._schedule_reconnect(f"connect failed: {e}")

    def _check_connected(self) -> None:
        """Check if the non-blocking connect completed."""
        assert self._sock is not None
        try:
            socket_error = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        except AttributeError:
            socket_error = 0
        except OSError as e:
            self._schedule_reconnect(f"connect failed (getsockopt): {e}")
            return

        if socket_error in (errno.EINPROGRESS, errno.EALREADY, errno.EWOULDBLOCK, errno.ENOTCONN):
            return
        if socket_error != 0:
            self._schedule_reconnect(
                f"connect failed: {OSError(socket_error, os.strerror(socket_error))}"
            )
            return

        try:
            self._sock.getpeername()
        except OSError as e:
            err: int = e.args[0] if e.args else 0
            if err == errno.ENOTCONN:
                # Still connecting — try again next frame.
                return
            self._schedule_reconnect(f"connect failed (getpeername): {e}")
            return

        # Connected. Queue auth+hello together and flush immediately
        # (matching the working debug tool's blocking send behaviour).
        self._log("connected")
        self._queue_auth()
        self._queue_hello()
        self._state.connection = ConnectionState.AWAITING_WORLD
        self._log("sending auth")
        self._flush_write()
        self._log("sending hello")

    # ── send path ─────────────────────────────────────────────────

    def _queue_auth(self) -> None:
        self._queue_line({"type": "auth", "password": self._password})

    def _queue_hello(self) -> None:
        self._queue_line({"type": "hello"})

    def _queue_snapshot_request(self) -> None:
        self._queue_line({"type": "getSnapshot"})
        self._log("sending getSnapshot")

    def _queue_line(self, obj: dict[str, Any]) -> None:
        self._write_buf.extend(encode_line(obj))

    def _flush_write(self) -> None:
        """Drain the write buffer to the socket (non-blocking)."""
        if not self._write_buf or self._sock is None:
            return

        try:
            sent = self._sock.send(self._write_buf)
            self._write_buf = self._write_buf[sent:]
        except BlockingIOError:
            return
        except OSError as e:
            err: int = e.args[0] if e.args else 0
            if err in (errno.ENOTCONN, errno.EAGAIN):
                return
            self._on_error(f"send failed: {e}")
            return

    # ── recv path ─────────────────────────────────────────────────

    def _try_recv(self) -> None:
        """Read all data currently available from the socket.

        Drains the socket in a loop rather than a single read: world-map
        chunks are ~192 KB, so a single 4 KB read per frame would take dozens
        of frames per chunk (seconds to fetch the whole map). Looping until
        the socket would block keeps large transfers to a handful of frames
        while staying non-blocking.
        """
        if self._sock is None:
            return

        got_data = False
        while True:
            try:
                chunk = self._sock.recv(65536)
            except BlockingIOError:
                break
            except OSError as e:
                err: int = e.args[0] if e.args else 0
                if err in (errno.ENOTCONN, errno.EAGAIN):
                    break
                self._on_error(f"recv failed: {e}")
                return

            if not chunk:
                if got_data:
                    # Process what we read before reporting the close.
                    self._process_read_buffer()
                self._on_error("connection closed by peer")
                return

            self._read_buf.extend(chunk)
            got_data = True

        if got_data:
            self._process_read_buffer()

    def _process_read_buffer(self) -> None:
        """Split the read buffer on newlines and dispatch messages."""
        while True:
            msg, self._read_buf = read_line(self._read_buf)
            if msg is None:
                break
            self._dispatch(msg)

    # ── dispatch ──────────────────────────────────────────────────

    def _dispatch(self, msg: dict[str, Any]) -> None:
        """Route a parsed JSON message by its ``type`` field."""
        msg_type = msg.get("type")
        if not isinstance(msg_type, str):
            self._log("ignoring message without type")
            return

        if msg_type == "world":
            self._on_world(msg)
        elif msg_type == "snapshot":
            self._on_snapshot(msg)
        elif msg_type == "update":
            self._on_update(msg)
        elif msg_type == "onPlayerUnavailable":
            self._handle_player_unavailable()
        elif msg_type == "onPlayerAvailable":
            self._handle_player_available()
        elif msg_type == "mapHeader":
            self._on_map_header(msg)
        elif msg_type == "mapChunk":
            self._on_map_chunk(msg)
        elif msg_type == "mapError":
            self._on_map_error(msg)
        elif msg_type == "localMapHeader":
            self._on_local_map_header(msg)
        elif msg_type == "localMapChunk":
            self._on_local_map_chunk(msg)
        elif msg_type == "localMapError":
            self._on_local_map_error(msg)
        elif msg_type == "alreadyConnected":
            self._log("server: another client is already connected")
            self._on_error("another client is already connected")
        else:
            self._log(f"ignoring unknown message type {msg_type!r}")

    def _on_world(self, msg: dict[str, Any]) -> None:
        if self._state.connection is not ConnectionState.AWAITING_WORLD:
            return

        from companion_app.state import WorldInfo

        sv = msg.get("schemaVersion", 0)
        game = msg.get("game", "")
        pa = bool(msg.get("playerAvailable", False))

        self._state.world = WorldInfo(
            schema_version=sv,
            game=game,
            player_available=pa,
        )
        # `world.playerAvailable` is the authoritative handshake-time
        # availability. After handshake, `onPlayerAvailable` and
        # `onPlayerUnavailable` carry transitions. The snapshot's
        # `playerAvailable` field is informational only (truth at
        # request time) and is not used to set `player.available`.
        self._state.player.available = pa
        self._log(f"world (v{sv}, game={game}, playerAvailable={pa})")
        self._log("requesting snapshot")
        self._queue_snapshot_request()
        self._state.connection = ConnectionState.AWAITING_SNAPSHOT

    def _on_snapshot(self, msg: dict[str, Any]) -> None:
        if self._state.connection is not ConnectionState.AWAITING_SNAPSHOT:
            return

        # Events are authoritative for `player.available`. The snapshot's
        # `playerAvailable` field is informational (truth at request time)
        # and is intentionally not applied here -- if an unavailable
        # event raced a pending snapshot reply, the snapshot's flag would
        # otherwise re-flip availability to the request-time value.
        payload = msg.get("payload", {}) or {}
        self._apply_snapshot_payload(payload)

        self._state.connection = ConnectionState.READY
        self._log(f"snapshot (hp={self._state.player.hp}/{self._state.player.max_hp})")

        self._maybe_start_map_fetch()

    def _on_update(self, msg: dict[str, Any]) -> None:
        pa = msg.get("playerAvailable", True)
        if not isinstance(pa, bool):
            pa = True
        self._state.player.available = pa

        if not pa:
            return

        kind = msg.get("kind")
        if kind == "player.vitals":
            self._apply_vitals(msg.get("payload", {}) or {})
            self._state.player.available = True
            self._log(f"update: hp={self._state.player.hp}/{self._state.player.max_hp}")
        elif kind == "player.status":
            self._apply_status(msg.get("payload", {}) or {})
            self._log("update: player.status")
        elif kind == "player.special":
            self._apply_special(msg.get("payload", {}) or {})
            self._log("update: player.special")
        elif kind == "player.progression":
            self._apply_progression(msg.get("payload", {}) or {})
            self._log("update: player.progression")
        elif kind == "player.localLocation":
            self._apply_local_location(msg.get("payload", {}) or {})
            self._log("update: player.localLocation")
        elif kind == "player.worldLocation":
            self._apply_world_location(msg.get("payload", {}) or {})
            self._log("update: player.worldLocation")
        elif kind == "player.inventory":
            self._apply_inventory(msg.get("payload", []) or [])
            self._log("update: player.inventory")
        elif kind is None:
            pass
        else:
            self._log(f"ignoring update: unknown kind {kind!r}")

    def _handle_player_unavailable(self) -> None:
        self._state.player.available = False
        self._log("player unavailable")

    def _handle_player_available(self) -> None:
        self._state.player.available = True
        self._log("player became available, requesting snapshot")
        self._queue_snapshot_request()
        self._state.connection = ConnectionState.AWAITING_SNAPSHOT

    # ── world-map fetch ────────────────────────────────────────────

    def _maybe_start_map_fetch(self) -> None:
        """Kick off the map fetch once per connection on entering READY."""
        world = self._state.world
        schema = world.schema_version if world is not None else 0
        wm = self._state.world_map

        if schema < MAP_MIN_SCHEMA_VERSION:
            if wm.status is WorldMapStatus.IDLE:
                wm.status = WorldMapStatus.UNAVAILABLE
                self._log(f"map unavailable (server schemaVersion {schema} < {MAP_MIN_SCHEMA_VERSION})")
            return

        if wm.status is not WorldMapStatus.IDLE:
            return

        wm.status = WorldMapStatus.FETCHING
        wm.retries = 0
        wm.last_request_at = time.monotonic()
        self._queue_line({"type": "getMap"})
        self._log("map: requesting getMap")

    def _on_map_header(self, msg: dict[str, Any]) -> None:
        wm = self._state.world_map
        if wm.status is not WorldMapStatus.FETCHING:
            return

        width = int(msg.get("width", 0))
        height = int(msg.get("height", 0))
        chunk_count = int(msg.get("chunkCount", 0))
        chunk_bytes = int(msg.get("chunkBytes", 0))

        try:
            palette = base64.b64decode(msg.get("paletteB64", ""), validate=True)
        except (binascii.Error, ValueError):
            self._fail_map("invalid paletteB64")
            return

        if len(palette) != MAP_PALETTE_BYTES:
            self._fail_map(f"bad palette length {len(palette)} (expected {MAP_PALETTE_BYTES})")
            return
        if width <= 0 or height <= 0 or chunk_count <= 0 or chunk_bytes <= 0:
            self._fail_map("bad map header dimensions")
            return

        wm.width = width
        wm.height = height
        wm.palette = palette
        wm.chunk_count = chunk_count
        wm.chunk_bytes = chunk_bytes
        wm.accumulator = bytearray()
        wm.next_index = 0
        wm.retries = 0
        wm.last_request_at = time.monotonic()
        self._log(f"map: header {width}x{height}, {chunk_count} chunks")
        self._request_map_chunk(0)

    def _on_map_chunk(self, msg: dict[str, Any]) -> None:
        wm = self._state.world_map
        if wm.status is not WorldMapStatus.FETCHING:
            return

        index = int(msg.get("index", -1))
        if index != wm.next_index:
            # Out-of-order / stale chunk: ignore and let the timeout re-request.
            self._log(f"map: ignoring chunk {index} (expected {wm.next_index})")
            return

        try:
            data = base64.b64decode(msg.get("dataB64", ""), validate=True)
        except (binascii.Error, ValueError):
            self._fail_map("invalid dataB64")
            return

        wm.accumulator.extend(data)
        wm.next_index += 1
        wm.retries = 0

        if wm.next_index < wm.chunk_count:
            wm.last_request_at = time.monotonic()
            self._request_map_chunk(wm.next_index)
            return

        expected = wm.width * wm.height
        if len(wm.accumulator) != expected:
            self._fail_map(
                f"reassembled {len(wm.accumulator)} bytes (expected {expected})"
            )
            return

        wm.pixels = bytes(wm.accumulator)
        wm.accumulator = bytearray()
        wm.status = WorldMapStatus.READY
        self._log(f"map: ready ({len(wm.pixels)} px)")

    def _on_map_error(self, msg: dict[str, Any]) -> None:
        wm = self._state.world_map
        if wm.status is not WorldMapStatus.FETCHING:
            return
        reason = msg.get("reason", "?")
        self._fail_map(f"server mapError: {reason}")

    def _request_map_chunk(self, index: int) -> None:
        self._queue_line({"type": "getMapChunk", "index": index})

    def _fail_map(self, reason: str) -> None:
        self._state.world_map.status = WorldMapStatus.UNAVAILABLE
        self._log(f"map unavailable: {reason}")

    def _tick_map_fetch(self) -> None:
        """Re-send a stalled outstanding map request, or give up."""
        wm = self._state.world_map
        if wm.status is not WorldMapStatus.FETCHING:
            return
        if time.monotonic() - wm.last_request_at <= MAP_REQUEST_TIMEOUT_SECONDS:
            return

        if wm.retries >= MAP_MAX_RETRIES:
            self._fail_map("fetch timed out (retries exhausted)")
            return

        wm.retries += 1
        wm.last_request_at = time.monotonic()
        if wm.chunk_count == 0:
            # No header yet: re-request the whole map.
            self._queue_line({"type": "getMap"})
            self._log(f"map: re-requesting getMap (retry {wm.retries})")
        else:
            self._request_map_chunk(wm.next_index)
            self._log(f"map: re-requesting chunk {wm.next_index} (retry {wm.retries})")

    # ── local-map fetch ────────────────────────────────────────────

    def _tick_local_map_fetch(self) -> None:
        """Drive the local-map fetch for the player's current map+elevation.

        Unlike the once-per-connection world map, the local map is re-fetched
        when the player's ``(map, elevation)`` changes and, while unchanged,
        on a throttled interval after the player has moved (to pick up newly
        explored tiles). Cancels and restarts an in-flight fetch if the target
        changes mid-fetch.
        """
        if self._state.connection is not ConnectionState.READY:
            return

        player = self._state.player
        # The local map is only meaningful on a LOCAL surface; on the world
        # map the LOCAL view shows "ON WORLD MAP" and no fetch runs.
        if player.surface is not PlayerSurface.LOCAL:
            return

        lm = self._state.local_map
        world = self._state.world
        schema = world.schema_version if world is not None else 0
        if schema < LOCAL_MAP_MIN_SCHEMA_VERSION:
            if lm.status is WorldMapStatus.IDLE:
                lm.status = WorldMapStatus.UNAVAILABLE
                self._log(
                    f"local map unavailable (server schemaVersion {schema} "
                    f"< {LOCAL_MAP_MIN_SCHEMA_VERSION})"
                )
            return

        target = (player.local_map_index, player.elevation)

        if lm.status is WorldMapStatus.FETCHING:
            if (lm.fetch_map, lm.fetch_elevation) != target:
                # Player changed map/elevation mid-fetch: restart for the new
                # target rather than finishing a now-stale image.
                self._start_local_map_fetch()
            else:
                self._tick_local_map_timeout()
            return

        now = time.monotonic()
        cached = (lm.map_index, lm.elevation)

        if lm.status is WorldMapStatus.READY:
            if cached != target:
                self._start_local_map_fetch()
            elif (
                now - lm.last_ready_at >= LOCAL_MAP_REFRESH_SECONDS
                and player.tile != lm.image_tile
            ):
                self._start_local_map_fetch()
            return

        if lm.status is WorldMapStatus.UNAVAILABLE:
            # Recover from a transient error (e.g. a race that produced
            # localMapError). Retry immediately if the player has moved to a
            # different map/elevation than the failed attempt; otherwise back
            # off by the refresh interval so a persistently-failing fetch does
            # NOT busy-loop sending getLocalMap every frame. Keyed off the last
            # *attempt* (fetch_map/elevation), not the last *success* (cached),
            # which stays the sentinel (-1,-1) when no fetch ever succeeded.
            last_attempt = (lm.fetch_map, lm.fetch_elevation)
            if (
                last_attempt != target
                or now - lm.last_request_at >= LOCAL_MAP_REFRESH_SECONDS
            ):
                self._start_local_map_fetch()
            return

        # IDLE: first fetch on this connection while on a local map.
        self._start_local_map_fetch()

    def _start_local_map_fetch(self) -> None:
        lm = self._state.local_map
        player = self._state.player
        lm.status = WorldMapStatus.FETCHING
        lm.fetch_map = player.local_map_index
        lm.fetch_elevation = player.elevation
        lm.chunk_count = 0
        lm.next_index = 0
        lm.accumulator = bytearray()
        lm.retries = 0
        lm.last_request_at = time.monotonic()
        self._queue_line({"type": "getLocalMap"})
        self._log(
            f"localmap: requesting getLocalMap (map={lm.fetch_map} elev={lm.fetch_elevation})"
        )

    def _on_local_map_header(self, msg: dict[str, Any]) -> None:
        lm = self._state.local_map
        if lm.status is not WorldMapStatus.FETCHING:
            return

        hdr_map = int(msg.get("map", -1))
        hdr_elevation = int(msg.get("elevation", -1))
        # The server serves the player's current map+elevation. Accept the
        # header only if it still matches the target we requested; otherwise
        # the player moved -- ignore and let the tick restart for the right
        # target. The chunks are then validated against this same identity.
        if (hdr_map, hdr_elevation) != (lm.fetch_map, lm.fetch_elevation):
            self._log(
                f"localmap: ignoring header for {hdr_map}/{hdr_elevation} "
                f"(want {lm.fetch_map}/{lm.fetch_elevation})"
            )
            return

        width = int(msg.get("width", 0))
        height = int(msg.get("height", 0))
        chunk_count = int(msg.get("chunkCount", 0))
        chunk_bytes = int(msg.get("chunkBytes", 0))

        try:
            palette = base64.b64decode(msg.get("paletteB64", ""), validate=True)
        except (binascii.Error, ValueError):
            self._fail_local_map("invalid paletteB64")
            return

        if len(palette) != MAP_PALETTE_BYTES:
            self._fail_local_map(
                f"bad palette length {len(palette)} (expected {MAP_PALETTE_BYTES})"
            )
            return
        if width <= 0 or height <= 0 or chunk_count <= 0 or chunk_bytes <= 0:
            self._fail_local_map("bad local map header dimensions")
            return

        lm.width = width
        lm.height = height
        lm.palette = palette
        lm.chunk_count = chunk_count
        lm.chunk_bytes = chunk_bytes
        lm.accumulator = bytearray()
        lm.next_index = 0
        lm.retries = 0
        lm.last_request_at = time.monotonic()
        self._log(f"localmap: header {width}x{height}, {chunk_count} chunks")
        self._request_local_map_chunk(0)

    def _on_local_map_chunk(self, msg: dict[str, Any]) -> None:
        lm = self._state.local_map
        if lm.status is not WorldMapStatus.FETCHING:
            return

        # Coherence: the server re-scans per chunk request, so a chunk that
        # echoes a different map/elevation than the in-flight header means the
        # player moved -- restart the fetch for the current target.
        chunk_map = int(msg.get("map", -1))
        chunk_elevation = int(msg.get("elevation", -1))
        if (chunk_map, chunk_elevation) != (lm.fetch_map, lm.fetch_elevation):
            self._log(
                f"localmap: chunk target drift {chunk_map}/{chunk_elevation} "
                f"!= {lm.fetch_map}/{lm.fetch_elevation}; restarting"
            )
            self._start_local_map_fetch()
            return

        index = int(msg.get("index", -1))
        if index != lm.next_index:
            self._log(f"localmap: ignoring chunk {index} (expected {lm.next_index})")
            return

        try:
            data = base64.b64decode(msg.get("dataB64", ""), validate=True)
        except (binascii.Error, ValueError):
            self._fail_local_map("invalid dataB64")
            return

        lm.accumulator.extend(data)
        lm.next_index += 1
        lm.retries = 0

        if lm.next_index < lm.chunk_count:
            lm.last_request_at = time.monotonic()
            self._request_local_map_chunk(lm.next_index)
            return

        expected = lm.width * lm.height
        if len(lm.accumulator) != expected:
            self._fail_local_map(
                f"reassembled {len(lm.accumulator)} bytes (expected {expected})"
            )
            return

        lm.pixels = bytes(lm.accumulator)
        lm.accumulator = bytearray()
        lm.map_index = lm.fetch_map
        lm.elevation = lm.fetch_elevation
        lm.status = WorldMapStatus.READY
        lm.last_ready_at = time.monotonic()
        lm.image_tile = self._state.player.tile
        self._log(f"localmap: ready ({len(lm.pixels)} px, map={lm.map_index})")

    def _on_local_map_error(self, msg: dict[str, Any]) -> None:
        lm = self._state.local_map
        if lm.status is not WorldMapStatus.FETCHING:
            return
        reason = msg.get("reason", "?")
        self._fail_local_map(f"server localMapError: {reason}")

    def _request_local_map_chunk(self, index: int) -> None:
        self._queue_line({"type": "getLocalMapChunk", "index": index})

    def _fail_local_map(self, reason: str) -> None:
        self._state.local_map.status = WorldMapStatus.UNAVAILABLE
        self._log(f"local map unavailable: {reason}")

    def _tick_local_map_timeout(self) -> None:
        """Re-send a stalled outstanding local-map request, or give up."""
        lm = self._state.local_map
        if lm.status is not WorldMapStatus.FETCHING:
            return
        if time.monotonic() - lm.last_request_at <= MAP_REQUEST_TIMEOUT_SECONDS:
            return

        if lm.retries >= MAP_MAX_RETRIES:
            self._fail_local_map("fetch timed out (retries exhausted)")
            return

        lm.retries += 1
        lm.last_request_at = time.monotonic()
        if lm.chunk_count == 0:
            self._queue_line({"type": "getLocalMap"})
            self._log(f"localmap: re-requesting getLocalMap (retry {lm.retries})")
        else:
            self._request_local_map_chunk(lm.next_index)
            self._log(
                f"localmap: re-requesting chunk {lm.next_index} (retry {lm.retries})"
            )

    # ── reconnection ───────────────────────────────────────────────

    def _schedule_reconnect(self, reason: str) -> None:
        self._log(f"error: {reason}", visible=False)
        self._close_socket()
        self._state.connection = ConnectionState.RECONNECTING
        self._next_connect_at = time.monotonic() + RECONNECT_DELAY_SECONDS

    def _on_error(self, reason: str) -> None:
        self._schedule_reconnect(reason)

    def _log(self, msg: str, *, visible: bool = True) -> None:
        print(f"companion_app: {msg}", file=sys.stderr)
        if visible and self._log_fn is not None:
            self._log_fn(msg)

    # ── helpers ───────────────────────────────────────────────────

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        self._read_buf.clear()
        self._write_buf.clear()
        # A reconnect must refetch the map from scratch: reset to a fresh
        # IDLE state. (last_known_world_* is left alone -- preserving it
        # across reconnect is not required, but resetting it is not either.)
        self._state.world_map = WorldMapState()
        self._state.local_map = LocalMapState()

    def _apply_snapshot_payload(self, payload: dict[str, Any]) -> None:
        vitals = payload.get("player.vitals", {}) or {}
        status = payload.get("player.status", {}) or {}
        special = payload.get("player.special", {}) or {}
        progression = payload.get("player.progression", {}) or {}
        local_location = payload.get("player.localLocation", {}) or {}
        world_location = payload.get("player.worldLocation", {}) or {}
        inventory = payload.get("player.inventory", []) or []

        if vitals:
            self._apply_vitals(vitals)
        if status:
            self._apply_status(status)
        if special:
            self._apply_special(special)
        if progression:
            self._apply_progression(progression)
        if local_location:
            self._apply_local_location(local_location)
        elif world_location:
            self._apply_world_location(world_location)
        self._apply_inventory(inventory)

    def _apply_vitals(self, payload: dict[str, Any]) -> None:
        self._state.player.hp = int(payload.get("hp", self._state.player.hp))
        self._state.player.max_hp = int(payload.get("maxHp", self._state.player.max_hp))

    def _apply_status(self, payload: dict[str, Any]) -> None:
        self._state.player.armor_class = int(
            payload.get("armorClass", self._state.player.armor_class)
        )
        self._state.player.current_carry_weight = int(
            payload.get("currentCarryWeight", self._state.player.current_carry_weight)
        )
        self._state.player.carry_weight = int(
            payload.get("carryWeight", self._state.player.carry_weight)
        )
        self._state.player.melee_damage = int(
            payload.get("meleeDamage", self._state.player.melee_damage)
        )
        self._state.player.damage_resistance = int(
            payload.get("damageResistance", self._state.player.damage_resistance)
        )
        self._state.player.radiation = int(
            payload.get("radiation", self._state.player.radiation)
        )
        self._state.player.poison = int(payload.get("poison", self._state.player.poison))

    def _apply_special(self, payload: dict[str, Any]) -> None:
        self._state.player.strength = int(payload.get("strength", self._state.player.strength))
        self._state.player.perception = int(
            payload.get("perception", self._state.player.perception)
        )
        self._state.player.endurance = int(payload.get("endurance", self._state.player.endurance))
        self._state.player.charisma = int(payload.get("charisma", self._state.player.charisma))
        self._state.player.intelligence = int(
            payload.get("intelligence", self._state.player.intelligence)
        )
        self._state.player.agility = int(payload.get("agility", self._state.player.agility))
        self._state.player.luck = int(payload.get("luck", self._state.player.luck))

    def _apply_progression(self, payload: dict[str, Any]) -> None:
        self._state.player.level = int(payload.get("level", self._state.player.level))
        self._state.player.experience = int(
            payload.get("experience", self._state.player.experience)
        )
        self._state.player.next_level_exp = int(
            payload.get("nextLevelExp", self._state.player.next_level_exp)
        )

    def _apply_inventory(self, payload: list[dict[str, Any]]) -> None:
        from companion_app.state import InventoryItem

        items: list[InventoryItem] = []
        for raw_item in payload:
            if not isinstance(raw_item, dict):
                continue
            items.append(
                InventoryItem(
                    pid=int(raw_item.get("pid", 0)),
                    proto_id=str(raw_item.get("protoId", "")),
                    name=str(raw_item.get("name", "")),
                    item_type=str(raw_item.get("type", "")),
                    count=int(raw_item.get("count", 0)),
                    slot=str(raw_item.get("slot", "none")),
                )
            )
        self._state.player.inventory = items

    def _apply_local_location(self, payload: dict[str, Any]) -> None:
        self._state.player.surface = PlayerSurface.LOCAL
        self._state.player.location = str(payload.get("location", self._state.player.location))
        self._state.player.location_id = str(
            payload.get("locationId", self._state.player.location_id)
        )
        self._state.player.world_x = 0
        self._state.player.world_y = 0
        # Local-map position (drives the LOCAL map render + its fetch driver).
        self._state.player.tile = int(payload.get("tile", self._state.player.tile))
        self._state.player.elevation = int(
            payload.get("elevation", self._state.player.elevation)
        )
        self._state.player.local_map_index = int(
            payload.get("map", self._state.player.local_map_index)
        )
        # The server reports the overworld position even on a local surface
        # (schema 7+). When present, record it as the world fix so ATLAS/WORLD
        # can place the marker immediately on connect in a town. The fields are
        # optional: an older server omits them and prior behavior is preserved.
        world_x = payload.get("worldX")
        world_y = payload.get("worldY")
        if world_x is not None and world_y is not None:
            self._state.last_known_world_x = int(world_x)
            self._state.last_known_world_y = int(world_y)
            self._state.has_world_fix = True

    def _apply_world_location(self, payload: dict[str, Any]) -> None:
        self._state.player.surface = PlayerSurface.WORLD
        self._state.player.location = ""
        self._state.player.location_id = ""
        self._state.player.world_x = int(payload.get("x", self._state.player.world_x))
        self._state.player.world_y = int(payload.get("y", self._state.player.world_y))
        # Remember the most recent world position so the map can show a
        # "LAST KNOWN" marker after the player drops to a LOCAL surface.
        self._state.last_known_world_x = self._state.player.world_x
        self._state.last_known_world_y = self._state.player.world_y
        self._state.has_world_fix = True
