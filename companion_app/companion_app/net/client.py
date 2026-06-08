"""Non-blocking TCP client for the companion server (M3-T2).

Owns the socket lifecycle, the auth+handshake state machine, and the
dispatch of inbound messages into ``AppState``.
"""
from __future__ import annotations

import errno
import os
import socket
import sys
from typing import Any, Callable

from companion_app.net.framing import encode_line, read_line
from companion_app.state import AppState, ConnectionState





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
        self._active: bool = True  # False = terminal error, no reconnect

    # ── public API ────────────────────────────────────────────────

    def poll(self) -> None:
        """Drive the client lifecycle.

        Call once per frame from the main loop. Non-blocking.
        """
        if not self._active:
            return

        st = self._state.connection

        if st is ConnectionState.DISCONNECTED:
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

    def cleanup(self) -> None:
        """Close the socket and reset the state to DISCONNECTED."""
        self._close_socket()
        self._state.connection = ConnectionState.DISCONNECTED

    # ── connection lifecycle ──────────────────────────────────────

    def _connect(self) -> None:
        """Initiate a non-blocking TCP connection."""
        self._close_socket()
        self._read_buf.clear()
        self._write_buf.clear()

        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setblocking(False)
            err = sock.connect_ex((self._host, self._port))
            if err != 0 and err != errno.EINPROGRESS:
                raise OSError(err, os.strerror(err))
            self._sock = sock
            self._state.connection = ConnectionState.CONNECTING
            self._log(f"connecting to {self._host}:{self._port}")
        except OSError as e:
            sock.close()
            self._log(f"connect failed: {e}")
            self._on_error(f"connect failed: {e}")

    def _check_connected(self) -> None:
        """Check if the non-blocking connect completed."""
        assert self._sock is not None
        try:
            self._sock.getpeername()
        except OSError as e:
            err: int = e.args[0] if e.args else 0
            if err == errno.ENOTCONN:
                # Still connecting — try again next frame.
                return
            self._on_error(f"connect failed (getpeername): {e}")
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

    def _queue_get_snapshot(self) -> None:
        self._queue_line({"type": "get_snapshot"})
        self._log("sending get_snapshot")

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
        """Read available data from the socket."""
        if self._sock is None:
            return

        try:
            chunk = self._sock.recv(4096)
        except BlockingIOError:
            return
        except OSError as e:
            err: int = e.args[0] if e.args else 0
            if err in (errno.ENOTCONN, errno.EAGAIN):
                return
            self._on_error(f"recv failed: {e}")
            return

        if not chunk:
            self._on_error("connection closed by peer")
            return

        self._read_buf.extend(chunk)
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
        elif msg_type == "player_unavailable":
            self._on_player_unavailable()
        elif msg_type == "already_connected":
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
        self._log(f"world (v{sv}, game={game})")
        self._log("requesting snapshot")
        self._queue_get_snapshot()
        self._state.connection = ConnectionState.AWAITING_SNAPSHOT

    def _on_snapshot(self, msg: dict[str, Any]) -> None:
        if self._state.connection is not ConnectionState.AWAITING_SNAPSHOT:
            return

        pa = bool(msg.get("playerAvailable", False))
        self._state.player.available = pa

        if pa:
            payload = msg.get("payload", {})
            vitals = payload.get("player.vitals", {})
            self._state.player.hp = int(vitals.get("hp", 0))
            self._state.player.max_hp = int(vitals.get("maxHp", 0))

        self._state.connection = ConnectionState.READY
        self._log(f"snapshot (hp={self._state.player.hp}/{self._state.player.max_hp})")

    def _on_update(self, msg: dict[str, Any]) -> None:
        pa = msg.get("playerAvailable", True)
        if not isinstance(pa, bool):
            pa = True
        self._state.player.available = pa

        if not pa:
            return

        kind = msg.get("kind")
        if kind == "player.vitals":
            payload = msg.get("payload", {})
            self._state.player.hp = int(payload.get("hp", self._state.player.hp))
            self._state.player.max_hp = int(
                payload.get("maxHp", self._state.player.max_hp)
            )
            self._state.player.available = True
            self._log(f"update: hp={self._state.player.hp}/{self._state.player.max_hp}")
        elif kind is None:
            pass
        else:
            self._log(f"ignoring update: unknown kind {kind!r}")

    def _on_player_unavailable(self) -> None:
        self._state.player.available = False
        self._log("player unavailable")

    # ── reconnection (disabled for now) ────────────────────────────

    def _schedule_reconnect(self) -> None:
        self._close_socket()
        self._state.connection = ConnectionState.DISCONNECTED
        self._log("reconnect disabled, giving up")

    def _on_error(self, reason: str) -> None:
        self._log(f"error: {reason}")
        self._close_socket()
        self._state.connection = ConnectionState.DISCONNECTED
        self._active = False

    def _log(self, msg: str) -> None:
        print(f"companion_app: {msg}", file=sys.stderr)
        if self._log_fn is not None:
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
