# Companion App — MVP Milestone Plan

Reference: [`concept.md`](concept.md).

## MVP Definition

The companion app MVP is a standalone Python + pygame application
that:

- Renders only the contents of the (future) Pip-Boy device screen.
  No bezel, no case chrome, no clock/date/water-chip strip — those
  are physical-device concerns.
- Runs at a virtual resolution of **480×800 portrait** (7" Pi-class
  panel rotated), scaled to the desktop window during development.
- Uses the Fallout webfont for all text in a monochrome green
  palette.
- Connects to the in-game companion server over TCP (newline JSON,
  step-1 handshake) and stays connected with automatic reconnect.
- Draws a fixed **top header line** in every section: active
  section name on the left, connection-status indicator on the
  right (`OK`, `NO SIGNAL`, `RECONNECTING`).
- Exposes four top-level sections via four hardware-style section
  buttons:
  1. **STATUS** — live HP / max HP from the server.
  2. **DATA** — sub-tabs Quests / Holodisks, both shipped as
     placeholders ("NOT YET IMPLEMENTED") in the MVP because the
     server does not expose this data yet.
  3. **INVENTORY** — placeholder.
  4. **MAP** — placeholder.
- Supports the full hardware-style input vocabulary
  (`SectionButton(1..4)`, `EncoderLeft`, `EncoderRight`, `Confirm`,
  `Back`) via keyboard emulation in dev.
- Handles the connection lifecycle gracefully:
  `CONNECTING`, `OK`, `RECONNECTING`, and `NO SIGNAL` (when
  `playerAvailable` is false). All states are signalled via the top
  header and the section body.
- Reads its server host/port and display settings from a
  configuration file.

The MVP is **shippable against the unmodified step-1 server**.
Anything that would require server changes (quests, holodisks,
inventory, map) is rendered as a placeholder.

Out of MVP: bezel/chrome rendering, idle screensaver, audio, real
hardware integration, any game-control commands, authentication
beyond what step 1 needs.

---

## Milestone Layout

Five milestones. Each is independently testable. They are ordered so
each one produces a runnable artifact and unblocks the next.

- **M1** — App skeleton & input abstraction
- **M2** — Rendering primitives & screen shell (header + body)
- **M3** — Network client & state cache
- **M4** — STATUS section (first live section)
- **M5** — Section navigation shell & placeholder sections

After M5 the MVP is complete.

---

## M1 — App skeleton & input abstraction

### Goal

A pygame application starts, opens a window at a fixed virtual
resolution, runs a deterministic main loop, and converts keyboard
input into the hardware-style input event vocabulary. No networking,
no real UI.

### Scope

- Project skeleton (Python package layout, `pyproject.toml` or
  equivalent, dev requirements).
- pygame main loop at a fixed frame rate.
- Window opens at the virtual resolution **480×800 portrait**
  (scaled to a desktop window for development).
- `input/` module that emits exactly these events:
  - `SectionButton(n)` where `n ∈ {1,2,3,4}`
  - `EncoderLeft`, `EncoderRight`
  - `Confirm`, `Back`
- Dev keymap (configurable):
  - `1` `2` `3` `4` → section buttons 1..4
  - `Up` / `Down` → encoder left / right
  - `Enter` → confirm
  - `Backspace` → back
  - `Esc` or `q` → quit app (dev only)
- A debug screen that visibly logs the last 10 input events. Used
  only to verify M1 manually; removed or hidden in later milestones.
- Configuration loader (file path resolution, JSON parsing, defaults).

### Out of scope

- Any networking.
- Any chrome rendering, real font, or palette.
- Section navigation logic.

### Success criteria

- Running the app opens a window of the configured virtual size.
- Pressing any mapped key produces exactly one input event of the
  correct type, visible in the debug screen.
- Holding a key does not spam events (key repeat is filtered or
  surfaced as repeated single events — pick one and document it).
- The app exits cleanly on quit; no zombie pygame state.
- Configuration values can be overridden by an explicit config file.

### Dependencies

None.

---

## M2 — Rendering primitives & screen shell

### Goal

