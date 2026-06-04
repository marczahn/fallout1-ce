# Companion Server Step 1 Plan

## Goal

Implement the first minimal companion server for Fallout Community Edition with these constraints:

- Optional in-process TCP server.
- No extra thread.
- Non-blocking socket handling from the main game loop.
- One client at a time.
- Newline-delimited JSON protocol.
- Handshake:
  - client sends `{"type":"hello"}`
  - server replies `{"type":"world","schema_version":1,"game":"fallout1-ce"}`
  - client requests a full snapshot with `{"type":"get_snapshot"}`
  - server replies with a full snapshot
- Initial exposed data:
  - player current HP
  - player maximum HP
- Periodic sampled updates:
  - every 500 ms
  - only send on change

## Non-Goals For Step 1

- No UDP discovery.
- No HTTP or WebSocket layer.
- No command handling from the client beyond requesting a snapshot.
- No multi-client support.
- No inventory/map/combat serialization yet.
- No generalized event bus inside the engine.

## Design Principles

1. Keep networking isolated from gameplay code.
2. Read game state through narrow helper functions instead of spreading socket logic across engine files.
3. Use time-based scheduling, not frame-count scheduling.
4. Prefer sampled state replication first; add semantic events later where the engine gives clean hook points.
5. Fail closed: malformed input or protocol violations close the client connection.

## Proposed File Layout

- `src/companion_server.h`
- `src/companion_server.cc`
- `src/companion_protocol.h`
- `src/companion_protocol.cc`
- `src/companion_snapshot.h`
- `src/companion_snapshot.cc`

Possible later files, not needed in step 1:

- `src/companion_diff.h`
- `src/companion_diff.cc`

## Responsibilities By Module

### `companion_server`

Owns runtime server state and socket lifecycle.

Responsibilities:

- create/listen on TCP socket
- accept one client
- keep socket non-blocking
- read inbound bytes
- split inbound messages by newline
- enforce handshake state machine
- queue outbound messages
- flush outbound bytes without blocking
- run periodic scheduling for automatic update messages

Public API proposal:

```cpp
namespace fallout {

bool companionServerInit();
void companionServerExit();
void companionServerTick(unsigned int now);

} // namespace fallout
```

Configuration can be hardcoded for step 1, then moved into config later:

- enabled: `true`
- bind host: `0.0.0.0` (all interfaces; see security note)
- port: `28080`
- sample interval: `500 ms`

**Security note.** Binding to `0.0.0.0` exposes the server to the local network. The protocol has no authentication in step 1, so any device on the same network can read game state. This is acceptable for step 1 development and LAN testing. A step 2 task is to add authentication and/or make the bind host configurable, defaulting to `127.0.0.1`.

### `companion_protocol`

Converts internal structs into newline-delimited JSON strings and parses the minimal client input.

Responsibilities:

- parse only `{"type":"hello"}` for step 1
- parse only `{"type":"get_snapshot"}` for step 1
- build `world`
- build `snapshot`
- build `update`
- build `player_unavailable`

For step 1, parsing can stay intentionally narrow:

- trim trailing newline
- require a small exact-shape JSON object
- reject anything else

This does not need a full JSON library in step 1 if we keep input parsing tiny and output generation controlled.

### `companion_snapshot`

Reads the engine state and returns a normalized companion-facing snapshot.

Initial data model:

```cpp
namespace fallout {

struct CompanionPlayerSnapshot {
    int hp;
    int maxHp;
};

struct CompanionSnapshot {
    bool hasPlayer;
    CompanionPlayerSnapshot player;
};

CompanionSnapshot companionCollectSnapshot();

} // namespace fallout
```

Data sources:

- `obj_dude`
- `critter_get_hits(obj_dude)`
- `stat_level(obj_dude, STAT_MAXIMUM_HIT_POINTS)`

If `obj_dude` is not available yet, `hasPlayer` should be `false`.

## Runtime State Machine

Per server:

- `disabled`
- `listening`
- `client_connected`
- `client_ready`

Per client connection:

- `awaiting_hello`
- `ready`

Protocol behavior:

1. Client connects.
2. Server waits silently for first valid line.
3. If first message is `{"type":"hello"}`, reply with `world`.
4. Enter `ready`.
5. When the client sends `{"type":"get_snapshot"}`, send one full snapshot.
6. Every 500 ms, sample snapshot and send `update` if changed.
7. On parse error, unknown first message, socket error, or disconnect, drop client and continue listening.

## Message Schema

All messages are UTF-8 JSON, one object per line.

### Client to server

Handshake:

```json
{"type":"hello"}
```

Snapshot request:

```json
{"type":"get_snapshot"}
```

### Server to client

Handshake response:

```json
{"type":"world","schemaVersion":1,"game":"fallout1-ce","playerAvailable":true}
```

