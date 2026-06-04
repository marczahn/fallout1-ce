# Companion Server Step 1 — Audit

- **Range:** `ab529c0d78e617ea28e134b5f26f072cd608b611^..HEAD` (9 commits, +1900 / -1)
- **Scope:** companion server step 1 (new files + minimal integration points + 1 unrelated typo fix)
- **Stance:** general code health snapshot, architecture + code quality + protocol correctness
- **Plan of record:** `docs/plans/companion-server-step-1.md`
- **Tickets of record:** `docs/plans/companion-server-step-1-tickets.md`

## Summary

The implementation is in good shape and matches the plan to a high degree. The module split
(`companion_server` / `companion_protocol` / `companion_snapshot`) is clean, the
non-blocking I/O discipline is solid, and the protocol is faithfully reproduced from the
plan. There are a few minor code-quality issues, a handful of small doc drifts, and one
behavioral deviation from the plan that is conservative-but-arguably-correct. Nothing in
this audit blocks step 1.

Verdict: **approve with optional follow-ups** (see "Follow-ups" at the end).

---

## 1. Business Analyst Pass

### Problem and outcome

- The plan and the implementation are aligned on a single, well-bounded outcome: a
  localhost-friendly TCP service that exposes player HP to an external companion
  application, without changing the game or the engine.
- "Game remains authoritative" is preserved: the server is read-only on the game state.
  `companion_snapshot.cc:17-23` reads via the agreed stable APIs (`obj_dude`,
  `critter_get_hits`, `stat_level`) and tolerates a null `obj_dude` (lines 17-19). No
  mutation, no engine coupling beyond the three agreed sampling points.

### Success criteria vs. delivery

The plan's top-level success criteria (`docs/plans/companion-server-step-1.md:484-493`)
and the tickets' success criteria (`docs/plans/companion-server-step-1-tickets.md:53-62`)
are met by the diff:

| Success criterion | Status | Evidence |
| --- | --- | --- |
| Game starts with server enabled, no client | met | `companionServerInit` returns `true` on every failure path (`companion_server.cc:432,440,447,458,465,472`) and sets state to `Disabled` |
| `nc 127.0.0.1 28080` works | met | listener created at `companion_server.cc:428-478` |
| `hello` → `world` then `Ready` | met | `handleClientMessage` → `queueWorldMessage` (`companion_server.cc:265-273, 210-221`) |
| `get_snapshot` returns `snapshot` with `hp`/`maxHp` | met | `companionBuildSnapshot` (`companion_protocol.cc:33-49`) |
| `update` within 500 ms of HP change | met | time-based sampling in `sampleReadyClient` (`companion_server.cc:381-406`) |
| Disconnect leaves server ready for next client | met | `closeConnection` → `resetConnectionState` (`companion_server.cc:117-133`) |
| Non-`hello` first message drops client | met | `handleClientMessage` (`companion_server.cc:265-268`) |

The step-1 deliverable list (plan lines 484-493) is fully covered.

### Hidden assumptions that were verified

- The `compat_timeGetTime()` wrap-around concern is dismissed correctly. With a
  500 ms cadence the counter wraps after ~828 days; the difference
  `now - lastSampleMs < kSampleIntervalMs` uses unsigned arithmetic that handles
  wrap correctly only if `kSampleIntervalMs` is small relative to the wrap period
  (it is, by ~6 orders of magnitude).
- `obj_dude` can be null at startup, menus, and the world map. The collector handles
  this. The plan explicitly notes the "real map vs placeholder" ambiguity as a known
  step-2 task (`docs/plans/companion-server-step-1.md:467-482`) — deferred correctly.

### Open risks worth surfacing

- The plan's "Security note" (plan line 92) binds the server to `0.0.0.0`. The
  diff deliberately keeps this for step 1 (commit `4e62e00`). The default of
  `127.0.0.1` is listed as a step-2 task. This is the right call for step 1
  development, but it means a developer running the build on a laptop
  sharing a network can leak HP data. Worth a louder warning to devs.
- The 500 ms cadence is a guess. The plan's "Risks" section is silent on cost.
  This audit confirms it is cheap (see "Performance notes"), so the risk is low.

### Non-goals — confirmed

The plan's non-goals (no UDP, no HTTP, no WebSocket, no event bus, no extra thread)
are all respected by the diff. No third-party libraries were added. The diff has
no `std::thread`, `std::async`, `pthread_create`, or `CreateThread` calls.

---

## 2. Architect Pass

### Module boundaries

The split is the right one and is respected:

- `companion_snapshot.{h,cc}` — pure read of game state, no networking, no JSON.
  Engine headers (`game/critter.h`, `game/object.h`, `game/stat.h`,
  `game/stat_defs.h`) are kept inside the `.cc` (`companion_snapshot.cc:3-6`).
  The public header is clean of engine dependencies
  (`companion_snapshot.h:1-19`). This is the correct isolation.
- `companion_protocol.{h,cc}` — pure wire format. Depends only on
  `companion_snapshot.h` and `<string>` (`companion_protocol.h:1-9`). Could
  be unit-tested without an engine.
- `companion_server.{h,cc}` — runtime / lifecycle. Touches sockets, ticks,
  and orchestrates the other two modules. The only file that includes
  `plib/gnw/input.h` and `plib/gnw/debug.h` (`companion_server.cc:20-23`),
  which is the correct scope.

### Integration points

The tick site is well-chosen:

- `companionServerTick` is called from `process_bk()` at the top of the function
  (`src/plib/gnw/input.cc:219`). `process_bk` is reached from
  `get_input` (`input.cc:194`), `pause_for_tocks` (`input.cc:650`),
  `combat_turn_run` (`src/game/combat.cc:2135`), `combatai.cc` (twice), and
  `intlib.cc:423`. This covers every focused loop the engine has.
- The idle-hook for the unfocused-window busy-wait is correct
  (`companion_server.cc:69-76`): it calls the previous `idle_func` first
  (preserving the `SDL_Delay(125)` throttle in `idleImpl` at `input.cc:1228-1231`),
  then ticks. The two tick sites are mutually exclusive on the same thread.

### Lifecycle and state machine

- Server-side states (`Disabled`, `Listening`) and client-side states
  (`AwaitingHello`, `Ready`) match the plan
  (`companion_server.cc:40-48`).
- Init / exit / tick are pure and the only public API surface
  (`companion_server.h:6-8`). The header is minimal and
  free of platform/JSON details — good.
- Init failure is fully isolated: every error path in
  `companionServerInit` returns `true` and sets the server to `Disabled`
  (`companion_server.cc:429-473`). The game is never aborted.
- The idle hook is uninstalled on `companionServerExit`
  (`companion_server.cc:494-498`) and the listener fd is closed
  (`companion_server.cc:502`). No leak across
  init/exit cycles.

### Coupling to the engine

- Only three sampling points are used: `obj_dude`, `critter_get_hits`,
  `stat_level` — all stable, well-defined engine APIs.
- One new include is added to `src/game/main.cc` (`companion_server.h`) and
  one to `src/plib/gnw/input.cc` (`companion_server.h`). The diff does not
  touch any other engine source file beyond the one-character typo fix in
  `src/plib/gnw/debug.cc`. This is exactly the "localized diff" the tickets
  asked for (`tickets.md:31`).

### Coupling we are introducing

- `companionServerTick` runs on every `process_bk` call, which is
  hot-path in some loops (`pause_for_tocks` calls it in a tight
  while-loop, `input.cc:649-656`). The tick is non-blocking and the
  no-client path returns after a single `gServerState` check
  (`companion_server.cc:508-510`). Cost is one branch in the
  steady-state-with-no-client case. Acceptable.
- The idle-hook chains a new function pointer onto a global
  (`idle_func` in `input.cc:57`). Only one piece of code in the engine
  is allowed to do that. If any future feature wants to chain its own
  idle function, the ordering will matter. This is a documented cost of
  the design choice, not a defect.

### Extensibility for step 2

- Multi-client: the connection is a single global (`gConnection`,
  `companion_server.cc:78-88`). Adding a small map would not change the
  public API. The state machine and protocol code are reusable.
- Windows support: the `#if !defined(_WIN32)` … `#else` (stubs) …
  `#endif` structure (`companion_server.cc:28-546`) leaves clean hooks.
  The stubs at `companion_server.cc:530-545` are correct.
- Auth, configurable bind host, `127.0.0.1` default: these are step-2
  tasks per the plan. The current code centralizes the hardcoded
  values in one place (`kListenPort`, `kListenHost`, `companion_server.cc:32-33`),
  so promoting them to config is a one-spot change.

### Protocol correctness vs. plan

The protocol reproduces the plan's wire format exactly. Specific checks:

- `world`: `{"type":"world","schemaVersion":1,"game":"fallout1-ce","playerAvailable":<flag>}\n`
  — matches the plan example. Built at `companion_protocol.cc:18-31`.