The app renders a monochrome-green CRT screen surface at 480×800
portrait using the Fallout webfont. A shared screen shell — top
header line (active section name + connection status) and a body
area — is in place with static placeholder values. No bezel, no
chrome.

### Scope

- Asset pipeline for `jh_fallout-webfont.woff` (vendored under
  `assets/`, loaded via pygame freetype). Verify glyph coverage for
  ASCII + digits + the punctuation the MVP uses. If `.woff` does
  not load cleanly, document the conversion to `.ttf`/`.otf` and
  ship the converted file.
- `render/` module with:
  - Palette (foreground, dim, background).
  - Screen background fill.
  - Text helpers (left-aligned, right-aligned, centered, with
    underline / strike-through hooks for later sections).
  - Optional CRT scanline overlay, toggled by config.
- `ui/shell.py` (or equivalent):
  - Top header line: section name on the left (static `STATUS` for
    M2), connection status on the right (static `--` for M2).
  - Body rect: everything below the header line. Renders a centered
    `PIPBOY 2000` placeholder.
  - Separator rule between header and body if useful.
- Virtual-resolution-to-window scaling.

### Out of scope

- Live data of any kind.
- Section-specific content.
- Network or connection-state integration.
- Input-driven section switching.

### Success criteria

- App boots into a single static screen at 480×800 virtual
  resolution, showing the header (`STATUS  --`) and body
  (`PIPBOY 2000`) on a green CRT background.
- Font renders correctly for the printable ASCII range used by the
  MVP.
- Window scaling preserves aspect ratio without distortion at at
  least two scale factors.
- CRT overlay toggles on/off via config without visual artifacts.
- No bezel, frame, or case decoration is drawn anywhere.

### Dependencies

- M1 (app skeleton, config loader).

---

## M3 — Network client & state cache

### Goal

The app connects to the companion server, completes the handshake,
ingests one full snapshot, applies `update` messages, and
auto-reconnects on disconnect. State is cached in memory and
exposed to the UI layer. The UI shows connection status but no
section data yet.

### Scope

- `net/` module:
  - Non-blocking TCP socket, polled once per frame.
  - Newline-delimited JSON framing.
  - Handshake state machine:
    `disconnected` → `connecting` → `awaiting_world` →
    `awaiting_snapshot` → `ready`.
  - Sends `hello`, awaits `world`, sends `get_snapshot`, awaits
    `snapshot`, then transitions to `ready`.
  - Applies inbound `update` messages by entity (player only for
    now; structure must accept new entities without code changes
    in `state/`).
  - Handles `player_unavailable` by clearing player state.
  - Exponential backoff reconnect (capped, configurable, sensible
    defaults).
- `state/` module:
  - Pure data store: `connection`, `world` (`schemaVersion`,
    `game`, `playerAvailable`), `player` (`hp`, `maxHp`).
  - No rendering, no input dependencies.
- UI integration:
  - Header status field reflects the connection state: `CONNECTING`,
    `OK`, or `RECONNECTING`.
  - When not `ready`, the body shows a centered `CONNECTING…`
    placeholder (the section name in the header may stay as the
    last-selected section).

### Out of scope

- Any section UI.
- Decoding fields the server does not yet emit.
- Authentication (step-1 server has none).

### Success criteria

- App connects to a running step-1 server within one second on
  localhost.
- Killing the server is detected within one frame budget after the
  next failed read/write; header flips to `RECONNECTING` and the
  body returns to the `CONNECTING…` panel.
- Restarting the server is detected; the app re-handshakes and
  returns to `CONNECTED` without restart.
- Sending an unexpected protocol message from a test stub (e.g. a
  malformed JSON line) does not crash the app; the client
  disconnects and reconnects per backoff.
- `state/` is observable from the UI layer via a stable read-only
  interface (no networking types leak into `ui/`).

### Dependencies

- M1 (loop, config).
- M2 (so the connection states have somewhere to render).
- Companion server step-1 implementation already exists in this
  repo.

---

## M4 — STATUS section

### Goal

The STATUS section renders live HP / max HP from the server,
handles the `playerAvailable: false` case, and is reachable from
section button 1.

### Scope