Full snapshot:

```json
{"type":"snapshot","seq":1,"playerAvailable":true,"data":{"player":{"hp":32,"maxHp":40}}}
```

Incremental update:

```json
{"type":"update","entity":"player","seq":2,"playerAvailable":true,"data":{"hp":28}}
```

Player-absent event (one-shot on the present→absent transition):

```json
{"type":"player_unavailable","seq":3,"playerAvailable":false}
```

Notes:

- All JSON field names use camelCase (e.g. `schemaVersion`, `playerAvailable`, `maxHp`).
- `type` values themselves stay lowercase or snake_case (`world`, `snapshot`, `update`, `player_unavailable`, `hello`, `get_snapshot`) for protocol-level identifiers.
- Include `seq` on every post-handshake server message.
- Include `playerAvailable` on every server message. It reflects the game state at the moment the message is built.
- `snapshot` contains the full synchronized model across all supported domains.
- `snapshot` does not include `entity`.
- `update` always includes `entity`.
- `update.data` is partial and scoped only to that entity.
- Step 1 updates can send just `hp` when that is the only changed value.
- When `playerAvailable` is `false`, the values inside `snapshot.data.player`
  and `update.data` are zeroed (`hp:0, maxHp:0`) rather than preserved
  from the last known state. The companion client is expected to key
  off `playerAvailable` rather than reading the values directly. A
  step 2 task may revisit this and preserve last-known values.

## Integration Points

### Initialization

Initialize after core game state is ready enough for `obj_dude` sampling to eventually succeed, but before entering the main loop.

Candidate place:

- `main_init_system(...)` in `src/game/main.cc`

Tasks:

- call `companionServerInit()`
- tolerate init failure without aborting the game
- log failure through existing debug facilities

### Tick integration

The companion server tick must run on every frame the engine is
processing input or background state, regardless of which engine loop
is currently active. The engine has many focused loops that block
`main_game_loop` — main menu, intro movie, combat, dialogs, inventory,
pip-boy, character sheet, save/load, options, world map, and so on.
The tick site is therefore placed in the engine's central background
processor, not in `main_game_loop` directly.

The single tick site is `process_bk()` in `src/plib/gnw/input.cc:215`.
`process_bk()` is called from:

- `get_input()` at `src/plib/gnw/input.cc:194` — the central input
  poll, invoked by every focused loop in the engine.
- `combat_turn_run` in `src/game/combat.cc` — the AI-turn frame loop.
- `combatai.cc` (twice) — internal AI decision points.
- `intlib.cc` script processing — the script interpreter's frame tick.
- `pause_for_tocks` at `src/plib/gnw/input.cc:650` — the engine's
  time-based wait helper.

This covers every state we have identified: main game loop, main menu,
intro movie, combat (both AI and player turns), dialogs, inventory,
pip-boy, character sheet, save/load, options, world map, and any
future focused loop the engine adds. There is no per-loop spread; one
call covers all paths.

The unfocused-window busy-wait in `GNW95_lost_focus()` at
`src/plib/gnw/input.cc:1209-1226` does **not** call `process_bk`; it
runs `GNW95_process_message()` and `idle_func()` in a tight loop while
the window is unfocused. To keep the server responsive in that case,
the companion server installs a chained `IdleFunc` via the existing
`set_idle_func` / `get_idle_func` API in `src/plib/gnw/input.h:45-46`.
The wrapper is `companionIdleHook` in `src/companion_server.cc`. It:

1. calls the previous `idle_func` first (preserving the `SDL_Delay(125)`
   throttle so the busy-wait does not burn CPU);
2. then calls `companionServerTick(compat_timeGetTime())`.

State for the hook is `gOriginalIdleFunc` and `gIdleHookInstalled` in
`src/companion_server.cc`. `companionServerExit` restores the previous
`idle_func`.

The two tick sites (`process_bk` while focused, `companionIdleHook`
while unfocused) never run concurrently — same thread, mutually
exclusive — so there is no reentrancy or state-coupling concern. The
tick is non-blocking, has no window-focus dependency, and is safe to
call from any of these contexts.

Empirically verified: the server responds to a Python `nc`-style
client in every state, including focused intro, focused main menu,
combat, in-game dialogs/menus, and unfocused window. The previous
plan's claim of "empirically verified for intro / main menu" was
limited to the unfocused-window case; that limitation is now closed.

### Shutdown

Candidate place:

- `main_exit_system()` in `src/game/main.cc`

Tasks:

- call `companionServerExit()`

### Debug log

The engine's `debug_register_env()` at `src/plib/gnw/debug.cc:82`
exists but is not called from any engine init path, so all
`debug_printf` calls are silently dropped by default. The companion
server's `companionServerInit` calls it once via the
`companionEnableDebugLog` helper in `src/companion_server.cc:419-422`.
This makes `DEBUGACTIVE=log` actually produce a `debug.log` during
development.

