# Companion App — Concept

## Purpose

A standalone desktop application that drives the **screen** of a
future physical Pip-Boy-style device. The device's case provides the
bezel, the section buttons, the rotary encoder, the confirm/back
buttons, and (if it ever has them) any extra physical indicators
like a clock strip or status lights. The app is responsible only
for what is rendered inside the screen rectangle.

The aesthetic target is the Fallout 1 Pip-Boy 2000 Mk I CRT screen.
The functional target is closer to the Fallout 4 companion app: a
useful second-screen view of game state. The app consumes data from
the in-game companion server over TCP (see
`docs/plans/companion-server-step-1.md`).

The app is read-only against the game in the MVP. It does **not**
control the in-game Pip-Boy, does not send commands to the engine,
and does not pause or alter gameplay. The MVP runs on a desktop
with keyboard input standing in for the future physical controls.

## Non-Goals (MVP)

- No control of the game (no rest, no fast travel, no item use).
- No write-back of state.
- No emulation of the in-game Pip-Boy as input device.
- No multi-instance, no remote/internet operation.
- No real hardware integration yet — only keyboard emulation of the
  intended hardware control surface.
- No audio (no radio, no UI sounds) in the MVP.

## Reference: the in-game Pip-Boy 2000 Mk I

The Fallout 1 Pip-Boy is a wrist-mounted, monochrome-feel green CRT
device. Visually (from `src/game/pipboy.cc`):

- Fixed 640×480 chrome with a green/amber CRT inset.
- **Chrome (around the screen):** day strip, month icon, year,
  digital `HHMM` clock, water-chip "days remaining" note panel,
  Vault-Tec logo, holiday text, 5 red section buttons on the left,
  alarm button. **None of this is the companion app's
  responsibility.** It belongs to the physical device case (or is
  omitted entirely on hardware that does not have these
  affordances).
- **Screen (monitor):** inner rect `(254,46)` size `374×410`. All
  dynamic content is drawn here in blocky monospace, with optional
  underline / strike-through, left- and right-column layout, and
  paged text. **This is the only surface the companion app draws.**
- **Sections in the original** (rendered inside the screen rect):
  - **Status** — quest log (left column: locations) + holodisks
    (right column: known disks). Completed quests are strike-through.
    Holodisks open a paged reader.
  - **Automaps** — list of known cities; per city, list of elevations;
    drawing of the top-down map.
  - **Archives** — list of in-game movies the player has seen, with
    replay.
  - **Alarm Clock** — rest timer (10 min .. until healed / party
    healed).
- **Idle screensaver** — falling-bombs animation after 120 s of no
  input.

The faithful Fallout 1 Pip-Boy has **no** stats, SPECIAL, inventory,
HP, AP, perks, or radio. Those live in the character screen and the
HUD. Putting them on the Pip-Boy is the artistic-freedom layer.

## Reference: Fallout 4 companion app

Used here only as a functional reference for what makes a useful
"second screen" companion:

- Stats: HP, status effects, SPECIAL, perks.
- Inventory: weapons, apparel, aid, misc, ammo, mods.
- Data: quests, workshops, stats, logs.
- Map: local + world map, markers.
- Radio: stations.

The MVP cherry-picks the small subset of this that maps cleanly onto
Fallout 1 mechanics and onto the data the companion server can
realistically provide.

## Look and Feel

The app renders only the screen content. No bezel, no frame, no
case affordances.

- Monochrome green CRT palette: one foreground tint, one dim tint,
  one background. No color UI.
- Monospace bitmap-style font (see Resolved Design Decisions).
  Pixel-aligned. No anti-aliased sub-pixel text.
- Optional CRT scanline overlay, off by default. Cheap to do in
  pygame as a pre-rendered translucent surface.
- **Virtual resolution: 480×800 portrait.** Targets a 7" Pi-class
  panel rotated to portrait. Pygame renders at the virtual
  resolution and scales to the window for desktop development.
- **On-screen layout:**
  - **Top header line** (single text line): active section name on
    the left, small connection-status indicator on the right
    (`OK`, `NO SIGNAL`, `RECONNECTING`). This is the app's
    substitute for the chrome highlight that the original used to
    show which section was active.
  - **Body**: the active section's content fills the remainder of
    the screen. Sections own their own internal layout (lists,
    paged text, etc.).
- No idle screensaver in the MVP.

## Hardware Control Surface

Intended physical inputs:

- **4 main section buttons** (labelled by current top-level tab).
- **1 rotary encoder** (rotate left / rotate right events).
- **1 enter / confirm button**.
- **1 back button**.

That's it. No mouse, no touchscreen, no keyboard in the final form.

### Mapping rules

- **4 section buttons** → switch top-level section. Always available,
  always overrides current sub-screen. Pressing the current section's
  button again resets that section to its root view.
- **Rotary encoder** → move the highlight up/down in lists, page in
  long text, scrub through numeric values. Context-dependent but
  always "navigate within the current screen".
- **Enter** → activate the current highlight (open a quest, open a
  holodisk page, drill into a sub-section).
- **Back** → go up one level in the current section. At the section's
  root, Back is a no-op (it does **not** switch sections — that's
  what the 4 section buttons are for).

### Why 4 buttons

The original Pip-Boy already exposes exactly 4 active section buttons.
The Fallout 4 companion has more (Stat / Inv / Data / Map / Radio),
but for a hardware device with a fixed button count the cleaner
mapping is:

- 4 hardware buttons = 4 top-level categories.
- Each category can have any number of sub-tabs/sub-views, navigated
  by encoder + enter + back.

Trade-off: every additional top-level category beyond 4 forces a
nesting decision. That's a design constraint, not a bug. The MVP
sections below are chosen to fit 4 cleanly.

### Dev-time keyboard emulation

Until real hardware exists, pygame maps keys to control events:

- `1` `2` `3` `4` → section buttons 1..4
- `Up` / `Down` (or `-` / `=`) → encoder left / right
- `Enter` → confirm
- `Backspace` or `Esc` → back
- `q` → quit the companion app (dev only)

These are device-emulation keys, not part of the final UX.

## Top-Level Sections (MVP)

Four sections, one per hardware button. Names are tentative.

### 1. STATUS

Faithful-ish: the Pip-Boy's own "is everything okay" screen.

- Header line: HP `cur/max`.
- (Later) AC, current weapon, ammo, radiation, status effects.
- Sub-screen: nothing in MVP. Just a single read-only panel.

This is the screen most people will leave on by default. It must work
even when the game has no loaded character (show "NO SIGNAL" or
similar when `playerAvailable` is false).

### 2. DATA

Quests + holodisks, like the original Status section.

- Encoder scrolls a unified list of quest locations + known holodisks
  (or two visual columns with encoder selecting across both — TBD,
  see open questions).
- Enter opens the selected entry.
- Inside a quest: list of quest lines, strike-through for completed.
- Inside a holodisk: paged reader, encoder turns pages.
- Back returns one level.

### 3. INVENTORY

Pure artistic freedom — does not exist in the original Pip-Boy.

- Categories: Weapons, Armor, Ammo, Aid, Misc.
- Encoder scrolls items in the current category.
- Enter shows item detail (description, weight, value).
- Back returns to category list.
- Sub-tab switching between categories: encoder at root, or a
  secondary affordance (TBD; see open questions).

Inventory requires a server protocol extension that does not yet
exist. The MVP for this section may launch with a "NOT YET
IMPLEMENTED" placeholder until the server-side step ships.

### 4. MAP

- World map with current location marker.
- Local automap of the current map (if exposed by the server).
- Encoder pans or selects markers.
- Enter shows marker info.

Also requires a server protocol extension. Same staged-rollout note
as Inventory.

## Server Data Needs

What the MVP needs from the companion server and how it compares to
what the step-1 plan delivers.

### Already in step 1

- `playerAvailable`, `player.hp`, `player.maxHp` — covers the STATUS
  section MVP.

### Required additions (rough, post-MVP)

- `quests` — list of `{locationId, lines: [{text, completed}]}`.
- `holodisks` — list of `{id, title, pages: [text]}`.
- `inventory` — list of `{category, name, count, weight, value, desc}`.
- `map` — current map id, world position, known markers.

In-game clock, date, and water-chip days remaining are **not** in
this list. Those belonged to the original Pip-Boy chrome, which is
now a physical-device concern. If a future device design moves them
back into the screen surface, server fields will be added then.

These should be planned as **separate server steps**, not bundled.
The companion app can ship each section as the corresponding server
step lands. STATUS is the only fully-buildable section against
step-1 data.

The protocol direction (newline JSON, snapshot + update, schema
versioning) is unchanged. New fields go under the existing
`snapshot.data` and `update.entity` model. No new transport.

## Application Architecture (sketch)

Single Python process, single thread, pygame main loop.

