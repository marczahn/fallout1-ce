# Companion Server Step 1 — Feature Tickets

Derived from `docs/plans/companion-server-step-1.md`. This document breaks the plan into trackable tickets. It does not redefine the plan; it makes it actionable.

## Scope Statement

Deliver a localhost-only, single-client, non-blocking TCP server integrated into the main game loop that exposes player HP via newline-delimited JSON. Game remains authoritative and must not be observably affected by the server's presence or absence.

## Out Of Scope (Step 1)

Carried over from the plan, restated as a hard wall:

- No UDP discovery.
- No HTTP, no WebSocket.
- No incoming client commands beyond `get_snapshot`.
- No multi-client support.
- No inventory, map, combat, or position data.
- No generalized engine event bus.
- No background threads.
- No new third-party dependencies.
- No Windows socket support (POSIX first; keep code isolated for step 2).

## Cross-Cutting Constraints

- **Simple solution bias.** Hand-roll the minimal JSON. Do not pull in a JSON library for two server messages and two client messages.
- **Built-in functionality preferred.** POSIX BSD sockets directly. Existing `debug_printf` for logging. Existing `compat_timeGetTime()` for scheduling. No new abstractions invented "for the future."
- **Third-party libraries only if they clearly pay for themselves in step 1.** They do not here. Reject any PR that adds one.
- **Server init failure must not abort the game.** On any socket setup failure, the server transitions to `disabled` and `companionServerInit` still returns success.
- **No per-tick churn.** No allocation in the steady state path. No log spam. Sampling and serialization cost must be negligible vs. frame time.
- **Fail closed.** Malformed input, unknown first message, or socket error drops the client and returns the server to `listening`. Game state untouched.
- **Localized diff.** Touch only the three new files, the three `main.cc` integration points, the existing `set_idle_func` hook for the background tick, the two combat loops in `src/game/combat.cc`, the build system entry. Nothing else.
- **No background threads.** The background tick hook is **not** a thread. It is a function pointer invoked from the existing `GNW95_lost_focus` busy-wait on the main thread, chained in front of the default `SDL_Delay(125)` throttle.

## Hidden Assumptions (Verified)

These came from the plan. They are real in this repo:

- `compat_timeGetTime()` exists (`src/platform_compat.cc:232`), returns `unsigned int`. 500 ms cadence is trivially safe; wrap-around is irrelevant.
- `obj_dude` declared at `src/game/object.h:26`, defined at `src/game/object.cc:260`.
- `critter_get_hits` declared at `src/game/critter.h:64`.
- `stat_level` declared at `src/game/stat.h:18`.
- `debug_printf` declared at `src/plib/gnw/debug.h:14`. Use it as-is; do not add a new logging facility.
- Integration points `main_init_system`, `main_game_loop`, `main_exit_system` live in `src/game/main.cc:224`, `:311`, `:245`.

## Resolved Decisions

1. **Slow consumer policy.** Drop the client when the outbound buffer exceeds **256 KiB**. Tolerant of slow networks; bounded memory.
2. **`seq` start value.** `world` has no `seq`. The first `snapshot` or `update` after `world` is `seq=1`. Counter increments per post-handshake send.
3. **Missing-player behavior.** Emit a one-shot `player_unavailable` event on the transition from "player present" to "player absent." On the transition back to "player present," let the next 500 ms sample's normal change detection fire a regular `update` (no separate `player_available` event). Initial state is "absent," so the first load does not emit `player_unavailable`.
4. **Build system entry.** Single executable target `fallout-ce` defined at `CMakeLists.txt:5`. Sources listed explicitly in `target_sources` (`CMakeLists.txt:43`). Three new `.cc` files are added as three lines in alphabetical order, before the first `src/game/...` entry.
5. **`seq` scope.** Per-connection counter. Resets on connect/disconnect.

## Top-Level Success Criteria (For Closing Step 1)

1. Game starts, runs, and shuts down identically with the server enabled and no client connected.
2. `nc 127.0.0.1 28080` from another shell succeeds.
3. `{"type":"hello"}` → `{"type":"world",...}` then server is in `ready`.
4. `{"type":"get_snapshot"}` → one `snapshot` with `player.hp` and `player.maxHp` matching in-game values.
5. Damaging or healing the player in-game produces an `update` on the wire within 500 ms.
6. Disconnecting the client (clean or unclean) leaves the game running and the server ready to accept a new client.
7. Sending any non-`hello` first message causes the client to be dropped; the game keeps running.
8. All six plan deliverables are demonstrably met.

