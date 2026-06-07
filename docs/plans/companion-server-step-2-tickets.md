# Companion Server Step 2 — Feature Tickets

Derived from `docs/plans/companion-server-step-1.md` (the seven candidates listed at lines 495–506) and from `AGENTS.md` (the auth and bind-host parts of the step-1 security note, now narrowed to required `companion_bind` + `companion_password` in `fallout.cfg`). This document breaks the milestone into trackable tickets. It does not redefine scope; it makes the milestone actionable.

## Scope Statement

Close the step-1 security gap, fix the step-1 player-availability correctness bug, and expand the synchronized model to position, map, and inventory. The server only runs when both `companion_bind` and `companion_password` are present in the `[companion]` section of `fallout.cfg`; otherwise it is in `disabled` and the main menu shows a single-line hint. Bind host and password are both required; there is no no-password mode. The auth handshake is `auth` (constant-time compared) → `hello` → `world`. **The `update` and `snapshot` wire shapes are redesigned in T0 before T3–T5 land; see T0 for the new shape.** The milestone adds no new thread model. Game remains authoritative and must not be observably affected by the server's presence or absence.

## Out Of Scope (Step 2)

- No generalized engine event bus. Sampling and diffs only.
- No engine mutation. The companion is read-only for game state. Commands (T6) are limited to a small, explicit allowlist; they do not generalize into a scripting surface.
- No new third-party dependencies. JSON stays hand-rolled. UDP discovery in T7 is `sendto`/`recvfrom` only.
- No Windows socket implementation. POSIX only. Windows remains empty stubs that satisfy the linker.
- No multi-client. The single-client constraint from step 1 carries forward.
- No HTTP, no WebSocket. T7 adds UDP, not a new request/response transport.
- No new UI beyond a single non-interactive main-menu hint line in T1. The hint is informational only; it has no button, no click target, and no settings screen.
- No screenshots, no audio streaming, no file I/O on behalf of the client. These are larger features and belong to a later milestone if requested.

## Cross-Cutting Constraints

- **Step-1 invariants are preserved.** Non-blocking, single-thread, single-client, hand-rolled JSON, sampled-with-change-detection for any new field added by T2–T5. A step-1 client that does not know `auth` is always dropped at the `auth` step (the "unknown first message" path), which is the correct behavior. There is no no-password mode.
- **T0 is the explicit exception to additive-only protocol changes.** T0 is a breaking change to the `update` and `snapshot` wire shapes. The `schemaVersion` bump from 2 to 3 makes the break visible. A step-1/step-2 client that hard-asserts `== 2` will refuse; a step-1/step-2 client that ignores the field will fail because the old `data.player.hp` path is gone. T0 must land before T3, T4, and T5 because they all add new `update` fields and the dispatch model needs to be settled first.
- **No allocation in the steady state path.** Reuse the same buffer strategy as step 1. The inventory serialization in T4 is the highest-risk path and must be measured before being accepted.
- **Fail closed.** Any parse error, auth failure, unknown message, or socket error drops the client and returns the server to `listening`. Game state untouched.
- **Localized diff.** Touch only the three step-1 files plus the new files introduced by individual tickets, the two `main.cc` integration points, the tick sites in `src/plib/gnw/input.cc`, the `gconfig.h` / `gconfig.cc` config-key additions for T1, the `mainmenu.cc` hint line for T1, and the build system. Nothing else.
- **Engine investigation is part of the ticket, not a prerequisite.** Tickets that need new engine signals (T2, T3, T4) include "investigate and document" as the first bullet. Do not silently assume APIs exist.
- **Per-domain change detection.** Each new domain (position, map, inventory) has its own `last_sent_*` cache and its own diff. A position change does not re-emit an inventory update and vice versa.

## Hidden Assumptions (To Verify During Implementation)

These are the facts each ticket depends on. Step 1's verified facts (`obj_dude`, `critter_get_hits`, `stat_level`, `compat_timeGetTime`, `debug_printf`, `set_idle_func`/`get_idle_func`, `process_bk`) carry forward unchanged. The following are step-2-specific and have **not** been verified at the time of writing this document. Each ticket that touches an assumption must verify it first and update this section.

- **Config API for the bind host and password.** `fallout.cfg` is parsed into a global `Config game_config` (declared at `src/game/gconfig.h:116`, defined at `src/game/gconfig.cc:18`). The string reader is `config_get_string(Config*, section, key, &outPtr)` at `src/game/config.cc:114`, which returns `true` if the key is present and writes a `char*` into `outPtr`. Existing key/section naming convention is `GAME_CONFIG_<SECTION>_KEY` for sections and `GAME_CONFIG_<SECTION>_<KEY>_KEY` for keys, all `#define`s in `src/game/gconfig.h`. T1 follows this convention for a new `[companion]` section with a `bind` key and a `password` key. Both keys must be present for the server to be enabled; the absence of either is the disabled state. (To verify by reading `src/game/config.cc:114` and `src/game/gconfig.h:1-90`.)
- **`fallout.cfg` is plaintext on disk.** The password will be stored in cleartext in the user's `fallout.cfg`. The threat model is "keep a LAN peer off the server," not "defend against malware on the same box." No hashing, no external credential store. This ceiling is documented and accepted.
- **`gconfig_init` runs before `companionServerInit`.** Step 1 already calls `companionServerInit` from `main_init_system` in `src/game/main.cc:224`. The relative ordering of `gconfig_init` and `companionServerInit` in `main_init_system` must be verified: the config must be initialized before the companion server reads it. (To verify by reading `src/game/main.cc:224-244`.)
- **Main-menu / intro / world-map signals.** The step-1 plan notes that `map_get_index_number() == -1` for the world map and presumably the main menu, but a real disambiguation needs at least one more signal. Candidates to investigate: `in_main_menu` (if it exists), the active `gsn_*` script state, the `gdialog_*` / `barter_*` / `dialog_*` state machines, the world-map engine state, and any "is the game paused for a movie" flag. (To verify by searching `src/game/`, `src/intlib/`, and `src/platform_compat/`.)
- **Player position storage.** Step 1 sampled HP through stable APIs. Position may be accessible as `obj_dude->tile` (or a similar field on `Object`), or via a dedicated function. (To verify by reading `src/game/object.h` and the critter/object accessors in `src/game/critter.h` / `src/game/object.cc`.)
- **Inventory mutation API.** The Fallout 1 inventory is large. The minimal model in T4 needs an iterator over `obj_dude`'s inventory and a way to read item id, count, and equipped state. The hooks T5 would need for true event detection may not exist; T5 is allowed to fall back to diff-based detection. (To verify by reading `src/game/inventry.h` / `src/game/inventry.cc` and the obj inv helpers.)
- **UDP broadcast on the dev platform.** T7 needs `SO_BROADCAST` and the loopback / LAN address resolution. Linux is fine; the existing POSIX-only constraint carries forward. (To verify by reading the existing socket setup in `src/companion_server.cc` and the `bind`/`listen` calls.)

## Resolved Decisions

