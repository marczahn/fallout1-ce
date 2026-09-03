#!/usr/bin/env python3
"""Smoke test for the companion server protocol (T0 / step 2 T0-redesign).

Assumes the game is running with the companion server enabled. The server
is enabled only when `fallout.cfg` has both `[companion] bind` and
`[companion] password` set. The test reads the password from
`--password` on the command line (or the `FALLOUT_COMPANION_PASSWORD`
environment variable) and uses it for the `auth` step of the handshake.

T0 protocol changes verified:
- `world.schemaVersion` is `14` (bumped when holodisk `body` text landed and
  every wire string became pure ASCII; `13` when the `player.transmissions`
  kind and the transmission audio fetch landed; `12` when `player.quests`
  was added).
- `update` carries a `kind` field and a `payload` wrapper (no `entity`,
  no `data`).
- `update.payload` is the *complete* per-kind object, not a field-level
  diff. A client that receives an `update` can merge it into its
  current state without having to first `getSnapshot`.
- `snapshot.payload` is a kind->object map (no `data.player`).
- `update` and `snapshot` do NOT carry `data` (T0 renamed it to
  `payload`).
- An inventory action over `cmd` is reported by the sampler's diff as an
  `update` of kind `player.inventory`, and never as a pushed `snapshot`
  (TASK-022). Opt-in via `--mutate-equipment`, because it equips a weapon
  in the live game.

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
import base64
import json
import math
import os
import struct
import socket
import sys

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 28080
RECV_TIMEOUT_SECONDS = 2.0

# Must match `kMapChunkBytes` in src/companion_server.cc.
MAP_CHUNK_BYTES = 147456
# Must match `kOutboundCap` in src/companion_server.cc.
OUTBOUND_CAP = 256 * 1024


def fail(message):
    print(f"FAIL: {message}")
    sys.exit(1)


def ok(message):
    print(f"  ok: {message}")


# Cases that could not run on this save/install. Counted and re-printed as a
# block at the end, because a run whose interesting half silently skipped
# looks exactly like a run that passed -- and "all ok" scrolling past is how
# a check that proves nothing gets mistaken for coverage.
SKIPPED: list[str] = []


def skipped(message):
    SKIPPED.append(message)
    print(f"  SKIPPED: {message}")


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
    # Current protocol version after the player.quests kind was added.
    assert_equal(msg.get("schemaVersion"), 14, "world.schemaVersion")
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
        for k in ("tile", "elevation", "map", "location", "mapName", "locationId", "worldX", "worldY"):
            assert_field(local, k, f"snapshot.payload.player.localLocation.{k}")
        assert_is_int(local["tile"], "snapshot.payload.player.localLocation.tile")
        assert_is_int(local["elevation"], "snapshot.payload.player.localLocation.elevation")
        assert_is_int(local["map"], "snapshot.payload.player.localLocation.map")
        # `location` may be a string or null (when the engine has no name).
        if local["location"] is not None:
            assert_is_str(local["location"], "snapshot.payload.player.localLocation.location")
        # `mapName` may be a string or null when the engine has no named map.
        if local["mapName"] is not None:
            assert_is_str(local["mapName"], "snapshot.payload.player.localLocation.mapName")
        assert_is_str(local["locationId"], "snapshot.payload.player.localLocation.locationId")
        # The overworld position is reported even on a local surface (TASK-013)
        # so the companion can show a world-map fix immediately.
        assert_is_int(local["worldX"], "snapshot.payload.player.localLocation.worldX")
        assert_is_int(local["worldY"], "snapshot.payload.player.localLocation.worldY")
        print(f"  info: local tile={local['tile']} elev={local['elevation']} map={local['map']} "
              f"locationId={local['locationId']!r} world=({local['worldX']},{local['worldY']})")
    else:
        world = payload["player.worldLocation"]
        assert_field(world, "x", "snapshot.payload.player.worldLocation.x")
        assert_field(world, "y", "snapshot.payload.player.worldLocation.y")
        assert_is_int(world["x"], "snapshot.payload.player.worldLocation.x")
        assert_is_int(world["y"], "snapshot.payload.player.worldLocation.y")
        print(f"  info: world x={world['x']} y={world['y']}")

    # player.quests (schemaVersion 12). Always present when the player is
    # loaded: the water-chip quest is forced visible by the engine, so the
    # array is never empty in a real game -- but the assertions below only
    # require the shape, so a modded quest table cannot fail them.
    assert_field(payload, "player.quests", "snapshot.payload")
    quests_payload = payload["player.quests"]
    if not isinstance(quests_payload, dict):
        fail("snapshot.payload.player.quests must be an object "
             f"(quests + water), got {type(quests_payload).__name__}: {quests_payload!r}")
    ok("snapshot.payload.player.quests is an object")

    # player.transmissions and player.holodisks (schemaVersion 13). Both are
    # present whenever the player is loaded, and both may legitimately be
    # EMPTY -- a fresh character has seen no cutscenes and found no disks --
    # so only the shape is asserted. They are deliberately separate kinds:
    # transmissions are replayable movies (the in-game ARCHIVES screen),
    # holodisks are text documents (the in-game STATUS screen).
    for kind, inner in (("player.transmissions", "transmissions"),
                        ("player.holodisks", "holodisks")):
        assert_field(payload, kind, "snapshot.payload")
        block = payload[kind]
        if not isinstance(block, dict):
            fail(f"snapshot.payload.{kind} must be an object, "
                 f"got {type(block).__name__}: {block!r}")
        assert_field(block, inner, f"snapshot.payload.{kind}")
        rows = block[inner]
        if not isinstance(rows, list):
            fail(f"snapshot.payload.{kind}.{inner} must be an array, "
                 f"got {type(rows).__name__}: {rows!r}")
        for row in rows:
            if not isinstance(row, dict):
                fail(f"{kind}.{inner} rows must be objects, got {row!r}")
            assert_field(row, "index", f"snapshot.payload.{kind}.{inner}[]")
            assert_is_int(row["index"], f"{kind}.{inner}[].index")
            assert_field(row, "title", f"snapshot.payload.{kind}.{inner}[]")
        ok(f"snapshot.payload.{kind} has {len(rows)} row(s), shape valid")

    # Holodisk body text (schemaVersion 14). This is the ONLY place the
    # engine's sentinel handling can be checked: `companionHolodiskBody`
    # has no unit-test target, and the app renders whatever it is sent, so
    # an app-side test would only prove the app is obedient.
    #
    # `body` may legitimately be empty -- that is how an unresolvable disk
    # is reported -- so emptiness is not a failure here.
    #
    # **A save with no holodisks checks nothing here, and says so.** The first
    # version of this block ended with an unconditional `ok(...)`, so against a
    # fresh character it printed "bodies are string arrays, no sentinels"
    # having examined zero rows -- reporting a pass for work it never did.
    # That is the same failure this ticket hit three times app-side: a green
    # result that proves nothing. Coverage that did not run must announce
    # itself, or the run is worse than not having the check.
    holodisks = payload["player.holodisks"]["holodisks"]
    for row in holodisks:
        where = f"player.holodisks.holodisks[index={row.get('index')}]"
        assert_field(row, "body", where)
        body = row["body"]
        if not isinstance(body, list):
            fail(f"{where}.body must be an array, "
                 f"got {type(body).__name__}: {body!r}")
        for line in body:
            if not isinstance(line, str):
                fail(f"{where}.body entries must be strings, got {line!r}")
            # Neither marker may ever reach a client. `**END-PAR**` is the
            # engine's blank line and must arrive as "" instead.
            if line.strip() in ("**END-DISK**", "**END-PAR**"):
                fail(f"{where}.body leaked the sentinel {line!r}")
    if holodisks:
        lines = sum(len(row["body"]) for row in holodisks)
        ok(f"player.holodisks: {len(holodisks)} disk(s), {lines} body line(s) "
           f"checked, no sentinels")
    else:
        skipped("player.holodisks is empty on this save -- the sentinel and "
                "body-shape checks did NOT run. Load a save that has found at "
                "least one disk to exercise them.")

    assert_field(quests_payload, "quests", "snapshot.payload.player.quests")
    quests = quests_payload["quests"]
    if not isinstance(quests, list):
        fail("snapshot.payload.player.quests.quests must be an array, "
             f"got {type(quests).__name__}: {quests!r}")
    ok("snapshot.payload.player.quests.quests is an array")

    assert_field(quests_payload, "water", "snapshot.payload.player.quests")
    water = quests_payload["water"]
    if not isinstance(water, dict):
        fail("snapshot.payload.player.quests.water must be an object, "
             f"got {type(water).__name__}: {water!r}")
    assert_field(water, "daysRemaining", "snapshot.payload.player.quests.water")
    assert_field(water, "countdownActive", "snapshot.payload.player.quests.water")
    assert_is_int(water["daysRemaining"], "snapshot.payload.player.quests.water.daysRemaining")
    assert_is_bool(water["countdownActive"], "snapshot.payload.player.quests.water.countdownActive")

    for index, quest in enumerate(quests):
        label = f"snapshot.payload.player.quests.quests[{index}]"
        if not isinstance(quest, dict):
            fail(f"{label} must be an object, got {type(quest).__name__}: {quest!r}")
        for key in ("locationIndex", "slot", "location", "text", "completed", "waterChip"):
            assert_field(quest, key, label)
        assert_is_int(quest["locationIndex"], f"{label}.locationIndex")
        assert_is_int(quest["slot"], f"{label}.slot")
        assert_is_str(quest["location"], f"{label}.location")
        # `text` may legitimately be empty (the message file could not
        # resolve the line); the row is still emitted, so only the type is
        # asserted here.
        assert_is_str(quest["text"], f"{label}.text")
        assert_is_bool(quest["completed"], f"{label}.completed")
        assert_is_bool(quest["waterChip"], f"{label}.waterChip")
    ok(f"snapshot.payload.player.quests.quests entries are well-formed ({len(quests)})")

    water_rows = [q for q in quests if q["waterChip"]]
    if len(water_rows) > 1:
        fail(f"at most one quest may carry waterChip, got {len(water_rows)}")
    print(f"  info: {len(quests)} quest(s), water daysRemaining={water['daysRemaining']} "
          f"countdownActive={water['countdownActive']}")


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
            expected_fields = {
                "tile", "elevation", "map", "location", "mapName", "locationId", "worldX", "worldY",
            }
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


def recv_line_bytes(sock):
    """Read bytes from the socket until a newline; return the line as raw
    bytes (without the trailing newline), or None on EOF."""
    buf = bytearray()
    while True:
        chunk = sock.recv(65536)
        if not chunk:
            return None
        buf.extend(chunk)
        if b"\n" in buf:
            line, _, _rest = buf.partition(b"\n")
            return bytes(line)


def test_get_map(sock):
    """Fetch the world-map image header + all chunks over the dedicated
    getMap/getMapChunk message types, then probe an out-of-range index.

    Requires a running game whose world-map art is lockable; on the main
    menu / character creation the art is still loadable (it is locked
    independently of the in-game world-map lifecycle), so this generally
    works headlessly once the server is up. If the server reports the
    map is unavailable, the test is skipped rather than failed.
    """
    print("test: getMap -> mapHeader -> mapChunk* (dedicated top-level messages)")
    sock.settimeout(RECV_TIMEOUT_SECONDS)
    sock.sendall(b'{"type":"getMap"}\n')
    line = recv_line_bytes(sock)
    if line is None:
        fail("server closed connection after getMap")
    if len(line) + 1 > OUTBOUND_CAP:
        fail(f"mapHeader line exceeds outbound cap ({len(line) + 1} > {OUTBOUND_CAP})")
    msg = json.loads(line.decode("utf-8"))

    if msg.get("type") == "mapError":
        print(f"  skip: server reports mapError reason={msg.get('reason')!r} (world-map art not lockable)")
        return

    assert_equal(msg.get("type"), "mapHeader", "type")
    for k in ("width", "height", "paletteB64", "chunkCount", "chunkBytes"):
        assert_field(msg, k, "mapHeader")
    assert_is_int(msg["width"], "mapHeader.width")
    assert_is_int(msg["height"], "mapHeader.height")
    assert_is_int(msg["chunkCount"], "mapHeader.chunkCount")
    assert_is_int(msg["chunkBytes"], "mapHeader.chunkBytes")
    assert_is_str(msg["paletteB64"], "mapHeader.paletteB64")

    width = msg["width"]
    height = msg["height"]
    chunk_bytes = msg["chunkBytes"]
    chunk_count = msg["chunkCount"]
    print(f"  info: width={width} height={height} chunkBytes={chunk_bytes} chunkCount={chunk_count}")

    palette = base64.b64decode(msg["paletteB64"])
    assert_equal(len(palette), 768, "decoded paletteB64 length")

    total = width * height
    expected_chunk_count = math.ceil(total / chunk_bytes)
    assert_equal(chunk_count, expected_chunk_count, "mapHeader.chunkCount == ceil(width*height/chunkBytes)")

    reassembled = bytearray()
    for index in range(chunk_count):
        sock.sendall(json.dumps({"type": "getMapChunk", "index": index}).encode("utf-8") + b"\n")
        chunk_line = recv_line_bytes(sock)
        if chunk_line is None:
            fail(f"server closed connection after getMapChunk index={index}")
        if len(chunk_line) + 1 > OUTBOUND_CAP:
            fail(f"mapChunk line exceeds outbound cap ({len(chunk_line) + 1} > {OUTBOUND_CAP}) at index={index}")
        chunk_msg = json.loads(chunk_line.decode("utf-8"))
        assert_equal(chunk_msg.get("type"), "mapChunk", f"chunk[{index}].type")
        assert_equal(chunk_msg.get("index"), index, f"chunk[{index}].index")
        assert_field(chunk_msg, "dataB64", f"chunk[{index}]")
        reassembled.extend(base64.b64decode(chunk_msg["dataB64"]))
    assert_equal(len(reassembled), total, "reassembled chunk length == width*height")

    # Out-of-range index: the server must reply with a mapError and must
    # NOT disconnect.
    sock.sendall(json.dumps({"type": "getMapChunk", "index": chunk_count}).encode("utf-8") + b"\n")
    err_line = recv_line_bytes(sock)
    if err_line is None:
        fail("server closed connection on out-of-range getMapChunk (must not disconnect)")
    err_msg = json.loads(err_line.decode("utf-8"))
    assert_equal(err_msg.get("type"), "mapError", "out-of-range getMapChunk -> mapError")
    assert_field(err_msg, "reason", "mapError")

    # The connection must still be usable after a mapError.
    sock.sendall(b'{"type":"getSnapshot"}\n')
    after = recv_line_bytes(sock)
    if after is None:
        fail("server disconnected after a mapError (must stay connected)")
    after_msg = json.loads(after.decode("utf-8"))
    assert_equal(after_msg.get("type"), "snapshot", "connection alive after mapError")


def test_get_local_map(sock):
    """Fetch the local automap image over getLocalMap/getLocalMapChunk.

    The server serves the *current* map+elevation from a live seen-object
    scan (it does NOT read AUTOMAP.DB), so this works even if the in-game
    Pip-Boy automap was never opened this session. When the player is not on
    a real local map (main menu, character creation, or on the world map),
    the server replies `localMapError` and MUST stay connected -- this test
    validates whichever path the live game is in, and always checks that the
    connection survives the error.
    """
    print("test: getLocalMap -> localMapHeader -> localMapChunk* (current map+elevation)")
    sock.settimeout(RECV_TIMEOUT_SECONDS)
    sock.sendall(b'{"type":"getLocalMap"}\n')
    line = recv_line_bytes(sock)
    if line is None:
        fail("server closed connection after getLocalMap")
    if len(line) + 1 > OUTBOUND_CAP:
        fail(f"localMapHeader line exceeds outbound cap ({len(line) + 1} > {OUTBOUND_CAP})")
    msg = json.loads(line.decode("utf-8"))

    if msg.get("type") == "localMapError":
        # No local map available (not playing / on the world map). Verify the
        # error shape and that the connection is NOT dropped.
        assert_field(msg, "reason", "localMapError")
        print(f"  info: localMapError reason={msg.get('reason')!r} (no local map in this state)")
        sock.sendall(b'{"type":"getSnapshot"}\n')
        after = recv_line_bytes(sock)
        if after is None:
            fail("server disconnected after a localMapError (must stay connected)")
        after_msg = json.loads(after.decode("utf-8"))
        assert_equal(after_msg.get("type"), "snapshot", "connection alive after localMapError")
        return

    assert_equal(msg.get("type"), "localMapHeader", "type")
    for k in ("map", "elevation", "width", "height", "explored", "paletteB64", "chunkCount", "chunkBytes"):
        assert_field(msg, k, "localMapHeader")
    assert_is_int(msg["map"], "localMapHeader.map")
    assert_is_int(msg["elevation"], "localMapHeader.elevation")
    assert_is_int(msg["width"], "localMapHeader.width")
    assert_is_int(msg["height"], "localMapHeader.height")
    assert_is_bool(msg["explored"], "localMapHeader.explored")
    assert_equal(msg["width"], 200, "localMapHeader.width == 200")
    assert_equal(msg["height"], 200, "localMapHeader.height == 200")
    assert_is_int(msg["chunkCount"], "localMapHeader.chunkCount")
    assert_is_int(msg["chunkBytes"], "localMapHeader.chunkBytes")
    assert_is_str(msg["paletteB64"], "localMapHeader.paletteB64")

    header_map = msg["map"]
    header_elevation = msg["elevation"]
    width = msg["width"]
    height = msg["height"]
    chunk_bytes = msg["chunkBytes"]
    chunk_count = msg["chunkCount"]
    print(f"  info: map={header_map} elevation={header_elevation} "
          f"width={width} height={height} chunkCount={chunk_count}")

    palette = base64.b64decode(msg["paletteB64"])
    assert_equal(len(palette), 768, "decoded localMap paletteB64 length")

    total = width * height
    expected_chunk_count = math.ceil(total / chunk_bytes)
    assert_equal(chunk_count, expected_chunk_count,
                 "localMapHeader.chunkCount == ceil(width*height/chunkBytes)")

    reassembled = bytearray()
    for index in range(chunk_count):
        sock.sendall(json.dumps({"type": "getLocalMapChunk", "index": index}).encode("utf-8") + b"\n")
        chunk_line = recv_line_bytes(sock)
        if chunk_line is None:
            fail(f"server closed connection after getLocalMapChunk index={index}")
        if len(chunk_line) + 1 > OUTBOUND_CAP:
            fail(f"localMapChunk exceeds outbound cap ({len(chunk_line) + 1} > {OUTBOUND_CAP}) at index={index}")
        chunk_msg = json.loads(chunk_line.decode("utf-8"))
        assert_equal(chunk_msg.get("type"), "localMapChunk", f"chunk[{index}].type")
        assert_equal(chunk_msg.get("index"), index, f"chunk[{index}].index")
        # Each chunk echoes the current map/elevation so the client can detect
        # a mid-fetch change; here they must match the header we received.
        assert_equal(chunk_msg.get("map"), header_map, f"chunk[{index}].map echo")
        assert_equal(chunk_msg.get("elevation"), header_elevation, f"chunk[{index}].elevation echo")
        assert_field(chunk_msg, "dataB64", f"chunk[{index}]")
        reassembled.extend(base64.b64decode(chunk_msg["dataB64"]))
    assert_equal(len(reassembled), total, "reassembled localMap length == width*height")

    # Every tile classifies as empty(0), wall(1), or scenery(2).
    bad = [b for b in set(reassembled) if b not in (0, 1, 2)]
    if bad:
        fail(f"localMap contains classes outside {{0,1,2}}: {sorted(bad)}")

    # Out-of-range index: the server must reply with a localMapError and must
    # NOT disconnect.
    sock.sendall(json.dumps({"type": "getLocalMapChunk", "index": chunk_count}).encode("utf-8") + b"\n")
    err_line = recv_line_bytes(sock)
    if err_line is None:
        fail("server closed connection on out-of-range getLocalMapChunk (must not disconnect)")
    err_msg = json.loads(err_line.decode("utf-8"))
    assert_equal(err_msg.get("type"), "localMapError", "out-of-range getLocalMapChunk -> localMapError")
    assert_field(err_msg, "reason", "localMapError")

    # The connection must still be usable after a localMapError.
    sock.sendall(b'{"type":"getSnapshot"}\n')
    after = recv_line_bytes(sock)
    if after is None:
        fail("server disconnected after a localMapError (must stay connected)")
    after_msg = json.loads(after.decode("utf-8"))
    assert_equal(after_msg.get("type"), "snapshot", "connection alive after localMapError")


class _LineStream:
    """Newline-framed reader that keeps whatever follows the first newline.

    `recv_line` / `recv_line_bytes` drop the remainder of a `recv` chunk,
    which is harmless for the strict request/response tests above but not
    here: a `cmd` reply and the sample it triggers are flushed in the same
    `companionServerTick`, so the `cmdAck` and the `player.inventory`
    update usually arrive in a single read.
    """

    def __init__(self, sock):
        self._sock = sock
        self._buf = bytearray()

    def next_message(self, timeout):
        """Next message as a parsed object, or None on EOF/timeout."""
        self._sock.settimeout(timeout)
        while True:
            if b"\n" in self._buf:
                line, _, rest = bytes(self._buf).partition(b"\n")
                self._buf[:] = rest
                return json.loads(line.decode("utf-8"))
            try:
                chunk = self._sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                return None
            self._buf.extend(chunk)


def test_inventory_action_emits_update(sock):
    """An inventory action issued over `cmd` must be reported the same way an
    in-game equip is: by the sampler's diff, as an `update` of kind
    `player.inventory`.

    Regression guard for TASK-022. The server used to push an unsolicited
    `snapshot` here, which the app discards (it only applies a `snapshot` it
    asked for) while `primeLastSentState` advanced the diff baseline past it --
    so the equip never reached the app at all. A pushed `snapshot` in this
    exchange is therefore a failure, not just a redundancy.

    Mutates the live player's loadout, so it only runs under
    `--mutate-equipment`.
    """
    print("test: cmd equipRightHand -> cmdAck + update(player.inventory), no pushed snapshot")
    stream = _LineStream(sock)

    sock.sendall(b'{"type":"getSnapshot"}\n')
    snapshot = None
    while True:
        msg = stream.next_message(RECV_TIMEOUT_SECONDS)
        if msg is None:
            fail("no snapshot arrived in response to getSnapshot")
        if msg.get("type") == "snapshot":
            snapshot = msg
            break

    inventory = (snapshot.get("payload") or {}).get("player.inventory")
    if not isinstance(inventory, list):
        print("  skip: no player.inventory in the snapshot (player not in real gameplay)")
        return

    # A one-handed, currently unequipped weapon: equipping it is guaranteed
    # to change `slot`, which is what the diff has to notice. Two-handed
    # weapons are excluded because they need `equipBothHands`, and an item
    # already in a slot would be a no-op the server correctly stays silent
    # about.
    candidate = next(
        (
            item for item in inventory
            if item.get("type") == "weapon"
            and not item.get("twoHanded", False)
            and item.get("slot") == "none"
            and int(item.get("objectId", 0)) > 0
        ),
        None,
    )
    if candidate is None:
        print("  skip: no unequipped one-handed weapon in the player's inventory")
        return
    object_id = int(candidate["objectId"])
    print(f"  info: equipping {candidate.get('name')!r} (objectId={object_id}) into the right hand")

    # Drain whatever the sampler queued alongside the snapshot, so anything
    # observed below belongs to the action. Bounded, because a game where the
    # player is moving emits `player.localLocation` every 500 ms and would
    # otherwise keep this loop fed indefinitely.
    for _ in range(20):
        if stream.next_message(0.4) is None:
            break

    sock.sendall(
        json.dumps({"type": "cmd", "id": 9001, "name": "equipRightHand", "objectId": object_id}).encode("utf-8")
        + b"\n"
    )

    saw_ack = False
    update = None
    # Other kinds may legitimately arrive first -- in combat the action's AP
    # cost is spent before the ack is queued -- so scan rather than assume
    # ordering.
    while update is None:
        msg = stream.next_message(RECV_TIMEOUT_SECONDS)
        if msg is None:
            break
        kind = msg.get("type")
        if kind == "snapshot":
            fail("server pushed a `snapshot` after an inventory action (TASK-022 regression): "
                 "the app discards unsolicited snapshots and `lastSent` is left holding state "
                 "the client never applied")
        if kind == "cmdAck" and msg.get("id") == 9001:
            if not msg.get("ok", False):
                error = msg.get("error")
                if error in ("notPlayersTurn", "notEnoughActionPoints"):
                    print(f"  skip: server rejected the action with {error!r} (combat state)")
                    return
                fail(f"equipRightHand was rejected: {error!r}")
            saw_ack = True
            ok("cmdAck ok=true")
            continue
        if kind == "update" and msg.get("kind") == "player.inventory":
            update = msg

    if not saw_ack:
        fail("no cmdAck arrived for the inventory action")
    if update is None:
        fail("no `update` of kind player.inventory arrived after the action "
             "(TASK-022: the sampler's diff must report an app-initiated equip)")
    ok("update(player.inventory) arrived and no snapshot was pushed")

    payload = update.get("payload")
    if not isinstance(payload, list):
        fail(f"update.payload (player.inventory) must be an array, got {type(payload).__name__}")
    equipped = next((item for item in payload if int(item.get("objectId", 0)) == object_id), None)
    if equipped is None:
        fail(f"objectId={object_id} is missing from the inventory update payload")
    assert_equal(equipped.get("slot"), "rightHand", f"objectId={object_id} slot after equipRightHand")
    print("  info: the player's right hand was changed by this test; re-equip in-game if it matters")


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
        assert_equal(msg.get("schemaVersion"), 14, "world.schemaVersion (recovery)")


def test_transmission_audio(sock):
    """Manifest, then a full audio+envelope fetch, then three negative cases.

    Uses its own `_LineStream` rather than `recv_line_bytes` for the same
    reason `test_inventory_action_emits_update` does: the negative cases
    below deliberately provoke replies while a sample may be in flight, so
    a reader that discards the remainder of a `recv` chunk would lose one.

    The negative cases are the point of this test as much as the happy
    path: every one of them must produce a `transmissionAudioError` AND leave
    the connection alive. An out-of-range index reaching the filesystem,
    or a malformed request dropping the connection, would both be bugs.
    """
    stream = _LineStream(sock)

    send(sock, {"type": "getTransmissionManifest"})
    manifest = stream.next_message(RECV_TIMEOUT_SECONDS)
    if manifest is None:
        fail("no transmissionManifest reply")
    assert_equal(manifest.get("type"), "transmissionManifest", "manifest type")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        fail("transmissionManifest.entries must be a list")
    print(f"  transmissionManifest: {len(entries)} baked disk(s)")

    if entries:
        entry = entries[0]
        index = entry["index"]
        expected_bytes = entry["bytes"]

        send(sock, {"type": "getTransmissionAudio", "index": index})
        header = stream.next_message(RECV_TIMEOUT_SECONDS)
        if header is None:
            fail("no transmissionAudioHeader reply")
        assert_equal(header.get("type"), "transmissionAudioHeader", "audio header type")
        assert_equal(header.get("index"), index, "audio header index")
        assert_equal(header.get("bytes"), expected_bytes, "audio header bytes matches manifest")

        envelope = base64.b64decode(header["envelopeB64"])
        if len(envelope) < 12 or envelope[:4] != b"HDEV":
            fail(f"envelope magic is not HDEV: {envelope[:4]!r}")
        version, bands = struct.unpack_from("<HH", envelope, 4)
        frames, frame_ms = struct.unpack_from("<IH", envelope, 8)
        assert_equal(version, 1, "envelope version")
        if len(envelope) != 14 + bands * frames:
            fail(f"envelope payload is {len(envelope) - 14} bytes, expected {bands * frames}")
        print(f"  envelope: {bands} bands x {frames} frames @ {frame_ms}ms "
              f"({frames * frame_ms / 1000:.1f}s)")

        received = bytearray()
        for chunk_index in range(header["chunkCount"]):
            send(sock, {"type": "getTransmissionAudioChunk", "index": index, "chunk": chunk_index})
            chunk_msg = stream.next_message(RECV_TIMEOUT_SECONDS)
            if chunk_msg is None:
                fail(f"no transmissionAudioChunk reply for chunk {chunk_index}")
            assert_equal(chunk_msg.get("type"), "transmissionAudioChunk", "chunk type")
            received.extend(base64.b64decode(chunk_msg["dataB64"]))
        assert_equal(len(received), expected_bytes, "reassembled audio length")
        if bytes(received[:4]) != b"OggS":
            fail(f"reassembled audio is not Ogg: {bytes(received[:4])!r}")
        print(f"  audio: {len(received)} bytes reassembled, OggS magic intact")
    else:
        skipped("transmissionManifest is empty -- the audio header, envelope and "
                "chunk-reassembly checks did NOT run. Expected until TASK-026 "
                "makes the engine generate audio.")

    # Negative 1: index out of range must be rejected before any file access.
    send(sock, {"type": "getTransmissionAudio", "index": 9999})
    err = stream.next_message(RECV_TIMEOUT_SECONDS)
    if err is None:
        fail("server went silent on an out-of-range transmission index")
    assert_equal(err.get("type"), "transmissionAudioError", "out-of-range yields an error")
    assert_equal(err.get("reason"), "index", "out-of-range reason")

    # Negative 2: a chunk with no matching header is recoverable, not fatal.
    send(sock, {"type": "getTransmissionAudioChunk", "index": 4242, "chunk": 0})
    err = stream.next_message(RECV_TIMEOUT_SECONDS)
    if err is None:
        fail("server went silent on a chunk with no transfer")
    assert_equal(err.get("type"), "transmissionAudioError", "orphan chunk yields an error")
    assert_equal(err.get("reason"), "noTransfer", "orphan chunk reason")

    # Negative 3: the connection must have survived all of the above.
    send(sock, {"type": "getSnapshot"})
    alive = stream.next_message(RECV_TIMEOUT_SECONDS)
    if alive is None:
        fail("server disconnected after transmissionAudioError (must stay connected)")
    assert_equal(alive.get("type"), "snapshot", "connection alive after transmissionAudioError")
    print("  negative cases: 3/3 errored without dropping the connection")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--password",
        default=os.environ.get("FALLOUT_COMPANION_PASSWORD", ""),
        help="the configured companion_password in fallout.cfg",
    )
    parser.add_argument(
        "--mutate-equipment",
        action="store_true",
        help="also run the inventory-action case, which equips a weapon in the live game "
             "(off by default: it changes the player's loadout)",
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
        test_get_map(sock)
        test_get_local_map(sock)
        test_post_handshake_hello_is_ignored(sock)
        # Keeps its own reader, so it must run after the strict first-line
        # readers above, alongside the other buffered case.
        test_transmission_audio(sock)
        # Last on this connection: it is the only case that keeps a read
        # buffer of its own, so anything it leaves behind cannot reach the
        # strict first-line readers above.
        if args.mutate_equipment:
            test_inventory_action_emits_update(sock)

    test_hello_first_message_drops(args.host, args.port)
    test_auth_wrong_password_drops(args.host, args.port, args.password)
    test_auth_empty_password_drops(args.host, args.port)
    test_auth_missing_password_field_drops(args.host, args.port)
    test_unknown_first_message_drops(args.host, args.port)
    test_server_still_listening(args.host, args.port, args.password)

    if SKIPPED:
        print(f"\nAll smoke tests passed, but {len(SKIPPED)} case(s) DID NOT RUN:")
        for message in SKIPPED:
            print(f"  - {message}")
        print("\nThose are gaps, not passes. A run whose interesting half skipped")
        print("looks identical to one that covered everything.")
    else:
        print("\nAll smoke tests passed.")


if __name__ == "__main__":
    main()