---

## Tickets

### T1 — Engine Integration Points

**Status:** done

**Goal:** Wire the companion server into the engine with no behavior change yet.

**Scope:**
- Create the three header/source file pairs from the plan as no-op stubs:
  - `src/companion_server.h` / `.cc`
  - `src/companion_protocol.h` / `.cc`
  - `src/companion_snapshot.h` / `.cc`
- Declare the public API in `companion_server.h`:
  ```cpp
  namespace fallout {
  bool companionServerInit();
  void companionServerExit();
  void companionServerTick(unsigned int now);
  }
  ```
- Add calls at `src/game/main.cc:224` (`main_init_system`), `:311` (`main_game_loop`), `:245` (`main_exit_system`).
- Add the three new `.cc` files to the CMake target.

**Acceptance:**
- Build succeeds.
- Game starts and runs unchanged with stubs in place.
- `companionServerTick` is called once per main loop iteration with `compat_timeGetTime()`.

**Notes:**
- Confirm exact CMake target name during implementation; do not assume.
- Tolerate init returning `false`; game must continue.

---

### T2 — Game-State Reader (`companion_snapshot`)

**Status:** done

**Goal:** Produce a normalized snapshot of the data the companion exposes, independent of the network layer.

**Scope:**
- Implement in `src/companion_snapshot.{h,cc}`:
  ```cpp
  namespace fallout {
  struct CompanionPlayerSnapshot { int hp; int maxHp; };
  struct CompanionSnapshot { bool hasPlayer; CompanionPlayerSnapshot player; };
  CompanionSnapshot companionCollectSnapshot();
  }
  ```
- Read via `obj_dude`, `critter_get_hits(obj_dude)`, `stat_level(obj_dude, STAT_MAXIMUM_HIT_POINTS)`.
- If `obj_dude == nullptr`, return `{hasPlayer=false}`.

**Acceptance:**
- Compiles without leaking engine headers into the public header.
- Returns correct values in normal play.
- Returns `hasPlayer=false` in menus / before the world loads / after death.
- No global state in this module.

**Notes:**
- This module knows nothing about sockets or JSON. It is a pure read.
- Keep the public header minimal; include `game/object.h`, `game/critter.h`, `game/stat.h` only inside the `.cc`.

---

### T3 — Protocol I/O (`companion_protocol`)

**Status:** done

**Goal:** Build the three server messages and recognize the two client messages. Nothing more.

**Scope:**
- Hand-rolled JSON. No library. Stable field order matters. All field names use camelCase.
- Build helpers producing newline-terminated strings:
  - `world(playerAvailable)` → `{"type":"world","schemaVersion":1,"game":"fallout1-ce","playerAvailable":true|false}\n`. Sampled at the moment of `hello` acceptance.
  - `snapshot(seq, CompanionSnapshot)` → `{"type":"snapshot","seq":N,"playerAvailable":true|false,"data":{"player":{"hp":..,"maxHp":..}}}\n`. `playerAvailable` is `snapshot.hasPlayer`.
  - `update(seq, playerAvailable, current, lastSent)` → `{"type":"update","entity":"player","seq":N,"playerAvailable":true|false,"data":{...}}\n` where `data` is one or more of `hp`, `maxHp` (step 1 sends only the changed fields; for HP changes, `hp` only; if `maxHp` changes for any reason, send both).
  - `player_unavailable(seq)` → `{"type":"player_unavailable","seq":N,"playerAvailable":false}\n`. Emitted only on the absent-side transition (see Resolved Decision 3).
- Exact-shape parser for input. Accepts only:
  - `{"type":"hello"}` (whitespace around `:` and after commas tolerated minimally; do not pull in a parser)
  - `{"type":"get_snapshot"}`
- Anything else returns "not recognized" to the caller, which will fail the connection.