1. **Auth handshake shape.** A new client message `{"type":"auth","password":"<string>"}` is the first message a step-2 server accepts. The server is enabled only when both `companion_bind` and `companion_password` are present in `fallout.cfg`; otherwise the server is in `disabled`. There is exactly one enabled mode: `awaiting_auth`. The first message must be `{"type":"auth","password":"..."}` with a password that matches `config_get_string` exactly. A `{"type":"hello"}` arriving as the first message is rejected as an unknown first message (drops the client, server returns to `listening`). After a correct `auth`, the connection transitions to `awaiting_hello`; the existing `hello` / `world` / `get_snapshot` / `update` flow runs unchanged. The password comparison is constant-time against the entire configured password. An `auth` with a missing `password` field is treated as an empty-password attempt, which will fail because the configured password is non-empty (it must be present for the server to be enabled).
2. **Password format.** A free-form UTF-8 string read from `fallout.cfg` via `config_get_string`. There is no length cap beyond what the config subsystem allows. The string is treated as opaque bytes for comparison; no normalization, no trimming, no case folding. An empty string is a valid configured password; the user is not second-guessed.
3. **Bind host.** Read from `companion_bind` in `fallout.cfg`. No default value: if the key is absent, the server is disabled. The accepted formats match whatever `inet_pton(AF_INET, ...)` accepts for an IPv4 dotted-quad; the existing POSIX `inet_pton` path in `companion_server.cc` is reused. A user who wants the step-1 LAN-reachable behavior sets `companion_bind=0.0.0.0`; a user who wants localhost-only sets `companion_bind=127.0.0.1`.
4. **Bind port.** `28080`. Hardcoded. Not overridable in milestone 2.
5. **`schemaVersion` bump.** `world` reports `schemaVersion: 2`. The bump is unconditional. Step-1 clients that hard-assert `== 1` will refuse; step-1 clients that ignore the field will be dropped at the `auth` step (correct behavior). No deprecation period, no dual-version support.
6. **Player-availability signal (T2 contract).** `hasPlayer` is true only when **all** of: `obj_dude != nullptr`, the engine reports a real map loaded (the existing `map_get_index_number() != -1` check), the main menu / intro / world-map state is false (the new check T2 adds), and no fullscreen movie is playing. The exact combination is T2's engineering output; this section only fixes the contract.
7. **Position sampling cadence.** Same 500 ms cadence as HP. Position and map-id are sampled in the same tick; if both changed in the same interval, both kinds' updates fire in that tick (vitals is independent of position). The `payload` of every `update` is the *complete* per-kind object (T0 refinement; see Decision #13).
8. **Inventory model (T4 contract).** Flat array of `{id, count, equipped}`. No slots, no weight, no condition, no ordering beyond "as returned by the engine iterator." The array is the full inventory on every `snapshot` and on every `update` (T0 "always full" principle applies to T4 as well; see Decision #13).
9. **Inventory change detection.** T5 emits one `update` per kind (`player.inventory`) whose `payload` is the full inventory array. The server's diff against its `lastSent` decides whether to call the builder; the protocol layer is pure formatting. If the inventory iterator is not stable across calls, T5 falls back to comparing the full arrays per slot and emitting on any change, and the ticket is marked partial.
10. **Commands (T6 contract).** Server accepts `{"type":"cmd","id":N,"name":"X","args":{...}}` and replies with `{"type":"cmd_ack","id":N,"ok":true|false,"error":"..."}`. The initial allowlist is exactly two commands: `ping` (no args, always ok) and `get_snapshot` (no args, behaves like the step-1 client message). This validates the command channel end-to-end without inventing new engine behavior.
11. **UDP discovery (T7 contract).** Server broadcasts `{"type":"announce","game":"fallout1-ce","schemaVersion":2,"host":"<bind host>","port":28080,"authRequired":true}\n` to `255.255.255.255:28080` once per second, only when a client is **not** currently connected. The `host` field is the value of `companion_bind`. `authRequired` is unconditionally `true` (the only enabled mode is auth-required). The password is **never** broadcast; clients must obtain the password through a separate channel (today: read it from the host's `fallout.cfg`). Discovery is a hint, not a substitute for the password.
12. **Slow-consumer policy.** Unchanged from step 1. The 256 KiB outbound cap applies to all new message types. UDP is a separate concern: T7 uses fire-and-forget `sendto` and does not maintain a per-client outbound buffer for discovery.
13. **T0 protocol shape (the design this milestone implements).** Every server-to-client message except `world`, `player_unavailable`, `cmd_ack`, and `announce` carries a `payload` object whose schema is determined by a `kind` string. `update` adds a top-level `kind`; `snapshot` is a `payload` that is itself a kind→object map. The `entity` field is removed. Kinds are namespaced as `player.<aspect>`. The current set: `player.vitals`, `player.local_location`, `player.world_location`; `player.inventory` is added by T4. `world.schemaVersion` is `3`. **Every `update.payload` is the complete per-kind object (T0 refinement).** The server compares each tick's sample to a `lastSent: CompanionSnapshot` and calls a builder only when a kind's fields (or, for location kinds, the current surface) differ. A surface change force-emits the new kind's update even if its numeric fields match the stale `lastSent` (which holds the other surface's data). Future kinds follow the same pattern: one builder per kind, one `lastSent` slot, server-side diff.

## Top-Level Success Criteria (For Closing Step 2)

1. The server only starts when `fallout.cfg` has both `companion_bind` and `companion_password` set in the `[companion]` section. If either key is missing, or the file is missing or unreadable, the server is in `disabled` and the main menu shows the hint line. The game starts and runs normally in either case.
2. When the server is enabled, the bind host is exactly what `companion_bind` says and the port is `28080`. A client on the LAN can reach the listener only if the bind host is reachable from the client.
3. When the server is enabled, a `{"type":"hello"}` as the first message drops the client (the only first message accepted is `auth`). A `{"type":"auth","password":"<correct>"}` is accepted and transitions to `awaiting_hello`; a `{"type":"auth","password":"<wrong>"}`, a `{"type":"auth","password":""}` (when the configured password is non-empty), or a `{"type":"auth"}` (no `password` field) all drop the client. A constant-time compare is used.
4. The mode (`disabled` or `awaiting_auth`) is decided at `companionServerInit` and is immutable for the lifetime of the process. Changing `fallout.cfg` requires a restart.
5. `world.schemaVersion` is `3`. All other step-1 message shapes and field names are preserved when the server is enabled except where T0 explicitly supersedes them (the `update`/`snapshot` payload shape; the `entity` field removal). The new `auth` message is added to the protocol. The authoritative wire-shape spec is the T0 ticket; this criterion is a pointer to it.
6. `playerAvailable` is `false` on the main menu, during the intro movie, on the world map, and between maps. `playerAvailable` is `true` only during real gameplay. Verified manually for each state.
7. `snapshot.payload` is a kind→object map. When a player is loaded, it includes `player.vitals` (with `hp`, `maxHp`) and exactly one of `player.local_location` (with `tile`, `elevation`, `map`, `location`, `locationId`) or `player.world_location` (with `x`, `y`). `update` for a kind carries the complete per-kind object (T0 "always full" principle), not a field-level diff. The server emits an `update` only when the kind's fields (or the current surface) differ from `lastSent`.
8. `snapshot.payload["player.inventory"]` is a non-empty flat array of `{id, count, equipped}` during real gameplay (T4, deferred). Picking up or dropping an item produces a `player.inventory` `update` within 500 ms (T5, deferred). Equipping or unequipping produces a `player.inventory` `update`. Both follow the T0 "always full" principle: the update's `payload` is the full inventory array.
9. A step-2 client can send `{"type":"cmd","id":1,"name":"ping","args":{}}` and receive `{"type":"cmd_ack","id":1,"ok":true,...}` with the same `id`. The `id` echo proves the request/response pairing works.
10. A step-2 client can send `{"type":"cmd","id":2,"name":"get_snapshot","args":{}}` and receive a `cmd_ack` followed by a `snapshot` message (or the snapshot is the ack payload; the contract is fixed in T6).
11. A `nc -u -l 28080` listener on the same machine receives the JSON announce broadcast from a step-2 server. The broadcast includes `host` (the configured `companion_bind`), `port` (28080), `schemaVersion` (3), `authRequired` (`true`), and never includes the password. The broadcast stops while a TCP client is connected and resumes within 1 second after disconnect.
12. The main menu hint line reads `Companion server: disabled (set [companion] bind + password in fallout.cfg)` and is drawn once during `main_menu_create()`. It is purely informational: no button, no input handler, no settings screen. The hint is drawn only when the server is in `disabled`.
13. Game starts, runs, and shuts down identically with the server enabled and no client connected, with the server disabled, with or without a UDP listener. The `fallout.cfg` is read at `companionServerInit`; a missing or unreadable `fallout.cfg` is treated as "server disabled."
14. All twelve plan deliverables in the milestone 1 plan remain demonstrably met for the enabled case; the disabled case is a new post-step-1 state and is verified by the absence of a listening socket.

---

## Tickets

### T0 — Protocol Redesign: Kind-Discriminated `update` and `payload` Everywhere

**Status:** done

**Implementation notes:**

- `companion_snapshot.h` splits the previous `CompanionPlayerSnapshot` into three per-kind structs: `CompanionPlayerVitals` (hp, maxHp), `CompanionPlayerLocalLocation` (tile, elevation, map, location, locationId), `CompanionPlayerWorldLocation` (x, y). `CompanionSnapshot` becomes a small aggregator with `hasPlayer`, `surface`, and the three substructs. The old `companionPlayerSnapshotEquals` helper is dropped; per-kind comparison lives in the server.
- `companion_protocol.h` drops `companionBuildPlayerUpdate` and exposes three per-kind builders: `companionBuildVitalsUpdate`, `companionBuildLocalLocationUpdate`, `companionBuildWorldLocationUpdate`. Each takes `(seq, current)` and emits the `kind`-tagged `update` with the *complete* per-kind object in `payload`. There is no `lastSent` parameter: the protocol layer does no diffing; the server decides whether to call a builder by comparing the current sample to its own last-sent state. `companionBuildSnapshot` is rewritten to emit the new kind→object map shape; the wrapper field is renamed from `data` to `payload`. `world`, `player_unavailable`, and the client-side parsers are unchanged.
- `companion_server.cc` holds a single `lastSent: CompanionSnapshot` plus a `lastSentPrimed` bool on `CompanionConnection`. The diff is done inline in `sampleReadyClient`: vitals differ → emit `player.vitals`; surface changed or local-location fields differ → emit `player.local_location`; surface changed (to World) or world-location fields differ → emit `player.world_location`. A surface change force-emits the new kind's update even if its numeric fields happen to match the stale `lastSent` (which holds the *other* surface's data). The per-kind `*Differ` helpers (`vitalsDiffer`, `localLocationDiffer`, `worldLocationDiffer`) are local to the anonymous namespace.
- The `auth` parser and password extractor now accept the spaced form `{"type": "auth"` (Python's `json.dumps` default) in addition to the compact form `{"type":"auth"`. This was a pre-existing bug discovered during live smoke-testing: the step-1/step-2 smoke test had never been run end-to-end against a real server, so the standard `json.dumps` output was never exercised. Fix is localized to `companionParseClientMessage` and `companionExtractAuthPassword`.
- Wire header comment in `companion_protocol.cc` is rewritten to describe the new shape, the kind list, and the "always full payload" semantics.
- The protocol test at `/tmp/opencode/protocol_test.cc` is rewritten to assert the new shape; ~60 assertions cover the builders (always-full payloads for each kind), the `kind` discriminator, the `payload` field, the surface transition (forced emit), and the unchanged `world` / `player_unavailable` / parser paths.
- `world.schemaVersion` is bumped from `2` to `3`. The T1 implementation note that records the `2` bump is left in place as history; the new authoritative value is in the protocol header.

**Design refinement during live testing:**

The original T0 design had `update.payload` as a field-level diff (per-field partial emission). Live testing against a running game revealed that this created a desync window: a client that missed the snapshot (or hadn't requested one yet) only got partial fields and didn't know the full state of a kind. The "snapshot-first" expectation was implicit and easy to violate. The T0 design was refined to "always full payload" at the protocol layer, with the server still doing a diff to decide whether to call a builder. This is a refinement, not a wire-shape break: clients that read fields defensively work with both. `schemaVersion` stays at `3`.

**Verification:**

- The protocol-layer test at `/tmp/opencode/protocol_test.cc` covers the new builders and the unchanged parsers.
- The build (`cmake --build build --target fallout-ce`) passes. The companion-server change is protocol- and dispatch-layer only; the engine integration points (`process_bk`, idle hook, main-menu hint, config keys) are untouched.

**Goal:** Replace the current monolithic `update.data` field with a kind-discriminated payload model. Each `update` carries exactly one `kind` whose `payload` matches that kind's schema. The `snapshot` message becomes a kind→object map. This makes client dispatch explicit (the `kind` tag) and lets future per-kind additions land without breaking unrelated clients. The `entity` field is removed; the `entity` is now part of the `kind` namespace (e.g., `player.vitals`). The wrapper field is renamed from `data` to `payload` for both `update` and `snapshot` so the client always knows where the structured content lives.

**Why this is T0, not a follow-up ticket:**

- The current `update.data` is *already* a field-level diff, but the field set is implicit. A client has to inspect the keys to know which aspect of the player changed. The same flat object carries vitals, local position, and world position depending on what changed. This is the implicit-dispatch problem the redesign is solving.
- T3, T4, and T5 are all about *adding more fields to that same implicit blob*. Each one makes the dispatch problem worse. T0 must land before any of them.
- T1 (auth + bind + password) does not need this, but T0 invalidates one fact in T1 — the `schemaVersion` bump from `1` to `2` is now superseded by T0's bump from `2` to `3`. T1's auth path, constant-time compare, disabled state, and main-menu hint are unchanged.

**Scope:**

- Wire shape changes in `companion_protocol`:
  - `update` adds a top-level `kind` field. Valid values in T0: `"player.vitals"`, `"player.local_location"`, `"player.world_location"`. T4 adds `"player.inventory"`.
  - `update` removes the top-level `entity` field.
  - `update.data` is renamed to `update.payload`. The `payload` shape is per-kind.
  - `snapshot.data` is renamed to `snapshot.payload`. The `payload` is a kind→object map containing only the kinds valid in the current state.
  - `world.schemaVersion` bumps from `2` to `3`. Hard break.
- Code changes in `src/companion_protocol.{h,cc}`:
  - Drop `companionBuildPlayerUpdate`. Replace with the three per-kind builders.
  - Each builder takes `(seq, current)` and emits a `kind`-tagged `update` with the *complete* per-kind object in `payload`. There is no `lastSent` or `playerAvailable` parameter: the protocol layer does no diffing and the envelope's `playerAvailable` is hardcoded to `true` (the server only calls an update builder while the player is loaded).
  - `companionBuildSnapshot` emits the new kind→object map shape.
  - The wire-format comment at the top of `companion_protocol.cc` is rewritten.
- Code changes in `src/companion_snapshot.{h,cc}`:
  - Split `CompanionPlayerSnapshot` into per-kind structs (`CompanionPlayerVitals`, `CompanionPlayerLocalLocation`, `CompanionPlayerWorldLocation`).
  - `CompanionSnapshot` becomes a small aggregator.
  - Drop `companionPlayerSnapshotEquals`; per-kind comparison lives in the server.
- Code changes in `src/companion_server.cc`:
  - Replace the per-kind `lastSent*` slots and `primed` flags with a single `lastSent: CompanionSnapshot` plus a `lastSentPrimed` bool on `CompanionConnection`.
  - Replace the three `queue*UpdateIfNeeded` functions with inline dispatch in `sampleReadyClient`.
  - On surface change, the `surface` field in `lastSent` differs from the current surface, which force-emits the new kind's update on the next sample.
- No changes to: `world`, `player_unavailable`, the auth/hello/`get_snapshot`/`cmd`/`cmd_ack` client messages, the step-1 contracts for `hasPlayer` and constant-time compare, the engine integration points, the config keys, the main-menu hint, the build system.

**Wire shapes:**

```json
// Snapshot: payload is a kind->object map. Only valid kinds are present.
{"type":"snapshot","seq":1,"playerAvailable":true,"payload":{
  "player.vitals":          {"hp":30,"maxHp":40},
  "player.local_location":  {"tile":12345,"elevation":0,"map":3,"location":"Vault 13","locationId":"VAULT13"}
}}

// Vitals update: full payload (always, regardless of which subfield changed).
{"type":"update","seq":2,"playerAvailable":true,
 "kind":"player.vitals",
 "payload":{"hp":28,"maxHp":40}}

// Vitals update: maxHp changed (still full payload).
{"type":"update","seq":3,"playerAvailable":true,
 "kind":"player.vitals",
 "payload":{"hp":30,"maxHp":50}}

// Local location update: full payload (all 5 schema fields).
{"type":"update","seq":4,"playerAvailable":true,
 "kind":"player.local_location",
 "payload":{"tile":12346,"elevation":0,"map":3,"location":"Vault 13","locationId":"VAULT13"}}

// Local location update: map changed (still full payload; `location` is JSON
// `null` when the engine has no localized name for the new map).
{"type":"update","seq":5,"playerAvailable":true,
 "kind":"player.local_location",
 "payload":{"tile":12345,"elevation":0,"map":5,"location":"Junktown","locationId":"JUNKKILL"}}

// World location update: full payload.
{"type":"update","seq":6,"playerAvailable":true,
 "kind":"player.world_location",
 "payload":{"x":12,"y":20}}

// player_unavailable: no `kind`, no `payload`.
{"type":"player_unavailable","seq":7,"playerAvailable":false}
```

**Payload semantics (always full, server-side diff):**

- Every `update.payload` is the *complete* per-kind object (all schema fields present). There is no field-level diff at the protocol layer. A client that receives an `update` can merge it into its current state without having to first `get_snapshot`.
- The server decides whether to call a builder by comparing the current sample to its `lastSent` snapshot. If a kind's fields (or, for location kinds, the current surface) differ from `lastSent`, the server calls the builder and updates `lastSent`. If nothing changed, the server does not call the builder.
- The server's diff is the only place "what changed" is computed. The protocol layer is pure formatting.

**Surface transition handling:**

When the player transitions between the local and world surface:

- The new surface's kind is force-emitted on the next sample, regardless of whether the new state's numeric fields match the stale `lastSent` for that kind. Implementation: the server compares `lastSent.surface` with `current.surface`; if they differ, the new kind is force-emitted. This covers both directions (local→world and world→local) and handles the "return to a numerically-identical previous tile after visiting the world map" case correctly.
- The old surface's kind is not emitted on transition. The client infers the surface change from the new kind appearing on the wire (e.g., a `player.world_location` update is itself the signal that the player is on the world map).
- A return to a numerically-identical tile *without* a surface change is a no-op: the fields match `lastSent`, and the server does not emit an `update`. This is the intended behavior under the "always full" semantics: the state did not change, so there is nothing to send.

**Acceptance:**

- `world.schemaVersion` is `3`.
- `update` messages carry exactly one `kind` and a `payload` object whose keys are the complete schema for that kind. There is no `entity` field, and there are no partial payloads.
- `snapshot.payload` is a JSON object whose keys are kinds and whose values are the per-kind full state. Only kinds valid in the current state are present.
- A step-1 client (no `auth`, no `kind`) is still dropped at the auth step.
- A step-2 client (no `kind`, looking for `data.player.hp`) is broken: that path no longer exists on the wire. This is the intentional breaking change; the bump to 3 makes it visible.
- The T1 success criteria (auth, disabled state, main-menu hint, constant-time compare, no-password-is-not-an-option) continue to pass byte-for-byte: T0 does not touch the auth path or the config subsystem (the parser now also accepts the spaced `{"type": "auth"` form, but the canonical compact form is unchanged).
- The T2 success criteria (player-availability signal) continue to pass: T0 does not touch the helper or the snapshot collector's gating logic.
- A position change in real gameplay emits exactly one `update` whose `kind` is `player.local_location` (or `player.world_location` on the world map), never a `player.vitals` update.
- A vitals change emits exactly one `update` whose `kind` is `player.vitals`, never a location update.
- A surface transition (local ↔ world) force-emits the new kind's update on the next sample, even if the new state's numeric fields happen to match the stale `lastSent`.
- The protocol-layer test at `/tmp/opencode/protocol_test.cc` covers the new builders and the unchanged parsers, and passes.

**Notes:**

- The protocol surface from the server is now: `world` (handshake), `snapshot` (full state), `update` (per-kind diff), `player_unavailable` (transition), `cmd_ack` (command reply), `announce` (UDP discovery, T7). Six message types.
- T6 (commands) and T7 (UDP discovery) are unaffected: they do not use the `update` or `snapshot` shape.
- T4 (inventory) lands as a new `kind: "player.inventory"` with a separate snapshot map entry. The per-kind model is what makes T4 additive.
- T5 (inventory events) is deferred per the protocol discussion; when it lands, the decision between flat-state-diff vs structured-events will be revisited.
- The `schemaVersion` bump from 2 to 3 is unconditional. There is no dual-version support.

---

### T1 — Required Bind + Password in `fallout.cfg`, with Disabled State and Main-Menu Hint

**Status:** done

**Implementation notes:**
- `gconfig.{h,cc}` gain `GAME_CONFIG_COMPANION_KEY`, `GAME_CONFIG_COMPANION_BIND_KEY`, `GAME_CONFIG_COMPANION_PASSWORD_KEY` and a `gconfig_file_loaded()` accessor; no defaults registered, so the keys are pure opt-in.
- `companion_server.{h,cc}` gain the `Disabled` server state and the `AwaitingAuth` client state. `companionServerInit` reads both keys via `config_get_string` and refuses to bind if either is missing. `companionServerIsActive()` returns `true` only in `Listening`. Bind port stays hardcoded at `28080`. The idle hook is installed only when entering `Listening`.
- `companion_protocol.{h,cc}` gain `CompanionClientMessage::Auth`, `companionExtractAuthPassword` (hand-rolled exact-shape parser with whitespace tolerance, no escape handling), and the `schemaVersion: 2` bump on `world`.
- `mainmenu.cc` draws the disabled hint once at the same y=460 as the version string, left-aligned at x=15, using the same font and color.
- Constant-time compare (`companion_server.cc:143`) iterates over `max(configured, candidate)`, XORs missing bytes against zero, and checks the accumulator exactly once. No `memcmp` / `strcmp` on the password.
- Log lines: `enabled (bind=<bind>, port=28080)`, `disabled (missing companion_bind)`, `disabled (missing companion_password)`, `disabled (fallout.cfg missing or unreadable)`, `disabled (bind parse failed: <bind>)`, `auth accepted`, `auth rejected`, `client disconnected: non-auth first message`. The password value never appears in any log line.
- One server-side fix landed alongside: `processInboundLines` now handles the message *before* shifting the buffer (`companion_server.cc:337-368`). The old order corrupted the `string_view` returned by `companionExtractAuthPassword` whenever auth + hello arrived in the same `recv`; the new order guards the post-handler `memmove` with a `hasClient()` check so a handler-driven `disconnectClient` doesn't underflow `inboundLen`.

**Verification:**
- Protocol unit test (`/tmp/opencode/protocol_test.cc`, links `companion_protocol.cc`) covers parser, auth extraction, and all four server message builders. 44 assertions pass.
- The Python smoke test (`scripts/companion_smoke_test.py --password <pw>`) covers the full handshake, drop rules, and recovery. It could not be run end-to-end here because the game binary exits at `game_init` when `master.dat` is absent, before `companionServerInit` runs. The protocol-layer test plus the fix's localized nature cover the same code paths.

**Goal:** Make the companion server fully opt-in. The server only runs when both `companion_bind` and `companion_password` are present in the `[companion]` section of `fallout.cfg`. Otherwise it is in `disabled` and the main menu shows a single informational line telling the user what to do. When enabled, the server binds to `companion_bind` on port `28080` and requires an `auth` first message. The `auth` password is constant-time compared against `companion_password`. The `world` `schemaVersion` bumps from `1` to `2`. There is no no-password mode.

**Scope:**

- Config integration in `src/game/gconfig.h`:
  - Add `GAME_CONFIG_COMPANION_KEY "companion"` (new section).
  - Add `GAME_CONFIG_COMPANION_BIND_KEY "bind"` (new key).
  - Add `GAME_CONFIG_COMPANION_PASSWORD_KEY "password"` (new key).
  - No defaults registered in `gconfig_init` for any of the three new names. The keys are pure opt-in.
- Bind + password read in `src/companion_server.cc`:
  - In `companionServerInit`, after the listening socket setup would happen, read both keys. If either is missing, the server transitions to `disabled`, emits one error log line, and skips the listen/bind/listen sequence. The game still runs.
  - For the bind key: copy the value into a server-owned buffer. The original `game_config`-owned pointer is not freed. The buffer is passed to `inet_pton(AF_INET, ...)` in the existing bind path. The same port `28080` is used.
  - For the password key: copy the value into a server-owned buffer and store its length. The original `game_config`-owned pointer is not freed. The buffer is used by the constant-time compare on the auth path. The buffer lives until `companionServerExit`.
  - The disabled state is the new default. The enabled state is a strict superset of step 1's running state plus the auth requirement.
- New protocol message in `src/companion_protocol.{h,cc}`:
  - Add a third `CompanionClientMessage` value: `Auth`, parsed from `{"type":"auth","password":"<string>}`.
  - The parser extracts the `password` field as a `std::string_view` into the original input buffer. The buffer is owned by the inbound connection state and outlives the auth compare.
  - Field order tolerance and exact-shape parsing rules from step 1 carry forward. A `{"type":"auth"}` without a `password` field is `Invalid`. A `{"type":"auth","password":""}` is a valid `Auth` with an empty password candidate; the compare will fail against a non-empty configured password.
  - `companionBuildWorld` bumps `schemaVersion` from `1` to `2`. All other fields are unchanged.
- State machine changes in `src/companion_server.cc`:
  - The per-server `ServerState` gains one variant: `Disabled` (the new default). `Listening` is entered only after the bind+password check succeeds. The disabled state does not open a socket and does not install the idle hook. (The idle hook is no longer needed because the disabled server has nothing to tick. The hook is installed only when the server enters `Listening`.)
  - The per-connection `ClientState` gains one variant: `AwaitingAuth`. The accept path sets the new connection to `AwaitingAuth`. There is no `AwaitingHello` start state when the server is enabled; the only path to `Ready` is `AwaitingAuth` → `AwaitingHello` → `Ready`.
  - In `AwaitingAuth`, only `Auth` is accepted. `Hello` is rejected as an unknown first message. A wrong or missing `password` field is rejected (drop, back to `Listening`). A correct `auth` transitions to `AwaitingHello`.
  - In `AwaitingHello`, only `Hello` is accepted. `Auth` is rejected as an unknown first message. `Hello` transitions to `Ready` and the existing `world` reply runs.
  - In `Ready`, the existing rules from step 1 apply (`GetSnapshot` accepted, `Hello` silently ignored, anything else drops).
- Constant-time password compare in `src/companion_server.cc`:
  - Implementation: XOR each byte of the candidate against the corresponding byte of the configured password, OR-ing into a running accumulator, then check the accumulator once at the end. The loop runs over `max(configuredLen, candidateLen)` iterations. When the candidate is shorter, the missing bytes are XOR'd against zero. When the configured is shorter, the missing bytes are XOR'd against the candidate. The accumulator is checked exactly once at the end. Do not use `strcmp`, `memcmp`, or any early-exit comparison.
  - Document the threat model in a code comment: this defends against LAN-local timing attacks, not against malware on the same host (the password is plaintext in `fallout.cfg`).
- Main-menu hint in `src/game/mainmenu.cc`:
  - Add a new query function `bool companionServerIsActive()` in `companion_server.h`. The function returns `false` when the server is `Disabled` and `true` otherwise.
  - In `main_menu_create()`, after the existing version-string `win_print` call at `mainmenu.cc:151`, add a single conditional `win_print` call drawing the hint string `"Companion server: disabled (set [companion] bind + password in fallout.cfg)"` if `companionServerIsActive()` is `false`. Use the same font (`text_font(100)`) and color (`colorTable[21204] | 0x4000000 | 0x2000000`) as the existing version string. Position: directly below the version string at y=460, left-aligned, x=15. No new font, no animation, no button. Purely informational.
  - The hint is drawn once when the main menu is created. The server's enabled/disabled state does not change at runtime, so a one-shot draw is sufficient.
- Logging:
  - On init, log one of: `companion: enabled (bind=<bind>, port=28080)`, `companion: disabled (missing companion_bind)`, `companion: disabled (missing companion_password)`, `companion: disabled (fallout.cfg missing or unreadable)`. The bind value is logged; the password value is never logged.
  - Log `auth accepted` and `auth rejected` on the new transitions. The `auth rejected` line must not include the password candidate.
  - Log `client disconnected: non-auth first message` (or similar) for the new `Hello`-in-`AwaitingAuth` rejection path, matching the step-1 "non-hello first message" log shape.

**Acceptance:**

- With neither `companion_bind` nor `companion_password` in `fallout.cfg`:
  - The server is in `disabled`. No listening socket is opened. `nc 127.0.0.1 28080` is refused.
  - The main menu shows the hint line. The game starts and runs normally.
  - The `companion: disabled (missing companion_bind)` log line is emitted at init.
- With `companion_bind=0.0.0.0` but no `companion_password`:
  - The server is in `disabled`. The main menu shows the hint.
  - The `companion: disabled (missing companion_password)` log line is emitted at init.
- With `companion_password=foo` but no `companion_bind`:
  - The server is in `disabled`. The main menu shows the hint.
  - The `companion: disabled (missing companion_bind)` log line is emitted at init.
- With both `companion_bind=0.0.0.0` and `companion_password=foo`:
  - The server is in `Listening` on `0.0.0.0:28080`. The main menu does **not** show the hint.
  - `{"type":"hello"}\n` as the first message drops the client. The log line is `client disconnected: non-auth first message` (or equivalent).
  - `{"type":"auth","password":"foo"}\n` is accepted. The connection transitions to `AwaitingHello`. A subsequent `{"type":"hello"}\n` returns `{"type":"world",...,"schemaVersion":2,...}`. The behavior from there is byte-identical to step 1.
  - `{"type":"auth","password":"bar"}\n` drops the client.
  - `{"type":"auth","password":""}\n` drops the client (empty candidate, non-empty configured).
  - `{"type":"auth"}\n` (no `password` field) is parsed as `Invalid` and drops the client.
  - The `companion: enabled (bind=0.0.0.0, port=28080)` log line is emitted at init. The password value does not appear in any log line.
- With both `companion_bind=127.0.0.1` and `companion_password=foo`:
  - The server is in `Listening` on `127.0.0.1:28080`. `nc 192.168.x.x 28080` (LAN IP) is refused; only loopback reaches the listener.
  - The auth flow runs as in the previous case.
- With `fallout.cfg` missing or unreadable:
  - The server is in `disabled`. The main menu shows the hint. The game still runs.
  - The `companion: disabled (fallout.cfg missing or unreadable)` log line is emitted at init.
- Constant-time compare: a length-mismatched candidate and a same-length wrong candidate touch every byte of the configured password. Verified by `valgrind --tool=callgrind` or an equivalent micro-benchmark.
- `world.schemaVersion` is `2`. The rest of `world` is byte-identical to step 1.
- A step-1 client (which does not know `auth`) is always dropped at the first message. The log line is the `non-auth first message` shape.
- T7's announce broadcast reports `authRequired: true` and the configured `host`, and never includes the password.

**Notes:**

- The password is the only secret. Constant-time compare is mandatory. The plaintext-on-disk threat model is unchanged: LAN-local only.
- Empty-string password is a valid configuration. Do not second-guess the user. The compare logic still touches the full configured length.
- Mode is decided once at init. A `fallout.cfg` change mid-run is not picked up. Document this in the init log line so a user who edits the file knows a restart is required.
- Do not invent new abstractions around the config subsystem. The existing `config_get_string` is the read; the new `GAME_CONFIG_COMPANION_*` macros are the key names. That's the entire config integration.
- The main-menu hint is the only UI change. It has no click target, no input handler, no settings screen. It is drawn once and forgotten.
- The disabled state is not a fallback. It is the default. The main-menu hint exists specifically so the user knows the server is off and how to turn it on.
- The bind host accepts whatever `inet_pton(AF_INET, ...)` accepts. A non-IPv4 bind value (e.g., `::1`, a hostname) is a config error: `inet_pton` returns 0 and the server logs `disabled (bind parse failed: <value>)`. This is an explicit failure mode; do not silently fall back to `0.0.0.0`.

---

### T2 — Real Player-Availability Signal

**Status:** done (revised)

**Implementation notes:**

- New files `src/companion_player_state.{h,cc}` with a single internal helper `bool companionIsPlayerReallyPlaying()`. `companionCollectSnapshot` now gates `hasPlayer` on this helper instead of `obj_dude != nullptr`.
- The helper uses five short-circuit checks:
  1. `obj_dude == nullptr` (covers game start, after `game_exit`).
  2. `in_main_menu` (covers the main menu loop).
  3. `moviePlaying()` from `int/movie.h` (covers MVE playback: IPLOGO, INTRO, OVRINTRO, the death scene, and the MVE-rendered sub-variants of `gmovie_play`).
  4. `map_data.name[0] == '\0' && !worldMapIsActive()` (covers "no real map is currently loaded" but accepts the world map as gameplay, because `map_save_in_game(true)` clears the name at world-map entry; `worldMapIsActive()` exposes `wwin_flag` from `game/worldmap.cc`, which is true for the entire duration of a `world_map()` invocation).
  5. `(obj_dude->flags & OBJECT_HIDDEN) != 0` (covers the post-`main_unload_new` state, including "player returned to the main menu from a previous game and then started a new game and is now in character creation", where `map_data.name` still holds the previous map's name).
- The original revision treated the world map as "not real gameplay" because `map_save_in_game(true)` clears `map_data.name[0]`. That diagnosis was wrong: `obj_dude` carries `OBJECT_NO_REMOVE` (`src/game/object.cc:334`), so `obj_remove_all()` (called from `map_save_in_game(true)` at `src/game/map.cc:1500`) does not touch the player. HP, max HP, inventory, and party state are all real on the world map, and reporting them as zero was a lie. The revised check uses `worldMapIsActive()` to disambiguate the world map from the other "no real map" states (cold startup, MVE playback, post-`main_unload_new`, character creation), none of which ever have the world map window up.
- One new public function on the world map module: `bool worldMapIsActive()` in `src/game/worldmap.h`, implemented in `src/game/worldmap.cc` as `return wwin_flag != 0;`. `wwin_flag` is a `static unsigned char` in `worldmap.cc` set to 1 by `InitWorldMapData` (`worldmap.cc:2706`, also set by the town map picker at `worldmap.cc:3295`) and cleared by `KillWorldWin` (`worldmap.cc:3500`). The flag is true for the entire duration of a `world_map()` invocation, including the brief periods the town map picker is shown. Both callers (`scripts.cc:789,798` and `map.cc:1268,1277`) call `world_map` synchronously and `KillWorldWin` immediately after, so the flag tracks "is the world map function on the call stack" with no false positives.
- The transition from "real map" to "world map" still has a brief flicker: `map_save_in_game(true)` clears the map name before `InitWorldMapData` sets `wwin_flag`. The companion server samples every 500 ms, so a 500 ms sample landing in that window will report `hasPlayer: false` once. This is a pre-existing limitation; the change does not make it worse.
- No new engine files were touched. `in_main_menu` is read from `game/mainmenu.h`, `moviePlaying()` from `int/movie.h`, `map_data` from `game/map.h` (already an `extern`), `OBJECT_HIDDEN` from `game/object_types.h`, `obj_dude` from `game/object.h`, and `worldMapIsActive()` from `game/worldmap.h` (the only new include in the helper). The localized diff rule is preserved.
- The step-1 contract "`playerAvailable` reflects the game state at the moment the message is built" is preserved: every `world`, `snapshot`, `update`, and `player_unavailable` message already derives `playerAvailable` from the snapshot's `hasPlayer`, and `hasPlayer` is now the helper's output.

**Audit: engine-signal investigation for the player-availability contract.**

The T2 contract is "`hasPlayer` is true only when all of: `obj_dude != nullptr`, real map loaded OR world map active, not main menu/intro, no fullscreen movie, player not torn down." This is the disambiguation table that justifies the five checks above. For each state the ticket lists, the table records which check (or which pair of checks) is responsible for reporting `hasPlayer = false`.

| State                       | obj_dude | in_main_menu | moviePlaying | map_data.name[0] | worldMapIsActive | OBJECT_HIDDEN | hasPlayer |
|-----------------------------|----------|--------------|--------------|------------------|------------------|---------------|-----------|
| Game start (cold)           | NULL     | false        | false        | '\0'             | false            | n/a           | false     |
| IPLOGO + INTRO (game start) | non-null | false        | **true**     | '\0'             | false            | set           | false     |
| Main menu (no prior game)   | non-null | **true**     | false        | '\0'             | false            | set           | false     |
| Main menu (after gameplay)  | non-null | **true**     | false        | set              | false            | **set**       | false     |
| Character creation (fresh)  | non-null | false        | false        | '\0'             | false            | set           | false     |
| Character creation (after prior game) | non-null | false | false | set (from prior map) | false | **set** | false |
| OVRINTRO                    | non-null | false        | **true**     | '\0'             | false            | set           | false     |
| World map                   | non-null | false        | false        | **'\0'** (cleared by `map_save_in_game(true)`) | **true** | clear         | **true**  |
| World map → town map picker (transient) | non-null | false | false | '\0' (still cleared) | **true** | clear | **true** |
| Real in-map gameplay        | non-null | false        | false        | set              | false            | clear         | **true**  |
| In-game menu (dialog, pip-boy, barter, save, options, etc.) | non-null | false | false | set | false | clear | true |
| Save/load screen            | non-null | false        | false        | set (loading) or '\0' (briefly) | false | clear | true (no menu mask) |
| Death scene (movie)         | non-null | false        | **true**     | set              | false            | clear         | false     |
| Between death and main menu | non-null | false        | false        | set (from last map) | false | **set** (after `main_unload_new`) | false |
| After game quit (`game_exit`) | NULL   | n/a          | n/a          | n/a              | n/a              | n/a           | false     |

Notes on the table:

- `map_data.field_34` is **not** a reliable "no map" signal. The struct is BSS-initialized to 0, which happens to be `MAP_DESERT1`. The world map does not change `field_34` either; it only changes `map_data.name[0]`. This is why the step-1 plan's "`map_get_index_number() != -1`" suggestion is insufficient on its own — the world map keeps `field_34` at the last real map's index.
- The world-map detection signal is `worldMapIsActive()` (the new helper backed by `wwin_flag`), not `map_data.name[0]` alone. `wwin_flag` is set to 1 by `InitWorldMapData` (`src/game/worldmap.cc:2706`) when the world map window is created, and cleared by `KillWorldWin` (`worldmap.cc:3500`) which the caller invokes immediately after `world_map()` returns (`scripts.cc:789-790,798-799` and `map.cc:1268-1270,1277-1279`). The flag tracks "is the world map function on the call stack" with no false positives.
- `map_save_in_game(true)` (called by `world_map` at entry, `src/game/worldmap.cc:999`) clears `map_data.name[0]` but does not touch `field_34`. The world-map exits via `LoadTownMap` (`worldmap.cc:2523`) which calls `map_load` and re-sets the name.
- The "world map → town map picker" row covers the brief moments inside the world map when the small in-world-map city picker is shown (`town_map` at `src/game/worldmap.cc:3098`). The world map window is still up (`wwin_flag == 1`), so the helper correctly returns `hasPlayer: true`. The player is interacting with the game (picking an entrance), so this is the right call.
- The `OBJECT_HIDDEN` check is the one that disambiguates "real map is still named but the player is not playing." It is set by `obj_turn_off` (`src/game/object.cc:1840`), which `main_unload_new` (`src/game/main.cc:316`) calls when leaving real gameplay. It is cleared by `obj_turn_on` (`src/game/object.cc:1809`), which `main_load_new` (`src/game/main.cc:274`) calls when starting real gameplay. The object is created with `OBJECT_HIDDEN` set in `obj_new`/`obj_init` (`object.cc:332-340`), so a fresh game also starts hidden.
- The save/load screen row reflects the design choice that pause screens (save, load, dialog, pip-boy, barter, character sheet, options) do not mask `hasPlayer`. The underlying map is loaded the whole time. The world map is now in the same category: it is a real-gameplay surface with real player data, and the helper returns `true` for it.
- The "in-game menu" row covers dialog, pip-boy, barter, character sheet, options, save, and the other in-game UI surfaces. None of them set `OBJECT_HIDDEN`, clear the map name, or start a movie. They are all "player is in a real map, looking at a UI."

**Acceptance verification (static, from the table):**

- Main menu: `in_main_menu` is `true` → `hasPlayer = false`. ✓
- Intro movie: `moviePlaying()` is `true` → `hasPlayer = false`. ✓
- World map: `map_data.name[0] == '\0'` and `worldMapIsActive()` is `true` → the combined check does not return false → `hasPlayer = true`. ✓
- World map → town map picker (transient): same as world map, `worldMapIsActive()` is `true` → `hasPlayer = true`. ✓
- Character creation: `OBJECT_HIDDEN` is `set` (from prior `main_unload_new` or from initial `obj_new`) → `hasPlayer = false`. ✓
- Save/load: name is set (during load the name is briefly empty but the helper's first three checks already return false during the load movie/menu flow, and the client sees a transition through `player_unavailable` if the load fails). ✓
- Real in-map gameplay: all five checks pass → `hasPlayer = true`. ✓
- Absent → present transition: `hasPlayer` flips to `true`, no `player_available` event. The next sample sees the change in `hp`/`maxHp` and emits a normal `update`. Per `companion_server.cc:269-287` (`queuePlayerUpdateIfNeeded`) and the absent→present path in `sampleReadyClient` (`companion_server.cc:439-464`). ✓
- Present → absent transition (death): `hasPlayer` flips to `false`, the server emits exactly one `player_unavailable`. Per `companion_server.cc:260-267` and `sampleReadyClient`. ✓
- Cost: the helper is five O(1) checks (pointer compare, bool read, function call returning a global int, byte compare + bool function call, bitwise AND). No allocation, no scan, no global lock. ✓

**Verification status:**

- Build passes (`cmake --build build --target fallout-ce`).
- The unit-test surface in `/tmp/opencode/protocol_test.cc` does not cover the new helper, because the helper reads engine globals and is not linkable into a host-only test binary. A runtime check requires the game data files (`master.dat`), which are not present in this workspace. The acceptance table above is the substitute for the runtime check.
- The next QA pass should run the game with `companion_server` enabled and a `nc` client connected, and walk through each row of the table while observing the wire. Recommended manual cases: fresh game start, load a saved game, walk off a map edge to the world map, walk across the world map, click a city and pick an entrance from the town map picker, enter a city from the world map, die in combat, and start a new game after a previous game session.

**Goal:** `hasPlayer` (and therefore `playerAvailable`) is `true` only when the engine is in real gameplay: a real map is loaded, the world map is the active surface, the main menu / intro state is false, the player is not torn down, and no fullscreen movie is playing. The placeholder 30/30 HP that step 1 reports from the main menu / intro must not be exposed. The world map is real gameplay; HP, max HP, and inventory are real and are reported.

**Scope:**
- Investigate and document in `docs/audits/companion-server-step-2.md` (or a focused subsection in the tickets file) the engine signals that distinguish:
  - Main menu
  - Intro movie
  - Character creation
  - World map
  - Real in-map gameplay
  - Save-game loading screen
  - Death / game-over screen
- Candidate signals to evaluate (verify which exist):
  - `map_get_index_number() != -1`
  - An `in_main_menu` or equivalent global (search `src/game/`, `src/platform_compat/`)
  - The current script number / `gsn_*` state
  - A "movie playing" flag (search the movie subsystem)
  - The world-map engine state (search for the world-map entry points)
- Add a new internal helper, e.g. `bool companionIsPlayerReallyPlaying()`, in `src/companion_snapshot.cc` (or a small new file `src/companion_player_state.{h,cc}` if the logic grows).
- `companionCollectSnapshot` uses the new helper to set `hasPlayer`.
- `world.playerAvailable`, `snapshot.playerAvailable`, and `update.playerAvailable` are derived from the new helper. The step-1 contract "reflects the game state at the moment the message is built" is preserved.
- Re-verify the T7 step-1 manual validation cases (main menu, intro, world map, real play) against the new helper. Add the verification log to this ticket.
- Expose a small public predicate on the world map module, `bool worldMapIsActive()`, so the helper can distinguish "no real map loaded and the world map is up" from "no real map loaded and we're in a non-gameplay state (cold startup, MVE playback, post-`main_unload_new`, character creation)." The predicate is backed by `wwin_flag` in `worldmap.cc` and is true for the entire duration of a `world_map()` invocation.
- T3 (position and map) is the next consumer of `worldMapIsActive()`. T3 will need to decide whether to keep the existing `x, y, map` fields and emit sentinels on the world map, or to add world-map position fields. That work is **out of scope for this ticket**.

**Acceptance:**
- At the main menu, `playerAvailable` is `false` for any `world`, `snapshot`, or `update` the server would send.
- During the intro movie, `playerAvailable` is `false`.
- On the world map, `playerAvailable` is `true`.
- During the in-world-map town map picker, `playerAvailable` is `true`.
- During character creation, `playerAvailable` is `false` (placeholder HP is being set but the player is not "playing").
- During a save/load screen, `playerAvailable` matches the underlying real-map state, not the screen state.
- During real in-game gameplay, `playerAvailable` is `true`.
- The transition from "absent" to "present" still produces a normal `update` (no `player_available` event), per the step-1 contract.
- The step-1 test for "player death → exactly one `player_unavailable`" still passes with the new helper as the source of truth.

**Notes:**
- This ticket is a correctness fix, not a feature. It closes a bug that step 1 shipped knowingly.
- The placeholder-HP issue is documented in the step-1 plan at lines 468–483. Read that section first.
- "Real" gameplay is a contract decision, not just a code change. If the engine signals do not cleanly disambiguate every case, document the residual ambiguity in the audit and pick a defensible default rather than ship a half-fix.
- The new helper must be cheap. It is called every 500 ms. No allocation, no scan, no global lock.

---

### T3 — Position and Map Updates

**Status:** pending

**Goal:** Expose the player's current tile position and current map to the companion client. `snapshot` and `update` carry the new fields. The existing HP behavior is preserved.

**Scope:**
- Investigate and document the engine's source of truth for:
  - Player tile coordinates (`x`, `y` on the current map)
  - Player elevation (decide: include or defer; default is **defer** unless the engine exposes it as a free read)
  - Current map identifier (`map_get_index_number()` is the working assumption; verify)
- Extend `CompanionPlayerSnapshot` in `src/companion_snapshot.h`:
  - Add `int x;` `int y;` `int map;` (or `int elevation;` if decided).
  - Document the units (tile coordinates on the current map) in a comment on the struct.
- Extend `companionCollectSnapshot` in `src/companion_snapshot.cc` to populate the new fields. If the field is unreadable, leave it at a documented sentinel (`-1` for `map`, `-1` for `x`/`y`) and set `hasPlayer` accordingly. T2's `hasPlayer` is the single source of truth for "do these values mean anything."
- Extend `companion_protocol`:
  - `snapshot` builder includes `x`, `y`, `map` in `data.player` whenever they are valid.
  - `update` builder for the `player` entity emits a per-field diff for `x`, `y`, `map` in addition to the existing `hp` and `maxHp`. The `data` payload is the union of changed fields.
- Per-field change detection in `src/companion_server.cc`:
  - `last_sent_x`, `last_sent_y`, `last_sent_map` caches. Reset on disconnect.
  - Each is compared against the new sample. Any difference emits an `update` for that field. Multiple differences in one interval collapse into a single `update`.
- Logging: the existing `update sent` log is sufficient. No new log lines for position.

**Acceptance:**
- With a step-2 server in `awaiting_hello` mode (no password set), `nc 127.0.0.1 28080` → `hello` → `get_snapshot` returns a `snapshot` whose `data.player` includes `x`, `y`, `map` in addition to `hp` and `maxHp`. With a server in `awaiting_auth` mode (password set), the handshake is `auth` → `hello` → `get_snapshot` and the same `snapshot` shape is returned.
- Moving the player one tile in-game produces an `update` within 500 ms whose `data` contains only the changed `x` (or `y`), not `hp` or `maxHp`.
- Changing the map (walking to a new map edge) produces an `update` whose `data` contains `map` and possibly `x`/`y` if they changed at the same time.
- After T2 is in place, `playerAvailable` is `false` on the world map, and therefore `x`, `y`, `map` are not present (or are sent as sentinels) in any `update` the server emits while on the world map. The companion client keys off `playerAvailable` and does not need to handle a separate "position is invalid" signal.

**Notes:**
- Elevation is the obvious next ask. Defer it to a later milestone unless it is a free read at the same call site.
- Map name is a different ask than map number. Defer; expose the index only.
- Do not invent a "tile format" the engine does not use. Whatever the engine stores is what the wire carries.

---

### T4 — Inventory Snapshots

**Status:** pending

**Goal:** Expose the player's inventory to the companion client as a flat array. `snapshot` carries the full inventory; `update` for the `inventory` entity carries the per-interval diff.

**Scope:**
- Investigate and document the engine's inventory APIs:
  - The iterator over `obj_dude`'s inventory items
  - The accessors for item id, count, and equipped state
  - Whether the iterator order is stable across calls (T5 depends on this)
  - Whether the engine has a concept of "slot" (head, torso, weapon, etc.) and whether it can be queried cheaply
- Extend the snapshot model in `src/companion_snapshot.{h,cc}`:
  - New struct `CompanionInventoryItem { int id; int count; bool equipped; }`.
  - New struct `CompanionInventorySnapshot { std::vector<CompanionInventoryItem> items; }` (or a fixed-size buffer if the inventory size is known and small; verify).
  - Extend `CompanionSnapshot` to include the inventory, gated by the T2 `hasPlayer` signal.
- Extend `companion_protocol`:
  - `snapshot.data.inventory` is a JSON array of `{id, count, equipped}`.
  - `update` for `entity: "inventory"` carries the per-interval diff. Shape is the same array; semantics are "items present in the new sample that were not in the last sent sample are added; items present in the last sent sample that are not in the new sample are removed; items with changed count or equipped state are updated."
- Per-interval diff logic in `src/companion_server.cc`:
  - `last_sent_inventory` cache. Reset on disconnect.
  - Compute the diff against the current sample. Emit one `update` only if the diff is non-empty.
- Buffer and allocation review:
  - Inventory serialization is the highest-allocation path in the milestone. Reuse the step-1 outbound buffer strategy. If the inventory is too large for a single tick, the protocol must split, but the initial model should keep it small enough that one message per tick is enough.
  - If the engine inventory can grow unbounded, T4 must include a documented upper bound on the array size and the client behavior on overflow.

**Acceptance:**
- `snapshot.data.inventory` is a non-empty array during real gameplay. Empty array (not absent) when the player has no items.
- Picking up an item produces an `update` within 500 ms with `entity: "inventory"` and the new item in `data`.
- Dropping an item produces an `update` removing it.
- Equipping or unequipping an item produces an `update` with the changed `equipped` flag.
- Stacking or unstacking items produces an `update` with the new `count`.
- No `update` is emitted for the inventory when nothing changed across an interval.
- A step-1 client that ignores `data.inventory` continues to work. Its `data.player` parsing is unaffected.

**Notes:**
- T4 is a snapshot ticket, T5 is the events ticket. The split exists so T4 can land and be validated before the harder diff work in T5.
- "Equipped" may not be a single boolean in the engine. Verify the actual data model and pick the closest match. Do not invent slot semantics.
- The inventory is a vector of items; the diff between two vectors is straightforward but easy to get subtly wrong. Use unordered maps keyed by `id` for the comparison. Do not rely on iterator order matching across calls.

---

### T5 — Derived Inventory Events

**Status:** pending

**Goal:** When the inventory changes between samples, the `update` for the `inventory` entity communicates the specific transition (added, removed, equipped, unequipped) per item, not just the post-state diff.

**Scope:**
- This ticket refines the `update` shape introduced in T4. The trigger is "something changed"; the refinement is "here is exactly what changed and how."
- For each item whose state changed between the last sent sample and the current sample, derive a transition:
  - Present in old, absent in new → `removed`.
  - Absent in old, present in new → `added`.
  - Present in both, count changed → `count_changed`.
  - Present in both, `equipped` changed → `equipped_changed` or `unequipped_changed`.
  - Any other change → `updated` (fallback).
- Extend `companion_protocol`:
  - `update` for `entity: "inventory"` carries an array of `{id, transition, count?, equipped?}` items instead of the raw diff array. Each entry includes only the fields relevant to the transition.
- This ticket depends on the iterator-order stability finding from T4's investigation. If the engine's iterator is unstable, T5 falls back to the raw post-state diff and the ticket is marked partial with a written explanation in the audit.
- Logging: no new log lines. The existing `update sent` log is sufficient.

**Acceptance:**
- A pickup emits one `update` with one entry whose `transition` is `added` and whose `count` is the picked-up count.
- A drop emits one `update` with one entry whose `transition` is `removed`.
- Equipping an item the player already has emits one `update` with one entry whose `transition` is `equipped_changed` and whose `equipped` is `true`.
- A stack change (e.g., 30 stimpaks → 60 stimpaks from a restock) emits one `update` with one entry whose `transition` is `count_changed` and whose `count` is the new count.
- Two simultaneous changes in the same interval (e.g., drop one item, equip another) produce a single `update` with two entries.
- The acceptance list for T4 continues to pass: the data is more specific but not less correct.

**Notes:**
- The transition taxonomy is a protocol decision. If a future change does not fit, the fallback `updated` exists. Do not invent a long tail of transition types speculatively.
- A step-1-style client that ignored `transition` and just read `id` + `count` + `equipped` from each entry would still work. The shape is additive.

---

### T6 — Incoming Client Commands

**Status:** pending

**Goal:** Add a small, explicit, allowlisted command channel from the client to the server. The initial allowlist is `ping` and `get_snapshot`. The server replies with a `cmd_ack` carrying the same `id` as the request, proving request/response pairing works. No engine mutation.

**Scope:**
- New protocol messages in `companion_protocol`:
  - Client: `{"type":"cmd","id":<int>,"name":"<string>","args":{<object>}}`. The `args` object is optional and may be empty.
  - Server: `{"type":"cmd_ack","id":<int>,"ok":<bool>,"error":"<string>"?,"data":{<object>}?}`.
- Command registry in `src/companion_server.cc` (or a new small file `src/companion_commands.{h,cc}` if the surface grows):
  - A static table of `{name, handler}` pairs. The initial table has exactly two entries: `ping` and `get_snapshot`.
  - `ping` handler: no args, `ok=true`, no data. The simplest possible command; it exists to validate the channel.
  - `get_snapshot` handler: no args, `ok=true`, `data` is the most recent `CompanionSnapshot` serialized in the same shape as the step-1 `snapshot` message's `data` field. The handler **also** enqueues a normal `snapshot` message so the client sees both the ack and the data on the wire. (The contract is fixed: ack and snapshot are sent for this command.)
- Server state machine:
  - Commands are accepted only in the `ready` state. A `cmd` arriving in `awaiting_auth` or `awaiting_hello` drops the client.
  - Unknown command name → `cmd_ack` with `ok=false`, `error="unknown_command"`. Client stays connected.
  - Malformed `cmd` (missing `id`, missing `name`, non-integer `id`) drops the client.
  - The `id` is a 32-bit integer. Duplicates and out-of-order ids are accepted; pairing is purely by `id` echo.
- Logging:
  - Log `cmd accepted` with command name and id.
  - Log `cmd rejected` with command name, id, and error.

**Acceptance:**
- A `{"type":"cmd","id":1,"name":"ping","args":{}}` produces exactly one `{"type":"cmd_ack","id":1,"ok":true}`.
- A `{"type":"cmd","id":2,"name":"get_snapshot","args":{}}` produces a `cmd_ack` with `id=2`, `ok=true`, followed by a `snapshot` message whose `data` matches a direct `get_snapshot` request.
- A `{"type":"cmd","id":3,"name":"unknown","args":{}}` produces a `cmd_ack` with `id=3`, `ok=false`, `error="unknown_command"`. The client is **not** dropped.
- A `{"type":"cmd","id":"not_a_number","name":"ping","args":{}}` drops the client. The game keeps running.
- A `{"type":"cmd","id":4,"name":"ping","args":{}}` arriving in `awaiting_auth` or `awaiting_hello` drops the client.

**Notes:**
- T6 is the smallest possible command channel. It is the architectural primitive, not a feature surface. Future commands (e.g., `set_volume`, `screenshot`) belong to a later milestone and require their own design discussions.
- The `get_snapshot` command deliberately duplicates the step-1 client message. The duplication is the point: it proves the command channel can produce the same observable result as the dedicated message, and lets a future step retire the dedicated message without breaking the ack contract.
- The command channel is the only piece of milestone 2 that allows the client to trigger engine behavior. The `ping` and `get_snapshot` handlers trigger no engine behavior at all. This is intentional; the channel's safety story is "the initial allowlist triggers nothing."

---

### T7 — UDP Discovery Broadcast

**Status:** pending

**Goal:** The server periodically broadcasts a small JSON announce packet over UDP so a companion client on the same LAN can find it. The packet tells the client whether auth is required. The password is **never** broadcast.

**Scope:**
- New code path in `src/companion_server.cc`:
  - Create a UDP socket in `companionServerInit`, set `SO_BROADCAST`, bind to an ephemeral port. On any failure, log and continue with the discovery socket in a `disabled` state — TCP behavior is unaffected.
  - In `companionServerTick`, when the server is `listening` (no client currently connected), broadcast the announce packet to `255.255.255.255:28080` at most once per second. Stop broadcasting while a client is connected.
  - Close the UDP socket in `companionServerExit`.
- `companion_protocol` adds a new builder for the announce payload:
  - `{"type":"announce","game":"fallout1-ce","schemaVersion":2,"host":"<bind host>","port":28080,"authRequired":true}\n`
  - `host` is the value of `companion_bind` from `fallout.cfg` (e.g., `0.0.0.0`, `127.0.0.1`, a LAN address). The client uses this to know which interface to connect to.
  - `authRequired` is unconditionally `true`. The server is enabled only with a password, so the auth path is always on.
  - No password field, ever. Clients must obtain the password through a separate channel (today: read it from the host's `fallout.cfg`).
- The broadcast is fire-and-forget. No receive loop, no per-client buffer, no error recovery beyond "log and disable the UDP socket."
- The broadcast is rate-limited at the source: one packet per second while idle. The `companionServerTick` is the natural place to do this without a timer thread.
- Logging: one log line when the discovery socket is created, one when it is closed. No per-packet log.

**Acceptance:**
- `nc -u -l 28080` on the same machine as the game receives the announce packet within 1 second of game launch (with no client connected).
- The announce packet is a single line of valid JSON matching the schema above.
- `authRequired` is `true` whenever the server is in `Listening`. The server is never in `Listening` without a configured password, so the field is effectively unconditional. The packet is not sent when the server is in `disabled`.
- The packet does not contain a password field. (Verified by grep.)
- When a TCP client connects, the announce broadcast stops. When the client disconnects, the broadcast resumes within 1 second.
- The discovery socket can be disabled (by, e.g., a `SO_BROADCAST` permission failure) without affecting the TCP server. The game still starts and runs.
- `nc -u -l 28080` on a different host on the same LAN receives the announce.

**Notes:**
- This is the only piece of milestone 2 that adds a new transport. The justification is that the bind host is now user-configured, which makes the server harder to find from a LAN peer without discovery; the announce lets a client learn the host, port, and auth requirement without trial-and-error.
- No client→server UDP. UDP is one-way.
- The broadcast address (`255.255.255.255`) and port (`28080`) are hardcoded. Multicast is out of scope. A future step can add a configurable discovery port if needed.
- The `host` field in the announce is the bind host, not the resolved client-visible address. A client receiving the announce on a multi-homed host still does not know which interface to use; that is a client problem, not a server one.
- A client that connects in the wrong mode (e.g., sends `hello` first when the server is in `awaiting_auth`) is dropped per T1's contract. The client should use the announce to pick the right mode.

---

## Suggested Ordering

T0 → T1 → T2 → T3 → T4 → T5 → T6 → T7. T0 must land first: it sets the protocol shape that T3, T4, and T5 build on. T1 and T2 are independent and can be implemented in either order after T0; T1 is recommended first because it closes the LAN-by-default footgun and gives the user a working security knob early. T3 depends on T2 (T2's `hasPlayer` is the gate for emitting position). T4 depends on T2 for the same reason. T5 depends on T4. T6 and T7 are independent of T3–T5 and of each other; they can land in any order after T1, but T6 is recommended before T7 because it exercises the protocol surface more and may surface parsing edge cases that T7 inherits.

T0 and T1 are protocol changes. T0's bump is `2 → 3`, unconditional, and supersedes T1's `1 → 2` bump (the authoritative value is now 3). T6 is additive (a step-1 client that ignores `cmd` and `cmd_ack` is unaffected), so no bump is required for T6; the bump already happened in T0.

## Rejection Heuristics For Future Proposals

Push back on any of:
- "Add an env var or runtime override for `companion_bind` / `companion_password`." The config file is the only knob in this milestone. The threat model and the user mental model both assume `fallout.cfg` is the single source of truth.
- "Add password hashing, salting, or external credential storage." Plaintext in `fallout.cfg` is the contract. The threat model is LAN-local.
- "Use `nss`, `openssl`, or any crypto library" for password comparison. A hand-rolled constant-time compare is sufficient.
- "Make the bind host or password optional / opt-in." Both are required in this milestone. The disabled state is the only escape hatch and it is the default.
- "Make the inventory model hierarchical" (containers, slot types, etc.). The flat array is the contract.
- "Add events for HP, position, or map" as a separate event channel. Sampling with change detection is the channel.
- "Allow the client to send arbitrary engine commands" without a per-command design discussion. Each new command is its own ticket.
- "Make the UDP announce include the password" or "include a nonce for replay protection." The password is secret; the announce is public.
- "Add a websocket or HTTP fallback for the discovery broadcast." The announce is a UDP packet, not an API.
- "Bump `schemaVersion` for T6." T6 is additive; the bump already happened in T1.
- "Implement the Windows socket path in this milestone." POSIX only; Windows is still empty stubs.
- "Revert the T0 protocol redesign" (drop `kind`, re-add `entity`, rename `payload` back to `data`, fold the per-kind builders back into a monolithic `companionBuildPlayerUpdate`). T0 is the architectural decision this milestone is built on; reverting it forces T3–T5 to land into a worse dispatch model.
- "Add a second discriminator on top of `kind`" (e.g., `subtype`, `domain`, or `aspect`). One tag is enough. Adding more creates the same implicit-dispatch problem T0 was designed to fix.
- "Flatten `payload` and merge it with the message envelope" (e.g., put `hp` and `seq` and `type` at the same level). The `payload` wrapper is the boundary between protocol-level fields (`type`, `seq`, `kind`, `playerAvailable`) and per-kind data. Removing the boundary makes dispatch harder, not easier.
- "Skip T0 because step-1 clients are gone." T0 is what makes the protocol evolvable; landing T3, T4, or T5 first would force a redo of T0 after more code is in place.