A pre-existing typo in `debug_register_log` at `src/plib/gnw/debug.cc:58`
also prevented the log file from being opened even after
`debug_register_env` was called (the condition was
`(mode[0] == 'w' && mode[1] == 'a') && mode[1] == 't'`, which can
never be true for any string). This has been fixed in step 1 so the
shim is now sufficient. The shim itself can be removed once a proper
global debug init path is in place.

## Platform Strategy

Step 1 target:

- Linux first

Implementation approach:

- use BSD sockets on non-Windows
- either:
  - stub out Windows support initially, or
  - implement a small compatibility layer for both POSIX and WinSock now

Recommendation:

- implement POSIX first
- keep socket code structurally isolated so Windows support can be added cleanly later

Reason:

- the immediate developer workflow is Linux + VS Code
- step 1 should minimize scope

## Error Handling

Server init failures should not break game launch.

Examples:

- bind failure
- listen failure
- malformed client hello
- malformed `get_snapshot`
- send/recv error

Behavior:

- log to `debug.log` if debug output is enabled
- disable or reset only the companion connection
- leave game runtime untouched

## Logging

Use existing debug infrastructure for low-volume lifecycle logs:

- server started
- client connected
- hello accepted
- snapshot requested
- snapshot sent
- update sent
- client disconnected
- socket error

Avoid per-tick spam.

## Validation Strategy

### Manual runtime validation

1. Launch game.
2. Confirm no gameplay regression when no client connects.
3. Connect using `nc` or a tiny test client. The server is
   responsive in every state: main menu, intro movie, combat, in-game
   menus (dialog, inventory, pip-boy, character sheet, etc.), and the
   unfocused-window case. See "Tick integration" under Integration
   Points.
4. Send `{"type":"hello"}` followed by newline.
5. Verify `world` response.
6. Send `{"type":"get_snapshot"}` followed by newline.
7. Verify snapshot response.
8. Change HP in-game (focus the game window briefly to take damage /
   heal, then return to the client window).
9. Verify update arrives within 500 ms.
10. Send invalid first message and verify connection closes cleanly.

### Development helper

Useful test command:

```bash
nc 127.0.0.1 28080
```

Then send:

```json
{"type":"hello"}
```

Then send:

```json
{"type":"get_snapshot"}
```

## Risks

### 1. Old-engine state availability

`obj_dude` may be null during early startup, menu screens, or transitions.

Mitigation:

- snapshot collector must tolerate missing player state
- avoid assuming gameplay is active at all times

### 2. Socket portability

POSIX-first implementation will not automatically support Windows.

Mitigation:

- isolate networking details
- add platform abstraction in step 2 if needed

### 3. Main-loop interference

Blocking I/O or expensive serialization could hitch the game.

Mitigation:

- non-blocking sockets only
- tiny payloads
- one client only

### 4. Protocol drift

Future additions may break early clients.

Mitigation:

- include `schema_version`
- keep message types explicit

### 5. Player availability on menus and world map

`obj_dude` is set with placeholder data (e.g., 30/30 HP from the
character-creation defaults) even when the game is at the main menu,
intro movie, or world map. The current `hasPlayer` check is just
`obj_dude != nullptr`, so the server reports `playerAvailable: true`
and the HP from these non-gameplay states. A client that ignores
`playerAvailable` and reads `data.player.hp` directly will see
placeholder data when the player is at the main menu or on the world
map.

Mitigation: defer. The natural fix is to combine `obj_dude != nullptr`
with `!in_main_menu` and `map_get_index_number() != -1`, but the
world map also reports `map_get_index_number() == -1`, so that check
is not sufficient. A step 2 task is to disambiguate "player is in a
real map" from "player placeholder is loaded" using a combination of
engine signals.

## Step 1 Deliverables

1. TCP listener on `0.0.0.0:28080` (all interfaces; no auth in step 1).
2. One-client handshake with `hello` -> `world`.
3. Client-requested HP snapshot via `get_snapshot`.
4. Sampled HP updates every 500 ms on change.
5. Tick integration via `process_bk()` plus the existing idle hook.
   Covers every focused engine loop and the unfocused-window busy-wait.
   No additional threads.
6. Basic lifecycle logging to `debug.log`.

## Out Of Scope For Step 2 Discussion

When step 1 is working, the next planning topic should be deciding whether step 2 adds:

- position/map updates
- inventory snapshots
- derived inventory events
- LAN discovery via UDP
- incoming commands
- authentication and configurable bind host (defaulting to `127.0.0.1`)
- a more accurate "is the player really playing" signal that
  disambiguates main menu, intro, world map, and real-map play