**Acceptance:**
- Exact byte output matches the schema in the plan.
- Parser returns a clear enum / bool distinguishing `hello` / `get_snapshot` / `invalid`.
- No heap allocation in the success path; reuse a caller-owned buffer or `std::string` returned by value (fine, simple).

**Notes:**
- Do not write a recursive-descent JSON parser. Compare fixed-shape strings after a tiny normalization.
- `seq` formatting is the caller's responsibility (the server passes a pre-formatted number, or this module formats it — pick one and document it in the function signature).

---

### T4 — Server Runtime: Listener And Connection Lifecycle

**Status:** done

**Goal:** TCP listener on `127.0.0.1:28080`, non-blocking, single client, POSIX only.

**Scope:**
- Implement in `src/companion_server.{h,cc}`.
- State machines (matching the plan):
  - Server: `disabled`, `listening`, `client_connected`, `client_ready`.
  - Per-connection: `awaiting_hello`, `ready`.
- `companionServerInit`:
  - Create socket, set `O_NONBLOCK`, `SO_REUSEADDR`, bind, listen.
  - On any failure: log via `debug_printf`, set state to `disabled`, return `true` (do not fail the game).
- `companionServerTick`:
  - If `listening` and a connection is pending, accept it; set the client socket non-blocking; transition to `awaiting_hello`.
  - If a second client tries to connect while one is active, close it immediately.
  - Disconnect/error → back to `listening`.
- `companionServerExit`:
  - Close any open client and the listener; release fds.

**Acceptance:**
- With no client, `tick` is a cheap no-op.
- After a client disconnects, the next `tick` can accept a new one.
- No file descriptor leaks across many connect/disconnect cycles.
- No use of `connect()`, `read()`, or `write()` that could block — `recv`/`send` with `MSG_DONTWAIT` or equivalent non-blocking flags only.

**Notes:**
- One-client is a hard limit. Do not design for a connection table; design for one slot.
- No `select`/`poll`/`epoll` for step 1. One socket, one connection. Revisit in step 2 if more is needed.

---

### T5 — Server Runtime: Protocol Loop And Periodic Updates

**Status:** done

**Goal:** Drive the per-connection state machine, enforce the protocol, and push sampled HP updates every 500 ms.

**Scope:**
- Extends `src/companion_server.cc`.
- Inbound:
  - Read into a fixed-size receive buffer (suggested 4 KiB).
  - Split on `\n`. Each complete line goes to the protocol parser.
  - On parse error or unknown first message, drop the client.
- Handshake:
  - In `awaiting_hello`: only `hello` is valid. Any other first message → drop, back to `listening`.
  - On `hello` → enqueue `world`, transition to `ready`, reset `seq` to 0 (next send becomes seq=1).
- Post-handshake:
  - `get_snapshot` → enqueue one `snapshot` with current `seq`, then increment.
  - Every 500 ms (time-based, not frame-based):
    - Sample `companionCollectSnapshot()`.
    - If the snapshot's `hasPlayer` differs from the cached `player_was_available` (initialized to `false`):
      - On the present→absent transition, enqueue a `player_unavailable` and increment `seq`. Do **not** touch the cached `last_sent_hp` / `last_sent_maxHp`.
      - On the absent→present transition, just update `player_was_available = true`. The next sample's change detection will fire a normal `update` for any field that differs from the last sent value.
    - If the snapshot's `hasPlayer` is true and any tracked field (`hp`, `maxHp`) differs from the last sent value, enqueue an `update` for `player` carrying only the changed fields, then increment.
- Outbound:
  - Maintain an outbound buffer with a **256 KiB cap** (see Resolved Decision 1).
  - Flush with non-blocking `send`. On `EAGAIN`/`EWOULDBLOCK`, keep the buffer for next tick. On overflow, drop the client.
  - On send/recv error, drop the client.

**Acceptance:**
- Happy path: hello → world → get_snapshot → snapshot → periodic updates within 500 ms of HP change.
- Sending `{"type":"foo"}` first → connection closes; game unaffected.
- Sending garbage (not even valid JSON) first → connection closes; game unaffected.
- Client disconnect mid-message → server returns to `listening` cleanly; no fd leak.
- `seq` increments per post-handshake send and is present on every such message.
- Player load → no `player_unavailable` emitted (initial state is absent).
- Player death / world unload (transition to absent) → exactly one `player_unavailable` on the wire. No further `player_unavailable` until the player returns and is lost again.
- Player return → a normal `update` fires within one sample interval (or no update if values happen to match the last sent values; both are acceptable).
- Outbound buffer cap at 256 KiB: a client that stops reading is dropped within one tick of the buffer exceeding the cap.

