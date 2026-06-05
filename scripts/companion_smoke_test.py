#!/usr/bin/env python3
"""Smoke test for the companion server protocol (step 2).

Assumes the game is running with the companion server enabled. The server
is enabled only when `fallout.cfg` has both `[companion] bind` and
`[companion] password` set. The test reads the password from
`--password` on the command line (or the `FALLOUT_COMPANION_PASSWORD`
environment variable) and uses it for the `auth` step of the handshake.

Verifies the parts of the protocol that do not depend on game state:
- The `auth` -> `hello` -> `world` handshake with `schemaVersion: 2`.
- The post-handshake `seq` invariant.
- The snapshot-shape invariant.
- The "invalid first message drops the connection" rule (extended for
  step 2: a `hello` first message is also dropped).
- A wrong / empty / missing-password `auth` is dropped.
- After a bad client, the server is still listening.

What this script does not test (would need live gameplay or visual
inspection of the main menu):
- HP values in `data.player`.
- The 500 ms cadence of `update` messages.
- The `player_unavailable` transition on death/world unload.
- The main-menu "disabled" hint line (verify visually).

Run:
    python3 scripts/companion_smoke_test.py --password foo
    python3 scripts/companion_smoke_test.py --password foo --port 28080
"""

import argparse
import json
import os
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


def send_auth(sock, password):
    payload = json.dumps({"type": "auth", "password": password})
    sock.sendall(payload.encode("utf-8") + b"\n")


def test_auth_then_hello(sock, password):
    print(f"test: auth -> hello -> world")
    send_auth(sock, password)
    # No server response to a correct auth; the server stays silent until hello.
    sock.sendall(b'{"type":"hello"}\n')
    line = recv_line(sock)
    if line is None:
        fail("server closed connection after auth + hello")
    msg = json.loads(line)
    assert_equal(msg.get("type"), "world", "type")
    assert_field(msg, "schemaVersion", "world")
    assert_equal(msg.get("schemaVersion"), 2, "world.schemaVersion")
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
    line1 = recv_line(sock)
    if line1 is None:
        fail("server closed connection unexpectedly after second hello")
    msg = json.loads(line1)
    assert_equal(msg.get("type"), "snapshot", "first response after ignored hello")


def expect_dropped(host, port, send_payload, label):
    print(f"test: {label}")
    with socket.create_connection((host, port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        sock.sendall(send_payload)
        chunks = []
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        except socket.timeout:
            fail(f"server did not close connection on: {label}")
    ok(f"{label}: server closed the connection")


def test_hello_first_message_drops(host, port):
    expect_dropped(host, port, b'{"type":"hello"}\n', "hello as first message is dropped")


def test_auth_wrong_password_drops(host, port, real_password):
    expect_dropped(
        host,
        port,
        b'{"type":"auth","password":"wrong-guess"}\n',
        "wrong auth password is dropped",
    )


def test_auth_empty_password_drops(host, port):
    expect_dropped(
        host,
        port,
        b'{"type":"auth","password":""}\n',
        "empty auth password is dropped",
    )


def test_auth_missing_password_field_drops(host, port):
    expect_dropped(
        host,
        port,
        b'{"type":"auth"}\n',
        "auth without password field is dropped",
    )


def test_unknown_first_message_drops(host, port):
    expect_dropped(host, port, b'{"type":"foo"}\n', "unknown first message is dropped")


def test_server_still_listening(host, port, password):
    print("test: server still listening after a bad client")
    with socket.create_connection((host, port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        send_auth(sock, password)
        sock.sendall(b'{"type":"hello"}\n')
        line = recv_line(sock)
        if line is None:
            fail("server did not respond to a new auth + hello after the bad client")
        msg = json.loads(line)
        assert_equal(msg.get("type"), "world", "type after recovery")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--password",
        default=os.environ.get("FALLOUT_COMPANION_PASSWORD", ""),
        help="the configured companion_password in fallout.cfg",
    )
    args = parser.parse_args()

    if not args.password:
        print("FAIL: --password (or FALLOUT_COMPANION_PASSWORD) is required", file=sys.stderr)
        sys.exit(2)

    with socket.create_connection((args.host, args.port), timeout=RECV_TIMEOUT_SECONDS) as sock:
        sock.settimeout(RECV_TIMEOUT_SECONDS)
        test_auth_then_hello(sock, args.password)
        test_get_snapshot(sock, expected_seq=1)
        test_post_handshake_hello_is_ignored(sock)

    test_hello_first_message_drops(args.host, args.port)
    test_auth_wrong_password_drops(args.host, args.port, args.password)
    test_auth_empty_password_drops(args.host, args.port)
    test_auth_missing_password_field_drops(args.host, args.port)
    test_unknown_first_message_drops(args.host, args.port)
    test_server_still_listening(args.host, args.port, args.password)

    print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