- `net/` — TCP client, framing (newline JSON), reconnect, handshake
  (`hello` → `world` → `get_snapshot`), inbound `update` dispatch.
- `state/` — local cache of the last known snapshot, mutated by
  inbound messages. Pure data; no rendering.
- `input/` — hardware-abstraction layer. Emits `SectionButton(n)`,
  `EncoderLeft`, `EncoderRight`, `Confirm`, `Back`. Pygame keyboard
  events feed this in dev.
- `ui/` — screens. One module per top-level section. A small
  navigation stack inside each section. Also owns the top header
  line shared across all sections.
- `render/` — font loader, palette, screen-area helpers, optional
  CRT overlay. No frame / bezel rendering.
- `app.py` — wires it together, owns the pygame main loop,
  dispatches input events to the active screen and drives net
  polling.

Threading: none. The TCP socket is non-blocking and polled once per
frame, identical in spirit to how the server side polls in
`process_bk`. This keeps the app deterministic and easy to debug.

Resolution: render at the virtual resolution **480×800 portrait**
and let pygame scale to the window for desktop dev. The eventual
hardware target is a 7" Pi-class panel rotated to portrait. No DPI
handling.

## Connection Lifecycle

- App starts. The top header shows the default section name and
  connection status `CONNECTING`. The body shows a centered
  `CONNECTING…` line.
- Attempts TCP connect to a configured host:port.
- On connect: sends `hello`, waits for `world`, sends
  `get_snapshot`, header status flips to `OK`, body switches to
  the last-active section (or STATUS by default).
- On disconnect or socket error: header status flips to
  `RECONNECTING`, body switches back to the `CONNECTING…` panel,
  the active section's last-known state is preserved in memory but
  not rendered. Reconnect uses exponential backoff (capped).
- `playerAvailable: false`: header status shows `NO SIGNAL`. The
  body of the current section shows a `NO SIGNAL` placeholder.
  Section buttons still work.

## Configuration

Plain JSON or INI file next to the executable:

- `server.host`
- `server.port`
- `display.scale`
- `display.crtOverlay` (bool)
- `input.keymap` (dev only)

No GUI for configuration in the MVP.

## Resolved Design Decisions

1. **DATA section layout:** split into two sub-tabs
   (Quests / Holodisks). At the section root, encoder selects the
   sub-tab; enter drops into it; back at the root is a no-op.
2. **Inventory / Map sections:** ship as placeholders in the MVP
   ("NOT YET IMPLEMENTED" panel). Real implementations are gated by
   future server protocol work and are post-MVP.
3. **Font:** use `jh_fallout-webfont.woff` from
   <https://github.com/xird/pip-boy-2000-mk-I/blob/main/html/jh_fallout-webfont.woff>.
   The app renders this font via pygame's freetype/font support.
   Font licensing is upstream's responsibility; we treat it as a
   third-party asset.
4. **Idle screensaver:** out of MVP scope. No timer, no animation.
5. **Sub-tab switching inside a section:** at a section's root the
   encoder switches sub-tabs; enter drops into the highlighted
   sub-tab; back at a section root is a no-op. Uniform across all
   sections.

## Remaining Risks

1. **Hardware abstraction reality check.** Until a real device
   exists, the encoder/button mapping is theoretical. Keep `input/`
   narrow and replaceable so a GPIO/serial backend can be added
   without touching `ui/`.
2. **Server protocol gap.** Step-1 server only exposes player HP.
   STATUS is the only section that can show real data in the MVP.
   Chrome clock/date/water-chip and DATA/INVENTORY/MAP all require
   additional server steps. The companion MVP is built to degrade
   gracefully when those fields are absent.

## Out of Scope (later concept rounds)

- Sending commands to the game (rest, use item, fast travel).
- Audio / radio.
- Persistent local notes.
- Multiple saved "profiles".
- Real hardware build / enclosure.
- Authentication beyond what the server requires.

## Next Steps

1. Agree on the four MVP top-level sections and the sub-tab model.
2. Lock the input event vocabulary (`SectionButton(n)`,
   `EncoderLeft`, `EncoderRight`, `Confirm`, `Back`).
3. Write a small server-protocol gap analysis: which sections need
   which new snapshot fields, in what order, to inform companion
   server step 3+.
4. Produce a first implementation plan covering only:
   - app skeleton (pygame loop, input abstraction, net client),
   - the chrome (clock, date, water-chip note, frame),
   - the STATUS section against existing step-1 data.
   That's the smallest vertical slice that proves the whole stack.
