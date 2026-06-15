#!/usr/bin/env python3
"""Smoke test for the companion server protocol (T0 / step 2 T0-redesign).

Assumes the game is running with the companion server enabled. The server
is enabled only when `fallout.cfg` has both `[companion] bind` and
`[companion] password` set. The test reads the password from
`--password` on the command line (or the `FALLOUT_COMPANION_PASSWORD`
environment variable) and uses it for the `auth` step of the handshake.

T0 protocol changes verified:
- `world.schemaVersion` is `4` (was `3` before the camelCase identifier cleanup).
- `update` carries a `kind` field and a `payload` wrapper (no `entity`,
  no `data`).
- `update.payload` is the *complete* per-kind object, not a field-level
  diff. A client that receives an `update` can merge it into its
  current state without having to first `getSnapshot`.
- `snapshot.payload` is a kind->object map (no `data.player`).
- `update` and `snapshot` do NOT carry `data` (T0 renamed it to
  `payload`).

The step-1/step-2 contracts that T0 preserves are also verified:
- The `auth` -> `hello` -> `world` handshake.
- The post-handshake `seq` invariant.
- A wrong / empty / missing-password `auth` is dropped.
- A `hello` as the first message is dropped.
- After a bad client, the server is still listening.

What this script does not test (would need live gameplay or visual
inspection of the main menu):
- HP values in the payload (depends on the player being in real
  gameplay, which requires walking past the main menu in a real game).
- The 500 ms cadence of `update` messages.
- The `onPlayerUnavailable` transition on death/world unload.
- The `onPlayerAvailable` re-sync trigger (steady-state `Ready` -> `AWAITING_SNAPSHOT`).
- The main-menu "disabled" hint line (verify visually).
- Surface transitions (local <-> world map) force-emit.

Run:
    python3 scripts/companion_smoke_test.py --password your-secret
    python3 scripts/companion_smoke_test.py --password your-secret --port 28080
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


def assert_is_str(value, label):
    if not isinstance(value, str):
        fail(f"{label}: expected str, got {value!r} ({type(value).__name__})")
    ok(f"{label} is str ({value!r})")


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
    # Current protocol version after the camelCase identifier cleanup.
    assert_equal(msg.get("schemaVersion"), 4, "world.schemaVersion")
    assert_field(msg, "game", "world")
    assert_field(msg, "playerAvailable", "world")
    assert_is_bool(msg["playerAvailable"], "world.playerAvailable")
    # T0: world has no `seq`, no `kind`, no `payload`.
    assert_not_present(msg, "seq", "world")
    assert_not_present(msg, "kind", "world")
    assert_not_present(msg, "payload", "world")
    # T0: `data` was renamed to `payload`; `world` never had `data`,
    # and still doesn't.
    assert_not_present(msg, "data", "world")


def test_getSnapshot(sock, expected_seq):
    print(f"test: getSnapshot -> snapshot (seq={expected_seq})")
    sock.sendall(b'{"type":"getSnapshot"}\n')
    line = recv_line(sock)
    if line is None:
        fail("server closed connection after getSnapshot")
    msg = json.loads(line)
    assert_equal(msg.get("type"), "snapshot", "type")
    assert_field(msg, "seq", "snapshot")
    assert_equal(msg.get("seq"), expected_seq, "snapshot.seq")
    # T0: snapshot has no `entity` (entity is encoded in the kind namespace).
    assert_not_present(msg, "entity", "snapshot")
    assert_field(msg, "playerAvailable", "snapshot")
    assert_is_bool(msg["playerAvailable"], "snapshot.playerAvailable")
    # T0: snapshot has `payload`, NOT `data`.
    assert_not_present(msg, "data", "snapshot (T0 rename)")
    assert_field(msg, "payload", "snapshot")
    payload = msg["payload"]
    if not isinstance(payload, dict):
        fail(f"snapshot.payload must be an object, got {type(payload).__name__}: {payload!r}")
    ok("snapshot.payload is an object")

    if not msg["playerAvailable"]:
        print("  skip: player not available; cannot verify payload kinds")
        return

    # T0: vitals is always present when the player is loaded.
    assert_field(payload, "player.vitals", "snapshot.payload")
    vitals = payload["player.vitals"]
    assert_field(vitals, "hp", "snapshot.payload.player.vitals")
    assert_field(vitals, "maxHp", "snapshot.payload.player.vitals")
    assert_is_int(vitals["hp"], "snapshot.payload.player.vitals.hp")
    assert_is_int(vitals["maxHp"], "snapshot.payload.player.vitals.maxHp")
    print(f"  info: hp={vitals['hp']} maxHp={vitals['maxHp']}")

    # T0: exactly one of local_location / world_location is present.
    has_local = "player.localLocation" in payload
    has_world = "player.worldLocation" in payload
    if has_local and has_world:
        fail("snapshot.payload: local_location and world_location are mutually exclusive")
    if not has_local and not has_world:
        # Player loaded but no location kind -- this is the snapshot
        # before the world map helper has a chance to populate. Tolerate
        # it on the main menu / character creation; flag it in real
        # gameplay if it persists.
        print("  info: no location kind in payload (player loaded but no surface determined)")
        return
    if has_local:
        local = payload["player.localLocation"]
        for k in ("tile", "elevation", "map", "location", "locationId"):
            assert_field(local, k, f"snapshot.payload.player.localLocation.{k}")
        assert_is_int(local["tile"], "snapshot.payload.player.localLocation.tile")
        assert_is_int(local["elevation"], "snapshot.payload.player.localLocation.elevation")
        assert_is_int(local["map"], "snapshot.payload.player.localLocation.map")
        # `location` may be a string or null (when the engine has no name).
        if local["location"] is not None:
            assert_is_str(local["location"], "snapshot.payload.player.localLocation.location")
        assert_is_str(local["locationId"], "snapshot.payload.player.localLocation.locationId")
        print(f"  info: local tile={local['tile']} elev={local['elevation']} map={local['map']} locationId={local['locationId']!r}")
    else:
        world = payload["player.worldLocation"]
        assert_field(world, "x", "snapshot.payload.player.worldLocation.x")
        assert_field(world, "y", "snapshot.payload.player.worldLocation.y")
        assert_is_int(world["x"], "snapshot.payload.player.worldLocation.x")
        assert_is_int(world["y"], "snapshot.payload.player.worldLocation.y")
        print(f"  info: world x={world['x']} y={world['y']}")


def test_update_shape(sock, password):
    """Drive a couple of samples and verify each `update` carries a
    kind tag and a `payload` wrapper, with no `entity` or `data` fields.
    Per the T0 contract, the `payload` is the *complete* per-kind
    object (not a field-level diff), so we also verify that the right
    set of fields is present for each kind.
    """
    print("test: update envelope invariants (kind + payload, no entity/data) and full payload per kind")
    # Wait briefly so the tick has a chance to emit a delta.
    sock.settimeout(1.5)
    saw_update = False
    while True:
        try:
            line = recv_line(sock)
        except socket.timeout:
            break
        if line is None:
            break
        msg = json.loads(line)
        if msg.get("type") != "update":
            # Skip non-update traffic.
            continue
        saw_update = True
        # T0: update must have `kind` and `payload`, must not have `entity` or `data`.
        assert_field(msg, "kind", "update")
        assert_is_str(msg["kind"], "update.kind")
        assert_field(msg, "payload", "update")
        if not isinstance(msg["payload"], dict):
            fail(f"update.payload must be an object, got {type(msg['payload']).__name__}: {msg['payload']!r}")
        ok(f"update.payload is an object (kind={msg['kind']!r})")
        assert_not_present(msg, "entity", "update (T0 removed entity)")
        assert_not_present(msg, "data", "update (T0 renamed data -> payload)")
        assert_field(msg, "seq", "update")
        assert_field(msg, "playerAvailable", "update")
        # T0: known kinds, and the payload must contain the full set of
        # per-kind fields (no partial diff). The server only calls the
        # builder when it has a complete sample.
        kind = msg["kind"]
        payload = msg["payload"]
        if kind == "player.vitals":
            expected_fields = {"hp", "maxHp"}
        elif kind == "player.localLocation":
            expected_fields = {"tile", "elevation", "map", "location", "locationId"}
        elif kind == "player.worldLocation":
            expected_fields = {"x", "y"}
        else:
            fail(f"update.kind: unknown kind {kind!r}")
        actual_fields = set(payload.keys())
        if actual_fields != expected_fields:
            fail(
                f"update.payload ({kind!r}): expected exactly {sorted(expected_fields)!r}, "
                f"got {sorted(actual_fields)!r}"
            )
        ok(f"update.payload ({kind!r}) has exactly the full set of fields")
        # We only need to validate one update.
        break
    if not saw_update:
        print("  info: no `update` arrived within 1.5s (player not in real gameplay yet); envelope check deferred")


def test_post_handshake_hello_is_ignored(sock):
    print("test: post-handshake hello is silently ignored")
    sock.settimeout(RECV_TIMEOUT_SECONDS)
    sock.sendall(b'{"type":"hello"}\n')
    sock.sendall(b'{"type":"getSnapshot"}\n')
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
        assert_equal(msg.get("schemaVersion"), 4, "world.schemaVersion (recovery)")


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
        test_getSnapshot(sock, expected_seq=1)
        test_update_shape(sock, args.password)
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
