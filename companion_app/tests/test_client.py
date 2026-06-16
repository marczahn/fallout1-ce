"""Unit tests for the NetworkClient (M3-T2).

Uses mock sockets to test state machine transitions, message dispatch,
and reconnection logic in isolation.
"""
from __future__ import annotations

import errno
import socket
import unittest
from unittest.mock import MagicMock, patch

from companion_app.net.client import NetworkClient
from companion_app.state import AppState, ConnectionState, PlayerSurface, WorldInfo


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


class _RefusedSocket(_FakeSocket):
    def connect_ex(self, address: tuple[str, int]) -> int:
        self._connected = False
        return errno.ECONNREFUSED


class _PendingRefusedSocket(_FakeSocket):
    def connect_ex(self, address: tuple[str, int]) -> int:
        self._connected = False
        return errno.EINPROGRESS

    def getsockopt(self, level: int, optname: int) -> int:
        return errno.ECONNREFUSED


class NetworkClientTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = AppState()
        self.client = NetworkClient(
            host="127.0.0.1",
            port=28080,
            password="testpw",
            state=self.state,
        )

    def tearDown(self) -> None:
        self.client.cleanup()

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

    @patch("companion_app.net.client.time.monotonic")
    @patch("companion_app.net.client.socket")
    def test_pending_connect_refusal_schedules_retry(
        self,
        mock_socket_module: MagicMock,
        mock_monotonic: MagicMock,
    ) -> None:
        mock_socket_module.socket.return_value = _PendingRefusedSocket()
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM
        mock_socket_module.SOL_SOCKET = socket.SOL_SOCKET
        mock_socket_module.SO_ERROR = socket.SO_ERROR
        mock_monotonic.return_value = 100.0

        self.client._connect()
        self.assert_connection(ConnectionState.CONNECTING)
        self.client._check_connected()

        self.assert_connection(ConnectionState.RECONNECTING)

    @patch("companion_app.net.client.time.monotonic")
    @patch("companion_app.net.client.socket")
    def test_connect_refused_retries_after_one_second(
        self,
        mock_socket_module: MagicMock,
        mock_monotonic: MagicMock,
    ) -> None:
        mock_socket_module.socket.return_value = _RefusedSocket()
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM
        mock_monotonic.side_effect = [100.0, 100.5, 101.0, 101.0]

        self.client._connect()
        self.assert_connection(ConnectionState.RECONNECTING)
        self.assertEqual(mock_socket_module.socket.call_count, 1)

        self.client.poll()
        self.assertEqual(mock_socket_module.socket.call_count, 1)

        self.client.poll()
        self.assertEqual(mock_socket_module.socket.call_count, 2)
        self.assert_connection(ConnectionState.RECONNECTING)

    @patch("companion_app.net.client.time.monotonic")
    @patch("companion_app.net.client.socket")
    def test_connect_attempts_are_not_forwarded_to_visible_log(
        self,
        mock_socket_module: MagicMock,
        mock_monotonic: MagicMock,
    ) -> None:
        visible: list[str] = []
        client = NetworkClient(
            host="127.0.0.1",
            port=28080,
            password="testpw",
            state=AppState(),
            log_fn=visible.append,
        )
        mock_socket_module.socket.return_value = _RefusedSocket()
        mock_socket_module.AF_INET = socket.AF_INET
        mock_socket_module.SOCK_STREAM = socket.SOCK_STREAM
        mock_monotonic.return_value = 100.0

        client._connect()

        self.assertEqual(visible, [])

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
            b'{"type":"world","schemaVersion":4,"game":"fallout1-ce",'
            b'"playerAvailable":true}\n'
        )
        self.client._try_recv()
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertIsNotNone(self.state.world)
        self.assertEqual(self.state.world.schema_version, 4)
        self.assertEqual(self.state.world.game, "fallout1-ce")
        self.assertTrue(self.state.world.player_available)
        # getSnapshot should be queued in the internal write buffer.
        self.assertIn(b"getSnapshot", self.client._write_buf)

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
            "schemaVersion": 4,
            "game": "fallout1-ce",
            "playerAvailable": True,
        })
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertEqual(self.state.world.schema_version, 4)
        self.assertEqual(self.state.world.game, "fallout1-ce")
        # `world.playerAvailable` is the authoritative handshake-time
        # availability flag.
        self.assertTrue(self.state.world.player_available)
        self.assertTrue(self.state.player.available)

    def test_world_dispatch_player_unavailable(self) -> None:
        # World arrives during the main menu or world map: player is
        # not loaded, and the client must not display hp.
        self.state.connection = ConnectionState.AWAITING_WORLD
        self.client._on_world({
            "type": "world",
            "schemaVersion": 4,
            "game": "fallout1-ce",
            "playerAvailable": False,
        })
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertFalse(self.state.world.player_available)
        self.assertFalse(self.state.player.available)

    def test_snapshot_dispatch_with_player(self) -> None:
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.state.player.available = True
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

    def test_snapshot_dispatch_applies_status_special_and_location(self) -> None:
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.state.player.available = True
        self.client._on_snapshot({
            "type": "snapshot",
            "playerAvailable": True,
            "payload": {
                "player.vitals": {"hp": 30, "maxHp": 40},
                "player.status": {
                    "armorClass": 12,
                    "currentCarryWeight": 132,
                    "carryWeight": 200,
                    "meleeDamage": 2,
                    "damageResistance": 10,
                    "radiation": 4,
                    "poison": 2,
                },
                "player.special": {
                    "strength": 5,
                    "perception": 7,
                    "endurance": 6,
                    "charisma": 4,
                    "intelligence": 8,
                    "agility": 9,
                    "luck": 6,
                },
                "player.progression": {
                    "level": 4,
                    "experience": 7650,
                    "nextLevelExp": 8000,
                },
                "player.localLocation": {
                    "tile": 1000,
                    "elevation": 0,
                    "map": 12,
                    "location": "Junktown",
                    "locationId": "JUNKENT",
                },
                "player.inventory": [
                    {"pid": 40, "protoId": "STIMPAK", "name": "Stimpak", "type": "drug", "count": 9, "slot": "none"},
                    {"pid": 144, "protoId": "SUPERSTIM", "name": "Super Stimpak", "type": "drug", "count": 9, "slot": "none"},
                ],
            },
        })
        self.assertEqual(self.state.player.armor_class, 12)
        self.assertEqual(self.state.player.current_carry_weight, 132)
        self.assertEqual(self.state.player.carry_weight, 200)
        self.assertEqual(self.state.player.melee_damage, 2)
        self.assertEqual(self.state.player.damage_resistance, 10)
        self.assertEqual(self.state.player.radiation, 4)
        self.assertEqual(self.state.player.poison, 2)
        self.assertEqual(self.state.player.level, 4)
        self.assertEqual(self.state.player.experience, 7650)
        self.assertEqual(self.state.player.next_level_exp, 8000)
        self.assertEqual(self.state.player.strength, 5)
        self.assertEqual(self.state.player.luck, 6)
        self.assertEqual(self.state.player.surface, PlayerSurface.LOCAL)
        self.assertEqual(self.state.player.location, "Junktown")
        self.assertEqual(self.state.player.location_id, "JUNKENT")
        self.assertEqual(len(self.state.player.inventory), 2)
        self.assertEqual(self.state.player.inventory[0].pid, 40)

    def test_snapshot_dispatch_without_player(self) -> None:
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.state.player.available = False
        self.client._on_snapshot({
            "type": "snapshot",
            "playerAvailable": False,
            "payload": {},
        })
        self.assert_connection(ConnectionState.READY)
        self.assertFalse(self.state.player.available)
        # No vitals in payload when player is absent -- defaults preserved.
        self.assertEqual(self.state.player.hp, 0)
        self.assertEqual(self.state.player.max_hp, 0)

    def test_snapshot_does_not_override_availability(self) -> None:
        # Race: an `onPlayerUnavailable` landed between the
        # `getSnapshot` request and the reply. The snapshot's
        # `playerAvailable: True` is truth-at-request-time and must
        # NOT re-flip `player.available`. Events are authoritative.
        self.state.connection = ConnectionState.AWAITING_SNAPSHOT
        self.state.player.available = False
        self.client._on_snapshot({
            "type": "snapshot",
            "playerAvailable": True,
            "payload": {
                "player.vitals": {"hp": 30, "maxHp": 40},
            },
        })
        self.assert_connection(ConnectionState.READY)
        self.assertFalse(self.state.player.available)
        # Vitals are still applied from the payload -- the UI is gated
        # on `player.available` so stale hp data is invisible.
        self.assertEqual(self.state.player.hp, 30)
        self.assertEqual(self.state.player.max_hp, 40)

    def test_player_available_handler(self) -> None:
        # Steady-state `Ready`, player was unavailable. Server sends
        # `onPlayerAvailable`; the client flips availability and
        # queues a re-sync snapshot.
        self.state.connection = ConnectionState.READY
        self.state.player.available = False
        self.client._write_buf.clear()
        self.client._handle_player_available()
        self.assertTrue(self.state.player.available)
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertIn(b"getSnapshot", self.client._write_buf)

    def test_player_available_handler_when_already_available(self) -> None:
        # Idempotency: if the event arrives when the player is
        # already available, the client still re-syncs. A double
        # `onPlayerAvailable` would be a server bug, but the
        # client treats it as "request another snapshot".
        self.state.connection = ConnectionState.READY
        self.state.player.available = True
        self.client._write_buf.clear()
        self.client._handle_player_available()
        self.assertTrue(self.state.player.available)
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertIn(b"getSnapshot", self.client._write_buf)

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

    def test_update_status(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True

        self.client._on_update({
            "type": "update",
            "kind": "player.status",
            "playerAvailable": True,
            "payload": {
                "armorClass": 11,
                "currentCarryWeight": 132,
                "carryWeight": 200,
                "meleeDamage": 2,
                "damageResistance": 10,
                "radiation": 3,
                "poison": 1,
            },
        })
        self.assertEqual(self.state.player.armor_class, 11)
        self.assertEqual(self.state.player.current_carry_weight, 132)
        self.assertEqual(self.state.player.carry_weight, 200)
        self.assertEqual(self.state.player.melee_damage, 2)
        self.assertEqual(self.state.player.damage_resistance, 10)
        self.assertEqual(self.state.player.radiation, 3)
        self.assertEqual(self.state.player.poison, 1)

    def test_update_special(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True

        self.client._on_update({
            "type": "update",
            "kind": "player.special",
            "playerAvailable": True,
            "payload": {
                "strength": 5,
                "perception": 7,
                "endurance": 6,
                "charisma": 4,
                "intelligence": 8,
                "agility": 9,
                "luck": 6,
            },
        })
        self.assertEqual(self.state.player.strength, 5)
        self.assertEqual(self.state.player.intelligence, 8)
        self.assertEqual(self.state.player.luck, 6)

    def test_update_progression(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True

        self.client._on_update({
            "type": "update",
            "kind": "player.progression",
            "playerAvailable": True,
            "payload": {"level": 4, "experience": 7650, "nextLevelExp": 8000},
        })
        self.assertEqual(self.state.player.level, 4)
        self.assertEqual(self.state.player.experience, 7650)
        self.assertEqual(self.state.player.next_level_exp, 8000)

    def test_update_inventory(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True

        self.client._on_update({
            "type": "update",
            "kind": "player.inventory",
            "playerAvailable": True,
            "payload": [
                {"pid": 40, "protoId": "STIMPAK", "name": "Stimpak", "type": "drug", "count": 9, "slot": "none"},
                {"pid": 144, "protoId": "SUPERSTIM", "name": "Super Stimpak", "type": "drug", "count": 2, "slot": "none"},
            ],
        })
        self.assertEqual(len(self.state.player.inventory), 2)
        self.assertEqual(self.state.player.inventory[0].pid, 40)
        self.assertEqual(self.state.player.inventory[1].count, 2)

    def test_world_location_update_clears_stale_local_location(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True
        self.state.player.surface = PlayerSurface.LOCAL
        self.state.player.location = "Junktown"
        self.state.player.location_id = "JUNKENT"

        self.client._on_update({
            "type": "update",
            "kind": "player.worldLocation",
            "playerAvailable": True,
            "payload": {"x": 120, "y": 240},
        })
        self.assertEqual(self.state.player.surface, PlayerSurface.WORLD)
        self.assertEqual(self.state.player.location, "")
        self.assertEqual(self.state.player.location_id, "")
        self.assertEqual(self.state.player.world_x, 120)
        self.assertEqual(self.state.player.world_y, 240)

    def test_local_location_update_clears_world_coordinates(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True
        self.state.player.surface = PlayerSurface.WORLD
        self.state.player.world_x = 120
        self.state.player.world_y = 240

        self.client._on_update({
            "type": "update",
            "kind": "player.localLocation",
            "playerAvailable": True,
            "payload": {
                "tile": 1000,
                "elevation": 0,
                "map": 12,
                "location": "Junktown",
                "locationId": "JUNKENT",
            },
        })
        self.assertEqual(self.state.player.surface, PlayerSurface.LOCAL)
        self.assertEqual(self.state.player.location, "Junktown")
        self.assertEqual(self.state.player.location_id, "JUNKENT")
        self.assertEqual(self.state.player.world_x, 0)
        self.assertEqual(self.state.player.world_y, 0)

    def test_player_unavailable_handler(self) -> None:
        self.state.player.available = True
        self.client._handle_player_unavailable()
        self.assertFalse(self.state.player.available)

    def test_dispatch_onPlayerAvailable_routes_to_handler(self) -> None:
        # Verifies the wire-type string `onPlayerAvailable` reaches
        # the right handler via the dispatch path, not just a direct
        # method call.
        self.state.connection = ConnectionState.READY
        self.state.player.available = False
        self.client._write_buf.clear()
        self.client._dispatch({"type": "onPlayerAvailable"})
        self.assertTrue(self.state.player.available)
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertIn(b"getSnapshot", self.client._write_buf)

    def test_dispatch_onPlayerUnavailable_routes_to_handler(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.available = True
        self.client._dispatch({"type": "onPlayerUnavailable"})
        self.assertFalse(self.state.player.available)

    def test_re_sync_flow_end_to_end(self) -> None:
        # The full path the user reported: client is in steady-state
        # `Ready` with `player.available = False` (NO SIGNAL), the
        # server sends `onPlayerAvailable`, then a `snapshot` in
        # response to the client's `getSnapshot`. After both: state
        # is `Ready`, `player.available` is True, vitals are
        # populated.
        self.state.connection = ConnectionState.READY
        self.state.player.available = False
        self.client._write_buf.clear()

        self.client._dispatch({"type": "onPlayerAvailable"})
        self.assert_connection(ConnectionState.AWAITING_SNAPSHOT)
        self.assertTrue(self.state.player.available)
        self.assertIn(b"getSnapshot", self.client._write_buf)

        self.client._dispatch({
            "type": "snapshot",
            "seq": 1,
            "playerAvailable": True,
            "payload": {
                "player.vitals": {"hp": 30, "maxHp": 40},
            },
        })
        self.assert_connection(ConnectionState.READY)
        self.assertTrue(self.state.player.available)
        self.assertEqual(self.state.player.hp, 30)
        self.assertEqual(self.state.player.max_hp, 40)

    def test_update_unknown_kind_ignored(self) -> None:
        self.state.connection = ConnectionState.READY
        self.state.player.hp = 30

        self.client._on_update({
            "type": "update",
            "kind": "player.unknown",
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