- `snapshot`: `{"type":"snapshot","seq":<n>,"playerAvailable":<flag>,"data":{"player":{"hp":<h>,"maxHp":<m>}}}\n`
  — matches the plan example. Built at `companion_protocol.cc:33-49`.
  No `entity` field — correct, per plan ("`snapshot` does not include `entity`").
- `update` with both `hp` and `maxHp` when `maxHp` changes:
  `companion_protocol.cc:59-67`. Matches plan.
- `update` with only `hp` when only `hp` changes:
  `companion_protocol.cc:68-75`. Matches plan.
- `update` returns empty string when nothing changed:
  `companion_protocol.cc:76-78`. Caller in
  `queuePlayerUpdateIfNeeded` (`companion_server.cc:243-261`)
  guards on this, so an empty `update` is never queued.
- `player_unavailable`: `{"type":"player_unavailable","seq":<n>,"playerAvailable":false}\n`
  — matches. Built at `companion_protocol.cc:85-97`.
- `world` has no `seq` (plan: "`seq` on every post-handshake server
  message"). Implemented: `queueWorldMessage` does not call
  `nextSequence` (`companion_server.cc:210-221`). Correct.
- `seq` starts at 1 for the first post-handshake send: `gConnection.nextSeq = 1`
  in `resetConnectionState` (`companion_server.cc:120`) and the static
  initializer at `companion_server.cc:82`. `nextSequence` returns
  `gConnection.nextSeq++` (`companion_server.cc:144-147`). The first
  `snapshot` or `update` will have `seq:1`.
- Field names: `schemaVersion`, `playerAvailable`, `maxHp` (camelCase) — matches.
  Type names: `world`, `snapshot`, `update`, `player_unavailable`, `hello`,
  `get_snapshot` — matches.

### Plan / tickets drift to be aware of

- **Tickets T1** (`tickets.md:85-93`) says the tick is added at
  `main_game_loop` (`main.cc:311`) and "the two combat loops in
  `src/game/combat.cc`". The actual diff does not touch
  `main_game_loop` or `combat.cc` — the tick is centralized at
  `process_bk` (`input.cc:219`), which is the right call (one
  call covers every focused loop). Commit `c8dc0ea` made this
  change. The plan is up-to-date (`plan.md:258-273`); the
  tickets are stale on this point. Update the tickets before
  treating them as the source of truth.
- **Tickets T1** also says "three new `.cc` files are added as
  three lines" (`tickets.md:50`). The diff adds six lines
  (three `.cc` + three `.h` files, `CMakeLists.txt:44-49`).
  Cosmetic — the headers travel with the sources — but worth
  correcting.
- **Tickets scope statement** (`tickets.md:21`) says "No Windows
  socket support (POSIX first; keep code isolated for step 2)".
  The actual code has Windows stubs (`companion_server.cc:530-545`).
  This is a stricter reading than necessary; the stubs are
  cheap and make the code compile on Windows. Either update
  the tickets to say "stubs only" or remove the stubs.
  The audit recommends keeping the stubs.

### Performance notes (informational, not blocking)

- Steady-state no-client cost: one branch (`gServerState == Disabled`
  early-return at `companion_server.cc:508-510`). Negligible.
- Steady-state with one client, no change: ~one branch and one
  `companionCollectSnapshot` per 500 ms. `companionCollectSnapshot`
  does two stable engine calls. Negligible.
- Slow-consumer cost: the outbound path uses
  `gConnection.outbound.erase(0, n)` (`companion_server.cc:368`),
  which is O(buffer size). With the 256 KiB cap
  (`kOutboundCap`, `companion_server.cc:37`), the worst case is
  O(256 KiB) per `send` call. A slow consumer is rare and
  is dropped within one tick of hitting the cap, so the
  total work is bounded. For step 1 this is fine. If profiling
  ever shows it, switch to a `std::deque<char>` or a small
  ring buffer — same complexity, O(1) per byte.
- The inbound `memmove` (`companion_server.cc:303-305`) is
  also O(buffer size) per line. The 4 KiB inbound cap
  (`kInboundBufferSize`, `companion_server.cc:36`) bounds it.

### Style and convention notes

- File-scope `gServerState`, `gListenerFd`, `gConnection`,
  `gOriginalIdleFunc`, `gIdleHookInstalled` are a smell in
  general, but the right call for a single-server,
  single-client design. They are in an anonymous namespace
  (`companion_server.cc:30-408`) so they have internal
  linkage. No external TU can collide.
- `companion_server.cc:65-76` has a redundant
  `#if !defined(_WIN32)` *inside* the outer
  `#if !defined(_WIN32)` (the outer one is at line 28,
  the file-level inner one is at line 65). It is harmless
  but visually noisy. Recommend dropping the inner guard
  (or extracting `companionIdleHook` and the two globals
  into a small platform-conditional block).

---

## 3. Code Reviewer Pass

### Matches the plan

- One TCP client. Implemented (single `gConnection`,
  `companion_server.cc:78-88`).
- Non-blocking I/O. `O_NONBLOCK` set on the listener and on
  every accepted fd (`companion_server.cc:95-107, 195-199`).
  `MSG_DONTWAIT` on `recv` and `send`
  (`companion_server.cc:323, 356`). `MSG_NOSIGNAL` guarded
  with `#if defined(MSG_NOSIGNAL)` (`companion_server.cc:357-359`).
- Time-based 500 ms scheduling, not frame-based
  (`companion_server.cc:381-390`).
- `world` has no `seq`; first `snapshot`/`update` is `seq:1`
  (`companion_server.cc:120, 144-147, 210-221`).
- `snapshot` has no `entity`; `update` always has `entity:player`
  (`companion_protocol.cc:39, 62, 71`).
- `update.data` is partial: only changed fields are sent
  (`companion_protocol.cc:59-78`).
- Outbound 256 KiB cap with `disconnect on overflow`
  (`companion_server.cc:155-158`).
- Inbound 4 KiB cap with `disconnect on overflow`
  (`companion_server.cc:315-318, 345-349`).
- Slow consumer: dropped within one tick of hitting the
  cap. Verified by tickets T7 manual validation
  (`tickets.md:289`).
- Server init failure is non-fatal: returns `true` and
  sets `Disabled` on every error
  (`companion_server.cc:429-473`).
- Tick site: `process_bk()` plus the idle hook. Matches
  plan (`input.cc:219`, `companion_server.cc:69-76`).
- No background threads: `grep` confirms.

### Behavioral deviation from plan (intentional, conservative)

The plan and tickets both say "drop the client on unknown
**first** message" (`plan.md:169`, `tickets.md:204`). The
implementation drops on unknown **any** post-handshake
message (`companion_server.cc:280-285`). This is a
stricter interpretation:

- Sending `{"type":"foo"}` after `hello` will drop the
  client.
- The plan and tickets could be read either way; the
  implementation is the safer one.

**Recommendation:** keep the strict behavior, but tighten
the wording in the plan and tickets to "unknown message"
(removing the word "first"). Right now a reader of the
plan would expect post-handshake garbage to be ignored,
not fatal.

### Edge cases checked

- **Empty first line:** `companionParseClientMessage` rejects
  `length == 0` (`companion_protocol.cc:101-103`). The `processInboundLines`
  loop extracts `lineLength` from a `memchr` of `'\n'`, so
  an empty line is `lineLength = 0`, parser returns
  `Invalid`, and the client is dropped. Correct.
- **Whitespace-only first line:** the parser strips all
  whitespace (`companion_protocol.cc:107-117`), produces
  an empty `stripped`, fails both `memcmp` checks, returns
  `Invalid`. Client dropped. Correct.
- **A line longer than 64 bytes (after stripping):** parser
  returns `Invalid` (`companion_protocol.cc:112-114`). With
  only 4 KiB inbound cap, lines up to 4 KiB can arrive,
  so the parser rejection prevents a 4 KiB `{"type":"hello"}`
  attempt from being accepted. That is correct: such a
  payload is not the agreed shape.
  One side effect: a malformed but well-intentioned client
  that pads with whitespace will be dropped. This is the
  intended "fail closed" behavior.
- **`hello` arriving twice:** after handshake, an extra
  `hello` is silently ignored (`companion_server.cc:280-282`).
  No state change, no `seq` increment. Correct.
- **Disconnect mid-message:** `recv` returns 0, client is
  dropped (`companion_server.cc:325-328`). Listener
  remains open. Correct.
- **`EINTR`:** not explicitly handled. `recv`/`send` can
  return `-1` with `errno == EINTR`. The current code
  treats that as a generic error and drops the client.
  This is a Linux-only concern; macOS does not normally
  raise `EINTR` from socket I/O. For step 1 with one
  client and no signals, this is acceptable. Worth a
  follow-up if step 2 introduces a signal-driven path.
- **`MSG_NOSIGNAL` on macOS:** defined. `send` will not
  raise `SIGPIPE` if the client has closed. Correct.
- **`errno` not thread-local-safe:** irrelevant — the
  whole server is single-threaded.
- **Long-lived `seq` overflow:** `unsigned int` wraps at
  ~4.3 billion. Per-connection counter, connection is
  short-lived. Not a concern.
- **`lastSampleMs` wrap-around:** when `now` wraps past
  `UINT_MAX`, the difference computation
  `now - gConnection.lastSampleMs < kSampleIntervalMs`
  uses unsigned wrap. With a 500 ms cadence, the counter
  only wraps after ~828 days of continuous use. Not a
  concern in practice; the math is correct for the
  non-wrapping range.
- **Player load → first sample with `playerAvailable=true`:** the
  implementation matches the plan's "absent → present
  transition: just update `player_was_available = true`"
  rule (`companion_server.cc:393-401`). The next
  sample will fire a normal `update` for any changed
  field. Correct.
- **Repeated re-`init` of the server** (e.g., on game
  reset): the idle hook install is guarded
  (`companion_server.cc:481-486`). The listener fd is
  reset (`companion_server.cc:475-476`) and the
  connection state is reset
  (`companion_server.cc:476`). No leak.
  **Caveat:** the `companionEnableDebugLog` static guard
  (`companion_server.cc:416-421`) means a re-`init` will
  not re-register the env. This is intentional — the
  comment says "Remove once a global debug init path
  is in place."

### Specific code observations

- `companion_server.cc:78-88`: the static initializer for
  `gConnection` uses positional braces. C++17 does not
  support designated initializers, so the style is
  correct. The fields are listed in struct order, but a
  quick `static_assert(sizeof(CompanionConnection) == …)`
  would make refactors safer. Optional.
- `companion_server.cc:120, 167-168`: `lastSampleMs = 0`
  after `hello` is a sentinel that means "sample on next
  tick". The condition
  `if (lastSampleMs != 0 && now - lastSampleMs < kSampleIntervalMs)`
  in `sampleReadyClient` (`companion_server.cc:387-389`)
  skips the interval check for the first sample. This is
  the agreed plan behavior; `lastSampleMs` is then set
  to `now` so the 500 ms cadence kicks in.
- `companion_server.cc:368`: `gConnection.outbound.erase(0, n)`
  is O(N). See "Performance notes" above.
- `companion_server.cc:212-221`: `queueWorldMessage`
  primes the last-sent state from the snapshot taken
  *at hello time*. The `world` message itself is built
  from `snapshot.hasPlayer` only. The local
  `lastSentPlayer` is then set to the actual values, so
  the first sample's change detection works against the
  correct baseline. Correct.
- `companion_server.cc:243-261`: `queuePlayerUpdateIfNeeded`
  updates `gConnection.lastSentPlayer = snapshot.player`
  after a successful enqueue. The `snapshot.hasPlayer`
  flag is *not* consulted here; the caller is responsible
  for ensuring the player is available. `sampleReadyClient`
  calls this only after confirming `snapshot.hasPlayer`
  (`companion_server.cc:403-405`). Tight coupling
  enforced by convention, not type. Acceptable for
  this small module.
- `companion_protocol.cc:107-117`: the parser strips *all*
  whitespace. The plan's wording is "whitespace around `:`
  and after commas tolerated minimally"
  (`tickets.md:145`). The implementation is more liberal.
  This is a non-issue (the wire format is well-defined and
  `nc` emits the agreed shape), but worth noting.
- `companion_protocol.cc:118-123`: equality check against
  the canonical bytes is exact and unambiguous. Good.
- `companion_protocol.cc:21, 36, 57, 87`: stack buffer
  sizes (96, 160, 160, 80) are sized for the longest
  possible output. `snprintf` is bounded and the
  `n >= sizeof(buffer)` check (`companion_protocol.cc:27-29`)
  is defensive. With a 32-bit `unsigned int` and a 32-bit
  `int`, the worst case is well under 200 bytes. Good.
- `companion_server.cc:355-378` `flushOutbound`: the loop
  is `while (hasClient() && !outbound.empty())`. A single
  successful `send` drains some bytes and continues; a
  partial `EAGAIN` returns. Correct.
- `companion_server.cc:130-133` `closeConnection`: closes
  the fd and resets all connection state. The fd is set
  to `-1` via `closeFd` (`companion_server.cc:109-115`).
  No double-close path: `closeFd` is a no-op on `-1`.
  Good.
- `companion_server.cc:177-180` `rejectExtraClient`: a
  second client connects and is immediately closed. The
  outbound buffer is not touched (correct: there is no
  outbound buffer for the rejected client). The accepted
  client is unaffected. Good.
- `companion_server.cc:301-307` and
  `companion_server.cc:339-349`: the inbound `memmove` and
  the post-recv overflow check are correct. There are
  *two* overflow checks (`companion_server.cc:315-318`
  and `companion_server.cc:345-349`). The first is the
  "carried over from the last tick" case; the second is
  the "we just filled it on this tick" case. Both
  produce the same outcome. Slightly redundant but
  unambiguous. Fine.
- `companion_server.cc:531-545`: Windows stubs return
  without doing anything. This keeps the rest of the
  codebase (`main.cc`, `input.cc`) compiling on Windows
  without `#ifdef` sprinkling. Good.

### Integration-point changes

- `src/game/main.cc:16, 231, 255`: three-line change
  (include + init + exit). `companionServerExit` is
  called *before* `game_exit` so the server is torn
  down before the engine state it might touch
  (`obj_dude` etc.) is invalidated. Correct.
- `src/plib/gnw/input.cc:7, 219`: include + one call at
  the top of `process_bk`. The call uses
  `compat_timeGetTime()` to keep the cadence consistent
  with the rest of the engine.
- `src/plib/gnw/debug.cc:58`: one-character typo fix.
  Original:
  `(mode[0] == 'w' && mode[1] == 'a') && mode[1] == 't'`.
  Fixed:
  `mode[0] == 'w' && mode[1] == 't'`. The original is
  always false (a single char cannot equal both `'a'`
  and `'t'`). The fix is correct. Side note: a caller
  passing `"w"` alone (no `t`) will still fail the
  check, but the only caller in the codebase is
  `debug_register_log("debug.log", "wt")` at
  `debug.cc:101`, so the fix is sufficient.

### Build system

- `CMakeLists.txt:44-49`: six new lines, three `.cc` +
  three `.h`, alphabetical, before the first
  `src/game/...` entry. Good.
- `CMakeLists.txt` does not need any new link flags for
  POSIX sockets (they are in libc on Linux/macOS) or for
  Windows (WinSock would need `ws2_32`, but the Windows
  path has no actual socket code — only stubs — so no
  link change is needed). Correct.

### `AGENTS.md`

The 305-line file is well-organized and faithfully
describes the project's collaboration model and the
current companion-server direction. No technical issue
to flag. Worth noting that the "Current Companion Server
Direction" section says "localhost only", but the plan
explicitly binds to `0.0.0.0` (with a step-2 task to
default to `127.0.0.1`). The direction statement in
`AGENTS.md` is the *target*; the plan describes the
*current* state. The wording in `AGENTS.md` could be
tweaked to "intended to be localhost only in step 2;
currently binds to `0.0.0.0` for step 1" to remove
ambiguity. Cosmetic.

### `docs/plans/companion-server-step-1-tickets.md` drift

Already noted above. Specific items to fix in a follow-up:

- T1 scope (`tickets.md:31`) lists "the two combat loops
  in `src/game/combat.cc`". `combat.cc` was not
  modified. The plan's centralized `process_bk` approach
  subsumed this. Update T1 to say "tick centralized at
  `process_bk` (`input.cc:219`) plus the idle hook".
- T1 (`tickets.md:50`) says "three new `.cc` files are
  added as three lines in alphabetical order". The
  diff adds six lines (3 .cc + 3 .h). Cosmetic fix.
- T5 acceptance (`tickets.md:230`) describes a buffer
  cap of 256 KiB and a tick of dropping on overflow. The
  implementation matches. No change needed.
- Scope statement (`tickets.md:21`) says "No Windows
  socket support". The implementation has stubs. Either
  say "stubs only" or remove the stubs. Recommend
  keeping the stubs and updating the wording.

---

## 4. QA Pass

### Evidence of validation

The tickets' "validation log" (`tickets.md:279-289`)
documents 10 manual checks. Specific notes:

- The "HP change in-game (combat damage from an ant)"
  test is unusual — it relies on the player being in
  combat with an ant to trigger damage. The plan's
  validation strategy (plan line 402-404) says "Change
  HP in-game (focus the game window briefly to take
  damage / heal, then return to the client window)."
  This works but is not deterministic. A console
  command or a deliberate HP-modify hook would be more
  reproducible. For step 1, manual play is acceptable.
- The "5000 `get_snapshot` lines in one shot" overflow
  test (`tickets.md:289`) is a real slow-consumer check
  and confirms the 256 KiB cap drops the client. Good.
- "Reconnect after invalid first message" is verified
  (`tickets.md:288`). Confirms the listener remains
  open after a client drops. Good.

### What is *not* verified

The validation log does not cover:

1. **`seq` value correctness.** The plan says `seq`
   starts at 1 and increments per post-handshake
   message. A test client should observe
   `seq=1` for the first `snapshot` or `update` after
   `world`. Not asserted.
2. **`world` has no `seq`.** The plan says
   "`world` has no `seq`". Not asserted.
3. **`player_unavailable` on absent transition.** The
   plan says it is one-shot on present→absent. Not
   asserted.
4. **`update` on absent→present transition.** The plan
   says no `player_available` event, just a normal
   `update` for changed fields. Not asserted.
5. **Empty `update` is never sent.** The implementation
   returns an empty string from `companionBuildPlayerUpdate`
   when nothing changed (`companion_protocol.cc:76-78`)
   and the caller does not enqueue it
   (`companion_server.cc:243-261`). Worth asserting.
6. **A 4 KiB send fills the inbound buffer.** The plan
   says the server drops on inbound overflow. The
   implementation drops after the buffer is full and
   no newline is found (`companion_server.cc:345-349`).
   Not explicitly tested.
7. **Server init failure does not abort the game.** The
   plan calls this out explicitly. The diff claims it
   but does not exercise it. A test that preempts the
   port (e.g., another process listening on 28080) and
   then launches the game would be a strong check.

### Regression risk

The risk is low but worth noting:

- The 5-line change to `main.cc` is straightforward
  (init + exit), but it does mean `game_init` and
  `companionServerInit` are now both called in
  `main_init_system`. The order is
  `game_init → companionServerInit → main_selfrun_init`.
  Reordering either init call could in theory affect
  game startup. Worth a comment in `main.cc` explaining
  the order. Optional.
- The single line in `process_bk` (`input.cc:219`) runs
  on every input poll. As noted, the no-client path is
  one branch. Worth a one-line comment explaining
  "this is the only tick site" so a future refactor
  doesn't accidentally move it to `main_game_loop` and
  lose the focused-loop coverage.
- The `debug.cc` typo fix affects any caller passing
  a non-`"wt"` mode string. The only caller in the
  codebase is `debug_register_env` at `debug.cc:101`,
  which uses `"wt"`. No regression risk in this tree.
  External callers (e.g., mods or test harnesses that
  link against the engine) would change behavior.

### Resolved-but-not-retested

The plan's "Risks" section lists five items
(`plan.md:427-482`). The implementation addresses all
five with the same mitigation as the plan:

1. Old-engine state: `companionCollectSnapshot` tolerates
   null `obj_dude` (`companion_snapshot.cc:17-19`).
2. Socket portability: POSIX-only with `#if !defined(_WIN32)`
   guards and stubs.
3. Main-loop interference: non-blocking I/O, small payloads.
4. Protocol drift: `schemaVersion` is in the wire format.
5. Player availability on menus: the implementation
   *implements* the buggy behavior the plan warns about
   (`hasPlayer = obj_dude != nullptr`),
   then defers the fix to step 2. The audit confirms
   this is what the plan said to do — no surprise, but
   worth confirming with the user that step 2 is
   actually going to fix this before any external
   consumer depends on `playerAvailable` for non-HP
   purposes.

### Residual risk

- The protocol is not versioned beyond `schemaVersion:1`.
  A future change that adds a field (e.g., a new
  entity) needs a `schemaVersion` bump. There is no
  schema-evolution test.
- The Windows path is stubs. Anyone building on Windows
  will get a working game with a non-functional
  companion server. The diff does not add a build-time
  warning, and the plan does not mention Windows in the
  test matrix.

---

## 5. Cross-Cutting Concerns

### What is good

- Module isolation is clean. `companion_snapshot` has
  zero socket or JSON awareness; `companion_protocol`
  has zero socket or engine awareness; `companion_server`
  is the only file that knows about both.
- The diff is localized. Five engine files touched
  (`main.cc`, `input.cc`, `debug.cc`, plus CMake and
  `.gitignore`), and the touched lines are minimal.
- The plan was followed. The protocol, the state
  machine, the sampling cadence, the tick site, the
  lifecycle, and the error model all match the plan.
- The non-blocking discipline is uniform. No
  `connect`/`read`/`write` in the diff — only
  `recv`/`send` with `MSG_DONTWAIT` and `accept` on a
  listener set to `O_NONBLOCK`.
- The init failure mode is fully isolated. The game
  starts and runs even if the port is in use, the
  socket call fails, or the bind is denied. This is
  a real win for developer ergonomics.

### What is acceptable but worth flagging

- `companion_server.cc` is 548 lines for a step-1
  module. The bulk is the file-scope state and the
  per-tick functions. For step 1, this is fine; for
  step 2, splitting the state machine into a separate
  `companion_state.cc` would be a natural refactor.
- The outbound buffer is a `std::string` with
  O(N) `erase` from the front. See "Performance notes".
- The parser is hand-rolled and minimal. The plan
  endorses this. If step 2 ever adds `get_entity`
  with parameters, the parser has to grow — a real
  JSON library is the right answer at that point,
  not a more elaborate hand-rolled one.
- `companionEnableDebugLog` is a deliberate
  workaround. The comment marks it as such
  (`companion_server.cc:410-413`). Good practice.

### What should be fixed before step 2

These are not blockers for step 1 closure. They are
the things the next milestone will trip over if not
addressed:

1. **Sync the tickets doc with the actual integration
   shape.** T1 should describe the `process_bk` tick
   site, not `main_game_loop`; the combat-loops claim
   is obsolete; the file count is 6, not 3.
2. **Tighten the plan / tickets on "drop on unknown
   message".** Both currently say "first message" but
   the implementation drops on any post-handshake
   message. Pick one wording and apply it to plan,
   tickets, and a one-line comment in
   `handleClientMessage`.
3. **Add a tiny automated test harness.** A 50-line
   Python script that opens a socket, sends `hello`,
   reads `world`, sends `get_snapshot`, reads
   `snapshot`, and asserts `seq == 1`, `playerAvailable`
   is a bool, and the `data.player.hp` matches
   `obj_dude->…` would catch regressions cheaply. The
   tickets' "validation log" is good evidence but is
   not repeatable.
4. **Decide on `127.0.0.1` default before any
   external consumer is built.** The plan defers this
   to step 2 and the diff binds to `0.0.0.0`. As long
   as step 2 lands before any consumer is released,
   this is fine.

### Things that were checked and are clean

- No `std::thread`, `std::async`, `pthread_create`,
  `CreateThread`, or any other threading primitive
  in the diff.
- No new third-party libraries.
- No new global state in the engine. The two
  new file-scope symbols (`idle_func` is pre-existing;
  `gOriginalIdleFunc`/`gIdleHookInstalled` are file-scope
  inside the companion module).
- No `new`/`delete`/`malloc`/`free` in the companion
  modules. All allocation is in `std::string` (the
  outbound buffer and the per-message strings), and
  the fixed-size 4 KiB inbound buffer is in BSS.
- No locale-dependent output in the protocol. Field
  values are integers; booleans are `"true"`/`"false"`
  in English. Good for a wire format.
- The wire format does not depend on byte order.
  `htons` is used for the port (`companion_server.cc:453`);
  integers in the JSON are decimal. Correct.
- No use of `sprintf` (unbounded). All formatting is
  via `snprintf` with a stack buffer and a length check.
- All platform-specific code is guarded.

---

## 6. Verdict

**Approve.** The implementation is a faithful, minimal,
and well-isolated delivery of the plan. The plan itself
is sound and the tickets' T7 validation log is concrete
evidence that the happy path and several failure paths
have been exercised.

The optional follow-ups above (sync tickets, add a
repeatable test harness, tighten the "drop on unknown
message" wording, decide on `127.0.0.1` before any
consumer ships) are step-2 prep, not step-1 blockers.

### Follow-ups (priority order)

1. **Tickets doc drift** — sync T1 with the actual
   `process_bk` integration, the 6-line CMake change,
   and the absence of `combat.cc` edits. *Low effort,
   high clarity win.*
2. **Plan/tickets wording** — change "unknown first
   message" to "unknown message" in the drop-on-error
   rule, or change the implementation to match.
   *Low effort, removes a future surprise.*
3. **Automated protocol smoke test** — a small
   Python script in `scripts/` that asserts `seq` starts
   at 1, `world` has no `seq`, `snapshot` has no
   `entity`, and `update` is partial. *Medium effort,
   high regression value for step 2.*
4. **Add a one-paragraph comment block at the top of
   `companion_protocol.cc`** describing the wire format
   so a future engineer does not have to read the plan
   to understand the file. *Low effort, doc win.*
5. **Drop the inner `#if !defined(_WIN32)` at
   `companion_server.cc:65`** — it's redundant under
   the outer guard at line 28. *Trivial, cosmetic.*
6. **Add a static assert on `CompanionConnection`
   size or layout** so future field additions do not
   silently break the positional initializer at
   `companion_server.cc:78-88`. *Trivial, future-proof.*
7. **Decide on `127.0.0.1` default** in step 2 before
   any external consumer is released. *Tracked in plan,
   not blocking step 1.*

### Must-fix

None.