- `ui/status.py`:
  - Header: `STATUS` on the left, connection-status on the right.
  - Body: renders `HP: cur / max` when `playerAvailable` is true.
  - Body: renders `NO SIGNAL` when `playerAvailable` is false, and
    the header status field also flips to `NO SIGNAL`.
  - Re-renders on snapshot/update changes.
- Wire `SectionButton(1)` to switch to STATUS.
- STATUS is the default section on first successful connection.
- Pressing `SectionButton(1)` while already in STATUS resets the
  view (no-op visually for MVP since STATUS has no sub-state).

### Out of scope

- Other sections.
- Any data beyond `hp` and `maxHp`.
- Animations / transitions.

### Success criteria

- On a fresh connection with a loaded character, STATUS shows the
  correct HP values within one update cycle.
- HP changes in-game (taking damage, healing) are reflected in the
  STATUS section within the server's update interval plus one
  frame.
- When the engine is at the main menu / pre-character state and the
  server reports `playerAvailable: false`, STATUS shows
  `NO SIGNAL`.
- Disconnecting the server while STATUS is active: header flips to
  `RECONNECTING`, body transitions to the connection-status panel
  from M3.
- Reconnecting: STATUS returns and shows current values.

### Dependencies

- M3 (state, connection lifecycle).
- M2 (chrome).

---

## M5 — Section navigation shell & placeholders

### Goal

All four top-level sections are reachable via section buttons.
DATA, INVENTORY, and MAP render placeholder content. The DATA
section additionally implements the sub-tab UX (Quests / Holodisks)
with placeholder sub-tab bodies. Encoder, Confirm, and Back behave
per the locked design rules in every section.

### Scope

- `ui/data.py`:
  - Root view shows two sub-tab labels: `QUESTS`, `HOLODISKS`.
  - Encoder switches the highlighted sub-tab; Confirm drops into
    the highlighted sub-tab; Back at root is a no-op.
  - Each sub-tab body shows `NOT YET IMPLEMENTED` plus the sub-tab
    name. Back returns to the root.
- `ui/inventory.py`:
  - Single panel: `NOT YET IMPLEMENTED`.
  - All inputs except section buttons are no-ops.
- `ui/map.py`:
  - Single panel: `NOT YET IMPLEMENTED`.
  - All inputs except section buttons are no-ops.
- Section-button routing:
  - `SectionButton(1)` → STATUS
  - `SectionButton(2)` → DATA
  - `SectionButton(3)` → INVENTORY
  - `SectionButton(4)` → MAP
- Section buttons always override the current sub-screen and reset
  the target section to its root view.
- The header line's section-name field updates immediately on
  section switch (this is the only "which section is active"
  indicator in the MVP).

### Out of scope

- Real data in DATA, INVENTORY, or MAP.
- Anything that requires new server fields.
- Idle screensaver, audio.

### Success criteria

- All four section buttons switch the active section instantly,
  from any sub-screen.
- DATA: encoder visibly moves the sub-tab highlight; Confirm enters
  the sub-tab body; Back returns to the sub-tab list.
- INVENTORY and MAP show the placeholder and ignore encoder /
  Confirm / Back without crashing or visually glitching.
- Header section-name field updates immediately on section switch.
- All M3 and M4 behaviors still pass (disconnect flips header to
  `RECONNECTING`, STATUS shows live HP, etc.).
- The full input vocabulary from M1 produces no exceptions in any
  section.

### Dependencies

- M4 (STATUS already implemented; this milestone adds the other
  three sections and the navigation shell around them).

---

## After M5: MVP done

At the end of M5 the companion app:

- Renders a Pip-Boy 2000 Mk I-style CRT screen surface at 480×800
  portrait, with a top header line and a section body.
- Connects to the existing step-1 server.
- Shows real HP data on STATUS.
- Exposes the full four-section navigation model with the locked
  input rules, ready to be filled in by future milestones gated on
  server protocol extensions.

The first natural post-MVP milestones, not planned here, are:

- Server protocol extension for quests + holodisks, followed by
  real DATA content.
- Server protocol extension for inventory.
- Server protocol extension for map.
- Real hardware backend behind `input/` (GPIO / serial encoder).
- Optional: physical-device design decisions (whether the case
  carries date/time/water-chip indicators, or whether those move
  back into the screen surface).
