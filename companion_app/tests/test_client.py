"""Unit tests for the NetworkClient (M3-T2).

Uses mock sockets to test state machine transitions, message dispatch,
and reconnection logic in isolation.
"""
from __future__ import annotations

import socket
import unittest
from unittest.mock import MagicMock, patch

from companion_app.net.client import NetworkClient
from companion_app.state import AppState, ConnectionState, WorldInfo


class _FakeSocket:
    """Simulates a non-blocking socket for testing NetworkClient."""

    def __init__(self) -> None:
        self.sendbuf = bytearray()
        self.recvbuf = bytearray()
        self._closed = False
        self._connected = False
        self.family = 0
        self.type = 0
        self.proto = 0

    def setblocking(self, flag: bool) -> None:
        pass

    def connect_ex(self, address: tuple[str, int]) -> int:
        self._connected = True
        return 0  # success, not EINPROGRESS

    def getpeername(self) -> tuple[str, int]:
        if not self._connected:
            raise OSError("not connected")
        return ("127.0.0.1", 28080)

    def send(self, data: bytes) -> int:
        if not self._connected:
            raise OSError("socket not connected")
        self.sendbuf.extend(data)
        return len(data)

    def recv(self, bufsize: int) -> bytes:
        if not self._connected:
            raise OSError("socket not connected")
        if not self.recvbuf:
            return b""
        chunk = self.recvbuf[:bufsize]
        self.recvbuf = self.recvbuf[bufsize:]
        return bytes(chunk)

    def close(self) -> None:
        self._closed = True
        self._connected = False

    def fileno(self) -> int:
        return -1

    def detach(self) -> int:
        return -1


class NetworkClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AppState()
        self.client = NetworkClient(
            host="127.0.0.1",
            port=28080,
            password="testpw",
            state=self.state,
        )

    def assert_connection(self, expected: ConnectionState) -> None:
        self.assertEqual(self.state.connection, expected)

    # ── initial state ─────────────────────────────────────────────

    def test_initial_state_disconnected(self) -> None:
        self.assert_connection(ConnectionState.DISCONNECTED)

    def test_poll_disconnected_starts_connecting(self) -> None:
        # poll() transitions from DISCONNECTED to CONNECTING by
        # initiating a non-blocking TCP connection.
        self.client.poll()
        # The connect will fail (no server), but the state should no
        # longer be DISCONNECTED — it's either CONNECTING or, if the
        # connect failed immediately (e.g. ECONNREFUSED because no
        # server is listening), RECONNECTING.
        self.assertNotEqual(self.state.connection, ConnectionState.DISCONNECTED)

    # ── connection lifecycle ──────────────────────────────────────

    @patch("companion_app.net.client.socket")
    def test_connect_success(self, mock_socket_module: MagicMock) -> None:
        fake = _FakeSocket()
        mock_socket_module.socket.return_value = fake
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM

        self.client._connect()
        self.assert_connection(ConnectionState.CONNECTING)

    @patch("companion_app.net.client.socket")
    def test_full_handshake(self, mock_socket_module: MagicMock) -> None:
        fake = _FakeSocket()
        mock_socket_module.socket.return_value = fake
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM

        # Trigger connect.
        self.client._connect()

        # Check connected → queues auth+hello together, transitions to
        # AWAITING_WORLD, and flushes immediately (matching the working
        # debug tool's behaviour).  The write buffer may be empty if the
        # mock accepted all bytes in one shot.
        self.client._check_connected()
        self.assert_connection(ConnectionState.AWAITING_WORLD)
        # Both auth+hello were queued and flushed in _check_connected().
        # Verify that both messages reached the socket.
        sent = self.client._sock.sendbuf  # _FakeSocket accumulates written bytes
        self.assertIn(b"auth", sent)
        self.assertIn(b"hello", sent)

        # Simulate server sending world.
        self.client._write_buf.clear()
        fake.sendbuf.clear()
        fake.recvbuf = bytearray(
            b'{"type":"world","schemaVersion":3,"game":"fallout1-ce",'
            b'"playerAvailable":true}\n'
        )
        self.client._try_recv()
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertIsNotNone(self.state.world)
        self.assertEqual(self.state.world.schema_version, 3)
        self.assertEqual(self.state.world.game, "fallout1-ce")
        self.assertTrue(self.state.world.player_available)
        # get_snapshot should be queued in the internal write buffer.
        self.assertIn(b"get_snapshot", self.client._write_buf)

        # Simulate server sending snapshot.
        self.client._write_buf.clear()
        fake.sendbuf.clear()
        fake.recvbuf = bytearray(
            b'{"type":"snapshot","seq":1,"playerAvailable":true,'
            b'"payload":{"player.vitals":{"hp":30,"maxHp":40}}}\n'
        )
        self.client._try_recv()
        self.assert_connection(ConnectionState.READY)
        self.assertTrue(self.state.player.available)
        self.assertEqual(self.state.player.hp, 30)
        self.assertEqual(self.state.player.max_hp, 40)

    # ── dispatch tests (unit, no socket) ──────────────────────────

    def test_world_dispatch(self) -> None:
        self.state.connection = ConnectionState.AWAITING_WORLD
        self.client._on_world({
            "type": "world",
            "schemaVersion": 3,
            "game": "fallout1-ce",
            "playerAvailable": True,
        })
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertEqual(self.state.world.schema_version, 3)
        self.assertEqual(self.state.world.game, "fallout1-ce")

    def test_snapshot_dispatch_with_player(self) -> None:
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.client._on_snapshot({
            "type": "snapshot",
            "playerAvailable": True,
            "payload": {
                "player.vitals": {"hp": 30, "maxHp": 40},
            },
        })
        self.assert_connection(ConnectionState.READY)
        self.assertTrue(self.state.player.available)
        self.assertEqual(self.state.player.hp, 30)
        self.assertEqual(self.state.player.max_hp, 40)

    def test_snapshot_dispatch_without_player(self) -> None:
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.client._on_snapshot({
            "type": "snapshot",
            "playerAvailable": False,
            "payload": {},
        })
        self.assert_connection(ConnectionState.READY)
        self.assertFalse(self.state.player.available)

    def test_update_vitals(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True
        self.state.player.hp = 30
        self.state.player.max_hp = 40

        self.client._on_update({
            "type": "update",
            "kind": "player.vitals",
            "playerAvailable": True,
            "payload": {"hp": 28, "maxHp": 40},
        })
        self.assertEqual(self.state.player.hp, 28)
        self.assertEqual(self.state.player.max_hp, 40)
        self.assertTrue(self.state.player.available)

    def test_player_unavailable(self) -> None:
        self.state.player.available = True
        self.client._on_player_unavailable()
        self.assertFalse(self.state.player.available)

    def test_update_unknown_kind_ignored(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.hp = 30

        self.client._on_update({
            "type": "update",
            "kind": "player.local_location",
            "payload": {},
        })
        # hp unchanged
        self.assertEqual(self.state.player.hp, 30)

    # ── cleanup ───────────────────────────────────────────────────

    @patch("companion_app.net.client.socket")
    def test_cleanup_resets_state(self, mock_socket_module: MagicMock) -> None:
        fake = _FakeSocket()
        mock_socket_module.socket.return_value = fake
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM

        self.client._connect()
        self.client._check_connected()
        self.client.cleanup()
        self.assert_connection(ConnectionState.DISCONNECTED)
        self.assertIsNone(self.client._sock)

    # ── error handling ────────────────────────────────────────────

    def test_malformed_json_logged_and_skipped(self) -> None:
        from companion_app.net.framing import read_line
        buf = bytearray(b"not-json\n{\"valid\": 1}\n")
        obj1, rem = read_line(buf)
        self.assertIsNone(obj1)
        obj2, _ = read_line(rem)
        self.assertEqual(obj2, {"valid": 1})


if __name__ == "__main__":
    unittest.main()
