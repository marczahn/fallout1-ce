# Companion App M3 — Feature Tickets

Derived from `docs/companion_app/plans/mvp-milestones.md` (M3) and
`docs/companion_app/plans/concept.md`. This document breaks M3 into
trackable tickets. It does not redefine the milestone; it makes it
actionable.

## Scope Statement

Deliver a network client that connects to the companion server
(current protocol: auth + hello/world handshake), completes the full
handshake, ingests one full `snapshot` into a local state cache,
applies incremental `update` messages as they arrive, and
auto-reconnects on disconnect with exponential backoff. The screen
shell transitions from static M2 placeholders to live values: the
header reflects `CONNECTING`, `OK`, `NO SIGNAL`, or `RECONNECTING`;
the body shows `CONNECTING…` until the handshake completes and then
either `OK` or `NO SIGNAL`. No section-specific content is rendered
in M3 (STATUS content lands in M4).

### Auth scope note (deviation from `mvp-milestones.md`)

The milestone document originally scoped auth out of M3 ("step-1
server has none"). The companion server has since advanced past
step 1 and **requires** `{"type":"auth","password":"…"}` as the first
message from any connected client. M3 therefore includes auth in the
handshake state machine. This is not scope creep: without it the
companion app cannot connect to the server that exists today.

## Out Of Scope (M3)

- No section-specific UI (STATUS, DATA, INVENTORY, MAP). The body
  shows only connection-state placeholders.
- No decoding of fields beyond `player.vitals` (`hp`, `maxHp`).
  Other snapshot payload kinds (`player.local_location`,
  `player.world_location`, `player.inventory`) are accepted but not
  stored — they will be consumed by later milestones.
- No section-switching logic. `SectionButton` events still emit (M1)
  but no section state machine consumes them in M3.
- No command channel (`cmd` messages). The app is read-only.
- No hardware backend behind `input/`. Keyboard emulation only.
- No threads, no async framework, no web stack.
- No new runtime dependencies beyond what `pygame` and the stdlib
  already provide.

## Cross-Cutting Constraints

- **Simple solution bias.** Raw TCP sockets with `socket.setblocking(False)`
  and `select.poll()`. No async framework, no HTTP, no WebSocket.
  Newline-delimited JSON is split by scanning for `\n` in a byte
  buffer — no streaming JSON parser is needed for messages that are
  always shorter than one TCP segment.
- **Single thread, single process.** `poll()` is called once per
  frame from the pygame main loop. The socket is non-blocking; every
  `recv`/`send` call returns immediately. No background workers.
- **Explicit state injection.** `AppState` is a plain dataclass owned
  by `app.py` and passed into `NetworkClient` at construction.
  No module-level singleton, no global mutable state. This keeps
  tests deterministic and makes the data-flow visible.
- **UI reads state through `app.py`, not directly.** The shell
  receives pre-computed strings. Future section UIs (M4+) may read
  `AppState` fields directly if needed, but no `ui/` module imports
  `state/` in M3.
- **State is in-memory only.** No persistence, no serialization.
  On disconnect the state may be reset or preserved for reconnect
  (preserved on disconnect; reset on reconnect).
- **Error tolerance.** A malformed JSON line, unexpected message
  type, `seq` gap, or socket error must never crash the app. The
  client logs the error (via `print` to stderr) and transitions to
  `RECONNECTING`.
- **Backoff is config-independent but sensible.** Exponential backoff
  from 1 s to 30 s with ±10 % jitter, hardcoded. Not configurable in
  M3.
- **No new config keys beyond `server.*`**. The existing
  `display.*`, `debug.*`, and `input.*` keys are unchanged.
- **The state machine is driven by received messages, not by
  wall-clock timeouts in M3.** If the server sends nothing after a
  state transition, the client waits indefinitely. Timeouts are a
  future improvement.

## Resolved Decisions

1. **Code location.**
   - `companion_app/companion_app/net/` — TCP client, framing,
     handshake, message dispatch.
   - `companion_app/companion_app/state/` — pure-data state cache.
   - No new top-level directories. These live inside the existing
     `companion_app/companion_app/` package.
   - `app.py` remains the wiring point. It imports both `net/` and
     `state/`.
2. **Package layout (additions only).**
   ```
   companion_app/
     companion_app/
       net/
         __init__.py       # public API: NetworkClient
         client.py         # socket lifecycle, poll(), send/recv
         framing.py        # newline-delimited JSON helpers
       state/
         __init__.py       # public API: AppState, getter helpers
         models.py         # dataclasses: ConnectionState, WorldInfo,
                           #   PlayerState
   ```
   Future milestones may split `net/` further (e.g. `net/handshake.py`)
   if the state machine grows; M3 keeps it in `client.py`.
3. **Config keys added in M3.** Three new keys under the existing
   warn-and-ignore pattern:
   - `server.host` (string, default `"127.0.0.1"`)
   - `server.port` (int, default `28080`)
   - `server.password` (string, **no default** — must be present
     and non-empty, otherwise `ConfigError` at startup)
   The `config.example.json` and `README.md` are updated to document
   them.
4. **Handshake state machine.**
   ```
   DISCONNECTED
       │ (connect() called)
       ▼
   CONNECTING
       │ (socket connected)
       ▼
   AWAITING_AUTH
       │ sent: {"type":"auth","password":"<cfg>"}
       │ (no server reply expected before hello; server transitions
       │  silently on correct password)
       ▼
   AWAITING_WORLD
       │ sent: {"type":"hello"}
       │ rx:   {"type":"world",...}
       ▼
   AWAITING_SNAPSHOT
       │ sent: {"type":"get_snapshot"}
       │ rx:   {"type":"snapshot",...}
       ▼
   READY ───────── receives updates, player_unavailable
       │
       ▼ (socket error or disconnect at any state)
   RECONNECTING ── exponential backoff ──→ CONNECTING
   ```
   The `AWAITING_AUTH` state exists so the client sends `auth` before
   `hello` and does not proceed until the socket has absorbed the
   `auth` bytes. The server does not reply to `auth` directly; it
   silently transitions to `AwaitingHello` on correct password, or
   drops the connection on bad password. The client detects the
   latter via a socket error on the next `send()` or `recv()` and
   reconnects.
5. **JSON framing.** Messages are UTF-8, one JSON object per line,
   terminated by `\n`. The framing layer:
   - `encode_line(obj) -> bytes` — serialize `obj` to compact JSON
     and append `\n`.
   - `read_line(buffer) -> (obj | None, remaining)` — scan buffer
     for `\n`, parse the complete line as JSON, return the parsed
     object and the remainder buffer.
   Accumulates partial data across `poll()` calls.
6. **Message dispatch.** Inbound JSON lines are dispatched by `type`
   field:
   - `"world"` → store `schemaVersion`, `game`, `playerAvailable`;
     transition to `AWAITING_SNAPSHOT`.
   - `"snapshot"` → extract `payload.player.vitals` → push to
     `AppState.player`; transition to `READY`.
   - `"update"` → dispatch by `kind`:
     - `"player.vitals"` → update `AppState.player.hp`,
       `AppState.player.maxHp`.
   - `"player_unavailable"` → set `AppState.player.available = False`.
   - Unknown `type` → log and ignore (do not disconnect).
   Messages without a `type` field or with invalid JSON are logged
   and trigger a disconnect-reconnect cycle.
7. **State cache shape.**
   ```python
   @dataclass
   class PlayerState:
       available: bool = False
       hp: int = 0
       max_hp: int = 0

   @dataclass
   class WorldInfo:
       schema_version: int = 0
       game: str = ""
       player_available: bool = False

   class ConnectionState(Enum):
       DISCONNECTED = 0
       CONNECTING = 1
       AWAITING_AUTH = 2
       AWAITING_WORLD = 3
       AWAITING_SNAPSHOT = 4
       READY = 5
       RECONNECTING = 6

   @dataclass
   class AppState:
       connection: ConnectionState = ConnectionState.DISCONNECTED
       world: WorldInfo | None = None
       player: PlayerState = field(default_factory=PlayerState)
   ```
8. **Reconnect backoff.**
   - Initial delay: 1 s
   - Multiplier: ×2 per attempt
   - Cap: 30 s
   - Jitter: ±10 % uniform random
   - Reset to 1 s on successful connection (`READY` reached)
   - Implemented as a simple timestamp-based gate in `poll()`:
     track `_reconnect_at` time, check `time.monotonic()` each frame.
9. **No state persistence across reconnect.** On a successful
   reconnect the server sends a fresh `world` and `snapshot`, which
   replace the entire cache. The old state is simply overwritten.
   On disconnect the state cache retains its last values (the UI
   briefly shows stale data behind the `RECONNECTING` overlay; this
   is acceptable).
10. **UI integration lives in `app.py`.** M3 adds a small helper
    function or inline logic to map `AppState` fields to the header
    status string and body text. No new `ui/` module is created for
    this mapping; `app.py` is already the per-frame wiring layer.
11. **Body placeholder in `READY` state.** When the connection is
    `READY` and the player is available, the body shows
    `"PIPBOY 2000 MK 1"` (the in-game device name). M4 replaces this
    with the STATUS section's HP display.
12. **`server.password` validation.** If the key is missing, empty,
    or not a string, `load_and_resolve_config()` raises `ConfigError`
    before pygame is initialized. This ensures the user gets a clear
    error without an orphan SDL window.
13. **Shutdown behavior.** When `app.py` exits (normal quit), it
    calls `net.cleanup()` which closes the socket (if open) and
    resets `AppState.connection` to `DISCONNECTED`. No lingering
    sockets.

## Top-Level Success Criteria (For Closing M3)

1. `pip install -e companion_app/` succeeds with the new `net/` and
   `state/` packages.
2. All M1 and M2 unit tests still pass (78 tests at M2 close).
3. M3 unit tests cover: framing roundtrip, state machine transitions
   (mock socket), backoff timing, player_vitals update,
   player_unavailable handling, malformed-JSON recovery,
   status-string mapping for all states.
4. App starts, connects to a running companion server (auth
   configured), completes handshake, header shows `OK`, body shows
   `PIPBOY 2000 MK 1`.
5. Wrong password in config: app does not reach `READY` — header
   stays `CONNECTING` or `RECONNECTING`.
6. Killing the server is detected: header flips to `RECONNECTING`,
   body returns to `CONNECTING…`, within one frame budget after the
   next failed read/write.
7. Restarting the server: app re-handshakes and returns to `OK`
   without crashing.
8. A `player_unavailable` message sets body to `NO SIGNAL` and
   header status to `NO SIGNAL`.
9. App exits cleanly via `Escape`, `q`, or window close — no orphan
   sockets, no traceback.
10. No new runtime dependency in `pyproject.toml` beyond `pygame`.
11. `server.password` missing or empty: startup aborts with a
    one-line error and non-zero exit code before pygame init.
12. Unknown `server.*` config keys warn-and-ignore (existing pattern).

---

## Tickets

### M3-T1 — Server Config Keys & State Cache Module

**Status:** todo

**Goal:** Add `server.host`, `server.port`, `server.password` to the
config loader and implement the pure-data `state/` cache that has no
dependency on networking or pygame.

**Scope:**
1. Extend `companion_app/companion_app/config.py`:
   - Add `SERVER_DEFAULT_HOST: str = "127.0.0.1"`,
     `SERVER_DEFAULT_PORT: int = 28080` module-level constants.
   - Add `server_host: str`, `server_port: int`,
     `server_password: str` fields to the `Config` dataclass.
   - In `_extract_fields()`: handle `server.top_key` with sub-keys
     `host`, `port`, `password`.
     - `host`: must be a non-empty string.
     - `port`: must be an int, 1–65535.
     - `password`: must be a non-empty string (raise `ConfigError`
       if missing, empty, or not a string).
   - Unknown sub-keys under `server` warn-and-ignore (existing
     pattern).
   - The `load_and_resolve_config()` entry point populates the new
     fields.
2. Create `companion_app/companion_app/state/` package:
   - `state/__init__.py`: module docstring, re-exports `AppState`,
     `ConnectionState`, `WorldInfo`, `PlayerState` from `models`.
   - `state/models.py`:
     - `ConnectionState(Enum)` — `DISCONNECTED`, `CONNECTING`,
       `AWAITING_AUTH`, `AWAITING_WORLD`, `AWAITING_SNAPSHOT`,
       `READY`, `RECONNECTING`.
     - `WorldInfo` dataclass — `schema_version: int`, `game: str`,
       `player_available: bool`.
     - `PlayerState` dataclass — `available: bool`, `hp: int`,
       `max_hp: int`.
     - `AppState` dataclass — `connection: ConnectionState`,
       `world: WorldInfo | None`, `player: PlayerState`.
3. `AppState` exposes no methods beyond the dataclass fields.
   Mutation is direct field assignment (single-threaded, no locking).
4. The `state/` package imports nothing from `net/`, `pygame`, or
   any UI module. Its dependency tree is: stdlib dataclasses + enum
   only.
5. Update `app.py` to create an `AppState` instance at startup and
   pass it into `NetworkClient` (which does not exist yet; the
   construction site is stubbed with a comment).

**Acceptance:**
- Config with `{"server": {"host": "127.0.0.1", "port": 28080,
  "password": "hunter2"}}` produces correct `Config` fields.
- Missing `server` block uses defaults for host/port but raises
  `ConfigError` for missing password.
- Empty `server.password` raises `ConfigError`.
- `server.port` as a string raises `ConfigError`.
- `server.port` out of range (0, 65536) raises `ConfigError`.
- `AppState` default: `connection = DISCONNECTED`,
  `player.available = False`, `world = None`.
- `PlayerState(hp=30, maxHp=40)` can be constructed and read.
- `ConnectionState.READY` is a distinct enum member.
- `state/` is importable without `pygame` initialized.
- All existing tests still pass.

**Tests:**
- Config: all three keys set correctly
- Config: password missing → ConfigError
- Config: password empty → ConfigError
- Config: port as string → ConfigError
- Config: port out of range → ConfigError
- Config: host empty → ConfigError
- Config: unknown server sub-key warns
- Config: unknown server sub-key still produces valid Config
- `AppState` defaults
- `PlayerState` construction and field access
- `ConnectionState` all members

**Notes:**
- The existing `_extract_fields()` function dispatches on top-level
  keys. The `server` key follows the same pattern as `display`,
  `input`, and `debug`.
- Do not create `net/` or `NetworkClient` in this ticket. That is
  M3-T2.

---

### M3-T2 — Net Module: TCP Client, Framing, Handshake & Message Dispatch

**Goal:** Non-blocking TCP client that connects to the companion
server, completes the auth + handshake, receives incoming messages,
and pushes decoded data into the `AppState` cache.

**Scope:**
1. Create `companion_app/companion_app/net/` package:
   - `net/__init__.py`: module docstring, re-exports `NetworkClient`.
   - `net/framing.py`:
     - `encode_line(obj: dict) -> bytes`: serialize `obj` to compact
       JSON (`separators=(",", ":")`, `ensure_ascii=True`), append
       `\n`, encode to UTF-8.
     - `read_line(buffer: bytearray) -> tuple[dict | None, bytearray]`:
       scan for `\n`; if found, extract the line, parse JSON, return
       `(parsed_dict, remainder)`. If no `\n`, return `(None, buffer)`.
     - Both functions are pure — no socket I/O, no side effects.
   - `net/client.py`:
     - `class NetworkClient`:
       - `__init__(self, host: str, port: int, password: str,
         state: AppState)` — store config and state ref.
       - `poll(self) -> None` — called once per frame; drives the
         entire lifecycle (connect, send, receive, reconnect).
       - `cleanup(self) -> None` — close socket, reset state to
         `DISCONNECTED`.
       - Private helpers:
         - `_connect()` → initiate non-blocking connect.
         - `_on_connected()` → send `auth` line, move to
           `AWAITING_AUTH`.
         - `_send_line(obj)` → encode and queue on write buffer.
         - `_flush_write()` → send queued bytes from write buffer.
         - `_try_recv()` → read available bytes into read buffer.
         - `_process_read_buffer()` → call `read_line()` in a loop,
           dispatch each complete message.
        - `_dispatch(msg)` → switch on `msg.get("type")`:
          - `"world"` → parse `schemaVersion`, `game`,
            `playerAvailable` into `state.world`; send
            `get_snapshot` → `AWAITING_SNAPSHOT`.
          - `"snapshot"` → set `state.player.available =
            msg.get("playerAvailable", False)`. If available,
            extract `payload["player.vitals"]["hp"]` and
            `["maxHp"]` into `state.player`. If not available,
            leave `state.player.hp`/`maxHp` at defaults.
            → `READY`.
          - `"update"` → if `msg.get("playerAvailable", True)`
            is false, set `state.player.available = False`.
            Otherwise dispatch by `msg["kind"]`:
            - `"player.vitals"` → update `state.player.hp`,
              `state.player.maxHp`; set `state.player.available
              = True`.
            - unknown kind → log and ignore.
          - `"player_unavailable"` → `state.player.available =
            False`.
          - default → `print` warning, ignore.
         - `_schedule_reconnect()` → compute next reconnect time
           with exponential backoff, set `state.connection =
           RECONNECTING`.
         - `_check_reconnect()` → if `RECONNECTING` and
           `time.monotonic() >= _reconnect_at`, try `_connect()`.
2. Socket lifecycle:
   - Use `socket.socket(socket.AF_INET, socket.SOCK_STREAM)`.
   - `socket.setblocking(False)`.
   - `connect_ex()` returns `EINPROGRESS` (or 0 if already
     connected — rare on localhost but handle it).
   - Poll with `select.poll()` or `select.select()` with
     zero-second timeout to check writability (connected) or
     readability (data / error).
   - On error at any point: close socket, `_schedule_reconnect()`.
3. Read buffer: a `bytearray` accumulated across `poll()` calls.
4. Write buffer: a `bytearray` or `list[bytes]` of queued outgoing
   lines. Drained in `_flush_write()`.
5. Backoff implementation:
   - `_reconnect_delay: float` starts at 1.0.
   - On each `_schedule_reconnect()`: `_reconnect_at =
     time.monotonic() + _reconnect_delay + jitter`.
   - After scheduling: `_reconnect_delay = min(_reconnect_delay * 2,
     30.0)`.
   - On reaching `READY`: `_reconnect_delay = 1.0`.
 6. Error handling:
    - `socket.error`, `OSError` → log via `print(f"…",
      file=sys.stderr)` → `_schedule_reconnect()`.
    - `json.JSONDecodeError` on a complete line: log and skip that
      line (do not disconnect). The buffer advances past the
      offending `\n`.
    - Messages with no `type` field or null/empty `type`: log and
      skip.
    - Messages with `type` that is not handled: log and ignore.
    - Expected-missing fields inside `_dispatch()` are handled
      locally with `.get()` or `try`/`except` — they must not
      propagate to the top-level error handler.

**Acceptance:**
- `poll()` with no socket and no backoff pending: returns
  immediately, does nothing.
- Successful connection sequence:
  `poll()` → `_connect()` → writable → send `auth` →
  `AWAITING_AUTH` → send `hello` → `AWAITING_WORLD` →
  receive `world` → parse → send `get_snapshot` →
  `AWAITING_SNAPSHOT` → receive `snapshot` → parse → `READY`.
- `update` with `kind: "player.vitals"` updates
  `state.player.hp` and `state.player.maxHp`.
- `player_unavailable` sets `state.player.available = False`.
- Socket error during any state: transitions to `RECONNECTING`,
  backoff timer starts.
- Backoff: 1 s → 2 s → 4 s → … → 30 s → stays at 30 s.
- After backoff expires: attempts `_connect()` → `CONNECTING`.
- Malformed JSON on a line: logs warning, moves to next line,
  socket stays open.
- `cleanup()` closes the socket and sets state to `DISCONNECTED`.

**Tests:**
- `encode_line` / `read_line` roundtrip for single object
- `read_line` with partial line returns `(None, buffer)`
- `read_line` with multiple lines returns first object
- State machine transitions via `_dispatch()` in isolation
- Full mock integration: inject bytes via a fake recv, assert
  state transitions and outgoing bytes
- `NetworkClient` with a mock socket that fails on connect →
  `CONNECTING` → `RECONNECTING` with backoff
- `player_unavailable` sets `state.player.available = False`
- `update` with unknown `kind` is ignored
- `cleanup()` resets connection to `DISCONNECTED`

**Notes:**
- Tests use `unittest.mock` to simulate sockets. No real network in
  unit tests. The manual validation ticket (M3-T4) exercises a real
  server.
- The `AWAITING_AUTH` state exists because the client must not send
  `hello` before `auth` has been written to the socket. On a
  non-blocking socket, `send()` may return `EAGAIN`; the client
  queues the bytes and retries on the next `poll()` until all
  `auth` bytes are sent. Only then does it transition to
  `AWAITING_WORLD` and send `hello`.
- The server does not reply to `auth` with an explicit
  acknowledgment. A bad password causes the server to drop the
  connection silently, which the client detects as a socket error
  on the next `poll()`.

---

### M3-T3 — UI Integration: Live Connection Status in Shell

**Goal:** Wire `NetworkClient` into `app.py`'s main loop. Replace
static M2 shell strings with live values read from `AppState`.
Shut down the network client cleanly on exit.

**Scope:**
1. Update `companion_app/companion_app/app.py`:
   - Import `NetworkClient` from `companion_app.net`.
   - Import `AppState` from `companion_app.state`.
   - After config validation & font loading, construct:
     ```python
     state = AppState()
     net = NetworkClient(
         host=config.server_host,
         port=config.server_port,
         password=config.server_password,
         state=state,
     )
     ```
   - Each frame, **before** rendering:
     ```python
     net.poll()
     ```
   - After `net.poll()`, compute header status and body text from
     `state`:
     ```python
     status = _connection_status(state)
     body = _body_text(state)
     ```
   - Pass `status` and `body` to `draw_shell(virtual, SECTION_NAME,
     status, body)`. Remove the old `SECTION_NAME`, `CONNECTION_STATUS`,
     `BODY_PLACEHOLDER` constants.
   - On exit (`running = False`): call `net.cleanup()`.
2. Add helper functions at module level in `app.py`:
   - `_connection_status(state: AppState) -> str`:
     | `state.connection` | Result |
     |---|---|
     | `DISCONNECTED` | `"--"` |
     | `CONNECTING` | `"CONNECTING"` |
     | `AWAITING_AUTH` | `"CONNECTING"` |
     | `AWAITING_WORLD` | `"CONNECTING"` |
     | `AWAITING_SNAPSHOT` | `"CONNECTING"` |
     | `READY` + `state.player.available` | `"OK"` |
     | `READY` + not `state.player.available` | `"NO SIGNAL"` |
     | `RECONNECTING` | `"RECONNECTING"` |
   - `_body_text(state: AppState) -> str`:
     | `state.connection` | Result |
     |---|---|
     | Not `READY` | `"CONNECTING…"` |
     | `READY` + `state.player.available` | `"PIPBOY 2000 MK 1"` |
     | `READY` + not `state.player.available` | `"NO SIGNAL"` |
3. Update `SECTION_NAME` usage: the header section name stays
   `"STATUS"` in M3 (no section switching yet). Keep a simple
   `SECTION_NAME = "STATUS"` constant.
4. Remove the `BODY_PLACEHOLDER = "PIPBOY 2000"` constant and the
   `CONNECTION_STATUS = "--"` constant (they are now computed from
   state).
5. Shutdown: call `net.cleanup()` after the main loop exits and
   before `pygame.quit()`. Order: stop net → clean up overlays →
   pygame quit.
6. The error handling in `main()` already catches `ConfigError` and
   `FontLoadError`. No new exception class is needed for net errors
   (they are handled inside `NetworkClient` and surfaced through
   `state.connection`).

**Acceptance:**
- App starts, `state.connection = DISCONNECTED`, header shows
  `STATUS` `--`, body shows `CONNECTING…`.
- On first `poll()` tick, connection attempt begins, header shows
  `STATUS` `CONNECTING`, body shows `CONNECTING…`.
- On successful handshake, header flips to `STATUS` `OK`, body
  shows `PIPBOY 2000 MK 1`.
- Killing the server: header flips to `STATUS` `RECONNECTING`, body
  returns to `CONNECTING…` within one frame budget after next failed
  `recv()`.
- `player_unavailable` received: header shows `NO SIGNAL`, body
  shows `NO SIGNAL`.
- App exits cleanly: `net.cleanup()` called, socket closed, no
  traceback.
- The `_connection_status()` and `_body_text()` functions are
  deterministic pure functions tested in isolation.
- All M1 and M2 tests still pass (78 tests).
- No `import` of `state/` or `net/` inside `ui/shell.py`.

**Tests:**
- `_connection_status(DISCONNECTED)` → `"--"`
- `_connection_status(CONNECTING)` → `"CONNECTING"`
- `_connection_status(AWAITING_AUTH)` → `"CONNECTING"`
- `_connection_status(AWAITING_WORLD)` → `"CONNECTING"`
- `_connection_status(AWAITING_SNAPSHOT)` → `"CONNECTING"`
- `_connection_status(READY, available=True)` → `"OK"`
- `_connection_status(READY, available=False)` → `"NO SIGNAL"`
- `_connection_status(RECONNECTING)` → `"RECONNECTING"`
- `_body_text(DISCONNECTED)` → `"CONNECTING…"`
- `_body_text(READY, available=True)` → `"PIPBOY 2000 MK 1"`
- `_body_text(READY, available=False)` → `"NO SIGNAL"`

**Notes:**
- These helper functions are defined in `app.py` because they are
  the wiring layer. They are not a public API; they are tested by
  importing `app` module's private functions in the test file.
- The `CONNECTING…` ellipsis character is `\u2026` (HORIZONTAL
  ELLIPSIS), matching the milestone doc's `CONNECTING…` spelling.
- No new `ui/` module is created for this mapping. `app.py` is
  already the consumer of state and the caller of `draw_shell`.
  If the mapping logic grows (M5+), it can be extracted into a thin
  `ui/connection.py` helper later without changing the architecture.

---

### M3-T4 — Manual Validation

**Status:** todo

**Goal:** Run the companion app against the companion server and
verify all success criteria pass. Document results.

**Scope:**
1. Prerequisites:
   - Build and run the Fallout 1 CE engine with the companion server
     enabled (both `companion_bind` and `companion_password` set in
     `fallout.cfg`).
   - Ensure the companion app can reach the server (same host, correct
     port and password).
2. Run all unit tests from the `companion_app/` directory:
   ```
   .venv/bin/python -m unittest discover -s tests
   ```
   Record the count and runtime.
3. Manual scenarios to execute:
   - **C1 — Clean connect:** Start the game (server active), start
     the companion app. Verify header shows `CONNECTING` → `OK`
     within ~1 s. Body shows `PIPBOY 2000 MK 1`.
   - **C2 — Wrong password:** Configure a wrong password. App
     connects but never reaches `READY`. Header stays `CONNECTING`
     or shows `RECONNECTING` cyclically.
   - **C3 — Server kill:** While `OK`, kill the game process. Header
     flips to `RECONNECTING`, body to `CONNECTING…` within one frame
     budget (~17 ms) of the next failed `recv()`.
   - **C4 — Server restart:** Restart the game. App detects
     connectivity, re-handshakes, returns to `OK`. No restart of
     the companion app needed.
   - **C5 — `player_unavailable`:** Start the app while the game is
     at the main menu (before character load). Body shows
     `CONNECTING…` until handshake completes, then `NO SIGNAL`.
     Load a character: body switches to `PIPBOY 2000 MK 1`.
   - **C6 — HP update:** While `OK`, watch HP in the game change
     (take damage, heal). Verify the state cache updates (M4 will
     render this; in M3, assert via debug logging or a print statement
     that `update` messages are received and `state.player.hp` is
     current).
   - **C7 — Malformed JSON resilience:** (If a test stub or proxy is
     available) inject a malformed line. App logs a warning and
     continues without crashing.
   - **C8 — Exit:** Press `q`, `Escape`, or close the window. App
     exits with return code 0. No orphan socket (verified via
     `ss`/`netstat` or absence of error).
   - **C9 — Missing password config:** Run app without
     `server.password`. Verify startup aborts with a one-line error
     and non-zero exit code before pygame init.
4. Update the config.example.json and README with the three new
   `server.*` keys.
5. Create example config files in `examples/`:
   - `m3-default.json` (or update `m2-default.json`).
6. Write a brief validation log at the bottom of this ticket file
   with PASS/FAIL per criterion.

**Acceptance:**
- All 12 top-level success criteria from this document are verified
  and documented as PASS in the validation log.
- All unit tests pass.
- No regressions in M1 or M2 behavior (debug overlay, CRT overlay,
  input dispatch, etc.).

**Notes:**
- C1–C9 correspond to the Top-Level Success Criteria numbered 2–11
  in this document. C1 (pip install) and C12 (unknown keys) are
  covered by existing tests.
- M3-T4 does not require automated integration tests. The state
  machine, framing, and dispatch are covered by M3-T2 unit tests.
  Manual validation is appropriate for the real-server scenarios.
- Document the Fallout 1 CE build path and server-enabling config so
  future contributors can reproduce the validation.

---

## Suggested Ordering

M3-T1 (config + state) → M3-T2 (net client) → M3-T3 (UI integration)
→ M3-T4 (manual validation). M3-T1 is a prerequisite for M3-T2.
M3-T3 depends on both M3-T1 (state) and M3-T2 (net client).
M3-T4 depends on all three implementation tickets.
