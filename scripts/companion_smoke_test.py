#!/usr/bin/env python3
"""Smoke test for the companion server protocol.

Assumes the game is running with the companion server enabled (default
binds to 0.0.0.0:28080 in step 1). Verifies the parts of the protocol
that do not depend on game state: wire format, handshake, the
post-handshake `seq` invariant, the snapshot-shape invariant, and the
"invalid first message drops the connection" rule.

What this script does not test (would need live gameplay):
- HP values in `data.player`.
- The 500 ms cadence of `update` messages.
- The `player_unavailable` transition on death/world unload.

Run:
    python3 scripts/companion_smoke_test.py
    python3 scripts/companion_smoke_test.py --port 28080
"""

import argparse
import json
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 28080
RECV_TIMEOUT_SECONDS = 2.0


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(1)


def ok(message):
    print(f"  ok: {message}")


def recv_line(sock):
    """Read bytes from the socket until a newline is found."""
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            return None
        buf.extend(chunk)
        if b"\n" in buf:
            line, _, _rest = buf.partition(b"\n")
            return line.decode("utf-8")


def assert_field(obj, key, label):
    if key not in obj:
        fail(f"{label}: missing key {key!r} in {obj!r}")
    ok(f"{label} has {key!r}")


def assert_equal(actual, expected, label):
    if actual != expected:
        fail(f"{label}: expected {expected!r}, got {actual!r}")
    ok(f"{label} == {expected!r}")


def assert_not_present(obj, key, label):
    if key in obj:
        fail(f"{label}: must not contain {key!r}; got {obj!r}")
    ok(f"{label} has no {key!r}")


def assert_is_bool(value, label):
    if not isinstance(value, bool):
        fail(f"{label}: expected bool, got {value!r} ({type(value).__name__})")
    ok(f"{label} is bool ({value})")


def assert_is_int(value, label):
    if not isinstance(value, int) or isinstance(value, bool):
        fail(f"{label}: expected int, got {value!r} ({type(value).__name__})")
    ok(f"{label} is int ({value})")


def test_hello_world(sock):
    print("test: hello -> world")
    sock.sendall(b'{"type":"hello"}\n')
    line = recv_line(sock)
    if line is None:
        fail("server closed connection after hello")

    msg = json.loads(line)
    assert_equal(msg.get("type"), "world", "type")
    assert_field(msg, "schemaVersion", "world")
    assert_equal(msg.get("schemaVersion"), 1, "world.schemaVersion")
    assert_field(msg, "game", "world")
    assert_field(msg, "playerAvailable", "world")
    assert_is_bool(msg["playerAvailable"], "world.playerAvailable")
    assert_not_present(msg, "seq", "world")


def test_get_snapshot(sock, expected_seq):
    print(f"test: get_snapshot -> snapshot (seq={expected_seq})")
    sock.sendall(b'{"type":"get_snapshot"}\n')
    line = recv_line(sock)
    if line is None:
        fail("server closed connection after get_snapshot")

    msg = json.loads(line)
    assert_equal(msg.get("type"), "snapshot", "type")
    assert_field(msg, "seq", "snapshot")
    assert_equal(msg.get("seq"), expected_seq, "snapshot.seq")
    assert_not_present(msg, "entity", "snapshot")
    assert_field(msg, "playerAvailable", "snapshot")
    assert_is_bool(msg["playerAvailable"], "snapshot.playerAvailable")

    if not msg["playerAvailable"]:
        print("  skip: player not available; cannot verify data.player")
        return

    assert_field(msg, "data", "snapshot")
    data = msg["data"]
    assert_field(data, "player", "snapshot.data")
    player = data["player"]
    assert_field(player, "hp", "snapshot.data.player")
    assert_field(player, "maxHp", "snapshot.data.player")
    assert_is_int(player["hp"], "snapshot.data.player.hp")
    assert_is_int(player["maxHp"], "snapshot.data.player.maxHp")
    print(f"  info: hp={player['hp']} maxHp={player['maxHp']}")


def test_post_handshake_hello_is_ignored(sock):
    print("test: post-handshake hello is silently ignored")
    sock.sendall(b'{"type":"hello"}\n')
    sock.sendall(b'{"type":"get_snapshot"}\n')
    # First response: ignored hello produces no message. Second response: snapshot.
    # We read two lines and verify the second is a snapshot.
    line1 = recv_line(sock)
    if line1 is None:
        fail("server closed connection unexpectedly after second hello")
    msg = json.loads(line1)
    assert_equal(msg.get("type"), "snapshot", "first response after ignored hello")
    # If hello is NOT ignored, the second response would be a snapshot at seq=N+2
    # and the first would be a world. If hello IS ignored, the first response is
    # the snapshot at seq=N+1.
    # (This test relies on the snapshot arriving before any 500ms update; that
    # holds because the test runs in well under 500ms.)


def test_invalid_first_message(host, port):
    print("test: invalid first message drops the connection")
    with socket.create_connection((host, port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        sock.sendall(b'{"type":"foo"}\n')
        # Server should close the connection promptly. Read until EOF.
        chunks = []
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            fail("server did not close connection on invalid first message")
    ok("server closed the connection")


def test_server_still_listening(host, port):
    print("test: server still listening after a bad client")
    with socket.create_connection((host, port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        sock.sendall(b'{"type":"hello"}\n')
        line = recv_line(sock)
        if line is None:
            fail("server did not respond to a new hello after the bad client")
        msg = json.loads(line)
        assert_equal(msg.get("type"), "world", "type after recovery")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    with socket.create_connection((args.host, args.port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        test_hello_world(sock)
        test_get_snapshot(sock, expected_seq=1)
        test_post_handshake_hello_is_ignored(sock)

    test_invalid_first_message(args.host, args.port)
    test_server_still_listening(args.host, args.port)

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