**Notes:**
- "Change detection" is just `last_sent_hp != current_hp` and `last_sent_maxHp != current_maxHp`. Reset both on disconnect.
- Do not introduce a timer thread. Use `now - last_sample_ms >= 500`.
- Buffer sizes are step-1 guesses. If they show up in profiling, revisit; do not preemptively tune.

---

### T6 — Lifecycle Logging

**Status:** done

**Goal:** Low-volume, useful log lines via existing `debug_printf`.

**Scope:**
- Log on: init failure, listener up (one line), client accepted, `hello` accepted, snapshot sent, update sent (only when one is actually sent), client disconnect, socket error, init path returning `disabled`.
- Do not log: per-tick accept attempts, per-line parse success beyond `hello`/`get_snapshot`, every send, no-op ticks.

**Acceptance:**
- A full handshake + snapshot + one update produces a handful of log lines, not dozens.
- A misbehaving client (bad first message, slow) produces a clear disconnect line, not a stack trace.
- No log output when no client is connected across many ticks.

**Notes:**
- If a line would be useful only in deep debugging, do not include it at the default verbosity. Step 1 does not need a verbosity knob.

---

### T7 — Manual Validation

**Status:** done

**Goal:** Run the 10-step validation from the plan and record pass/fail.

**Scope:**
- Execute the steps in `docs/plans/companion-server-step-1.md` "Validation Strategy" → "Manual runtime validation".
- Test with `nc 127.0.0.1 28080`.
- Damaging and healing the player in-game to trigger an `update`.

**Acceptance:**
- Each of the 10 steps in the plan passes.
- Two extra steps pass: (a) disconnect mid-stream returns server to `listening`; (b) overflow / slow consumer drops the client.
- Any failure produces a written reproduction and a referenced `file:line`.

**Notes:**
- This is a hand-off to the QA persona. Engineering does not self-approve.
- If the dev environment cannot easily damage the player to trigger an `update`, find a console command or scripted path before declaring T7 blocked.

**Validation log (complete):**
- Verified: game starts and runs with the server enabled and no client connected (no regression).
- Verified: `nc 127.0.0.1 28080` from another shell succeeds.
- Verified: `{"type":"hello"}` → `{"type":"world",...}` and server enters `ready`.
- Verified: `{"type":"get_snapshot"}` → one `snapshot` with `player.hp` and `player.maxHp` matching in-game values.
- Verified: the server responds even while the game window is unfocused and even before `main_game_loop` is entered (intro / main menu). This is the background tick hook working.
- Verified: 0 `update` messages in 2s of idle listening when HP does not change — change detection throttles correctly.
- Verified: HP change in-game (combat damage from an ant) produces an `update` on the wire within ~500ms, without needing to Alt-Tab to the client. The combat-loop tick integration (`combat_turn_run` and `combat_input` in `src/game/combat.cc`) keeps the server responsive while the main loop is blocked by the turn-based combat system.
- Verified: disconnect mid-stream returns server to `listening` cleanly — multiple reconnects with full handshake + snapshot each time succeed.
- Verified: invalid first message (`{"type":"foo"}`) drops the client; a follow-up handshake succeeds.
- Verified: slow consumer / outbound overflow (5000 `get_snapshot` lines in one shot) drops the client with a connection reset; a follow-up handshake succeeds.

---

## Suggested Ordering

T1 → T2 → T3 → T4 → T5 → T6, then T7 (QA). T2 and T3 have no inter-module dependencies and can be implemented in either order. T4 and T5 form one logical unit; keep them in the same review.

## Rejection Heuristics For Future Proposals

Push back on any of:

- Adding a JSON library "for safety."
- Introducing a `select`/`poll`/`epoll` loop "while we're at it."
- Buffering multiple clients "since the structure is already there."
- Streaming `maxHp` on every `update` "for completeness."
- Adding a config file for host/port in step 1.

The plan chose simplicity on purpose. Defend it.
