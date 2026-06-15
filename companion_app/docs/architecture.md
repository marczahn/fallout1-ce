# Companion App Architecture

## Purpose

The companion app is a standalone Python + pygame application that renders the
screen surface for a Pip-Boy-style companion device. It is read-only against the
game. It consumes state from the Fallout CE companion server over TCP using
newline-delimited JSON and renders the synchronized state into a 480x800
portrait virtual screen.

The app does not modify the game engine, send game commands, or define server
protocol changes. Data that is not currently exposed by the server is a server
task first and an app UI task second.

## Runtime Shape

The app is intentionally single-threaded:

```text
pygame events
    |
    v
KeyboardInput -> InputEvent list
    |
    v
app.py main loop
    |
    +--> NetworkClient.poll() -> AppState
    |
    +--> BootSequence.tick() -> start network timing
    |
    +--> page routing -> current Page / page-local UI state
    |
    v
Layout + active page renderer -> virtual surface -> scaled window
```

There are no background threads, async framework, HTTP server, websocket layer,
or separate process. The socket is non-blocking and is polled once per frame.

## Package Layout

```text
companion_app/
  app.py              main entry point and pygame loop
  config.py           config loading, validation, and key resolution
  __main__.py         python -m companion_app entry point
  input/              fixed hardware-style input vocabulary and keyboard backend
  net/                newline JSON framing and TCP client
  state/              pure in-memory state cache
  render/             palette, font loading, background, CRT overlays
  ui/                 shared layout and top-level pages
  debug/              typewriter console and event log overlay
  assets/             vendored Fallout font and license
tests/                stdlib unittest suite
examples/             example JSON configs for manual checks
docs/                 local companion-app documentation
```

The top-level `README.md` covers installation, running, config shape, and test
commands. This document focuses on structure and ownership.

## Entry Point And Main Loop

`companion_app/app.py` owns the application lifecycle:

- Parses `--config`.
- Loads and resolves configuration.
- Initializes pygame display state.
- Creates a fixed 480x800 virtual surface.
- Preloads all font sizes used by the UI.
- Creates shared app objects: `KeyboardInput`, `AppState`,
  `TypewriterConsole`, `BootSequence`, optional CRT overlays, `Layout`, and
  page renderers.
- Runs the frame loop at `TARGET_FPS = 60`.
- Cleans up the network client and pygame on exit.

Per frame, the loop:

1. Reads pygame events.
2. Handles dev-only quit keys and console visibility toggle.
3. Converts keyboard events into the fixed `InputEvent` vocabulary.
4. Routes input only after the boot sequence exposes the main UI.
5. Polls the network client if it has been started.
6. Advances the typewriter console and boot sequence.
7. Draws either the boot page or the shared layout with the active page,
   followed by CRT overlays and optional debug overlay.
8. Scales the virtual surface to the configured window size.

## Boot Sequence

`ui/pages/boot.py` owns both the startup timeline and the dedicated boot page
renderer. The app starts on this boot page, not on the normal `STATUS` shell.
The boot transcript and successful connection log are drawn into the boot page
console area.

Current phases:

- `BOOTING`: queues and types the static boot transcript.
- `CURSOR_HOLD`: leaves the transcript visible and blinks the idle cursor for
  `BOOT_CURSOR_HOLD_MS` (3000 ms).
- `CONNECTING`: asks `app.py` to create the `NetworkClient`; connection logs are
  printed to stderr/debug output. Failed connection attempts are not printed
  into the visible boot console. The visible console shows the uplink target
  line with an idle cursor until the network state reaches `READY` and the
  console has finished typing.
- `READY_HOLD`: waits one second after a successful connection before showing
  the main UI.
- `COMPLETE`: enables normal input routing and page behavior.

Only `COMPLETE` reveals the main `STATUS` page. A failed connection therefore
leaves the user on the boot/connection screen with the cursor visible while the
client retries quietly once per second.

## Configuration

`config.py` owns all startup config parsing and validation.

Config resolution order:

1. Explicit `--config PATH`.
2. `./companion_app.config.json` in the current working directory.
3. Built-in defaults, except `server.password`, which is required.

Parsing is split into two stages:

- JSON parsing and schema validation happen first. Malformed JSON fails before
  pygame is initialized.
- Key names are resolved to pygame key codes after pygame is initialized.

Unknown config keys are warned about and ignored. Invalid known keys raise
`ConfigError` and abort startup.

## Input Model

`input/events.py` defines the full logical input surface:

- `PageButtonEvent(index)` for buttons 1 through 4.
- `EncoderLeftEvent`.
- `EncoderRightEvent`.
- `ConfirmEvent`.
- `BackEvent`.

`input/keyboard.py` is the current backend. It maps pygame `KEYDOWN` events
through the resolved keymap and returns zero or more `InputEvent` instances per
frame. `KEYUP` is ignored. Pygame key repeat is disabled in `app.py`, so each
physical key press maps to one logical event.

Any future hardware input backend should preserve the same `poll(...) ->
list[InputEvent]` shape and should not introduce new logical event types without
an explicit product decision.

## Navigation And Pages

`ui/pages/__init__.py` defines the four top-level pages:

- `STATUS`, bound to section button 1.
- `DATA`, bound to section button 2.
- `INVENTORY`, bound to section button 3.
- `MAP`, bound to section button 4.

`app.py` owns top-level routing. Page buttons always switch pages. Selecting
`DATA` resets its page-local UI state to the root. Non-page inputs are currently
handled only by `DATA`.

Page responsibilities:

- `StatusPage` renders live HP and max HP when the connection is ready and the
  player is available.
- `DataPage` implements root sub-tab selection for `QUESTS` and `HOLODISKS`,
  then renders placeholder detail screens.
- `InventoryPage` renders a placeholder.
- `MapPage` renders a placeholder.

The page objects are lightweight renderers. The only page-local state today is
`DataPageUiState`, which is immutable and returned from pure transition
helpers.

## Rendering

Rendering is split across `render/` and `ui/`:

- `render/palette.py` defines the current three-color monochrome palette:
  background, foreground, and dim.
- `render/font.py` loads the vendored Fallout font from package resources and
  caches fonts by size.
- `render/background.py` fills the virtual surface.
- `render/crt.py` builds the startup-only power-on effect plus the
  scanline, vertical sweep, vignette, and rounded-corner CRT overlays.
  The static surfaces are built once at startup; the animated sweep
  reuses a cached band surface and changes only its draw position each
  frame; the power-on effect temporarily transforms the already-rendered
  startup frame for a few hundred milliseconds and then disables itself.
- `ui/layout.py` draws the shared shell: background, centered page title,
  connection status, header underline, content rect, and generic placeholders.
- `ui/shell.py` stores shared geometry and font-size constants.

The app always renders to the 480x800 virtual surface first. The final blit is
either direct or scaled to the configured window size. This keeps UI positions
stable and avoids every page needing to reason about desktop window dimensions.

## Debug UI

`debug/console.py` implements the typewriter console used for boot, connection,
and protocol logs during startup. It owns line typing, cursor blink, color
selection, and visible line clipping. Once the boot sequence completes, the
normal page shell does not draw the console or its frame.

`debug/event_log.py` is an optional developer overlay controlled by
`debug.eventLog`. It is intentionally separate from the styled Pip-Boy shell
and can overlap screen content.

The Tab key toggles the typewriter console visibility at runtime.

## State Model

`state/models.py` is pure data. It imports neither pygame nor networking code.

Current state:

- `ConnectionState`: `DISCONNECTED`, `CONNECTING`, `AWAITING_AUTH`,
  `AWAITING_WORLD`, `AWAITING_SNAPSHOT`, `READY`, `RECONNECTING`.
- `WorldInfo`: schema version, game name, and player availability from `world`.
- `PlayerState`: availability, current HP, and max HP.
- `AppState`: shared aggregate mutated by the network client and read by the UI.

The UI reads `AppState` directly but does not mutate it. Network code mutates
the shared state in response to protocol messages.

## Network And Protocol Handling

`net/framing.py` contains pure newline-delimited JSON helpers:

- `encode_line(obj)` serializes compact ASCII JSON and appends `\n`.
- `read_line(buffer)` extracts one newline-terminated JSON object from a byte
  buffer and returns the parsed dict plus the remaining bytes. Malformed JSON,
  invalid UTF-8, and non-object JSON values return `None` for the message.

`net/client.py` owns the non-blocking TCP client and protocol dispatch.

Current handshake flow:

```text
DISCONNECTED
  -> _connect()
CONNECTING
  -> connected socket detected
  -> send auth
  -> send hello
AWAITING_WORLD
  -> receive world
  -> send getSnapshot
AWAITING_SNAPSHOT
  -> receive snapshot
READY
  -> apply update / onPlayerUnavailable / onPlayerAvailable messages
     (onPlayerAvailable re-enters AWAITING_SNAPSHOT for re-sync)
```

The client currently queues `auth` and `hello` together once the socket is
connected. It then waits for `world`, requests a snapshot, and applies player
vitals from the snapshot and subsequent `player.vitals` updates.

Reconnect behavior is active. `_on_error(...)` logs to stderr/debug output,
closes the socket, sets the connection state to `RECONNECTING`, and schedules
the next connection attempt one second later. Transient connection attempts and
failures are not forwarded to the visible boot typewriter; successful handshake
messages still are.

## Connection Status Display

`app.py` maps `AppState` to a header status string:

- `READY` plus player available: `OK` (not drawn in the header by `Layout`).
- `READY` plus player unavailable: `NO SIGNAL`.
- `RECONNECTING`: `RECONNECTING`.
- Any other non-disconnected state: `CONNECTING`.
- `DISCONNECTED`: `--`.

Body placeholder behavior:

- Before boot completes: the dedicated boot page is rendered instead of the main
  layout.
- After boot completes and connection is not ready: `CONNECTING...`. In normal
  startup this should not appear because boot completion requires `READY`; it is
  still the fallback for later disconnect/reconnect states.
- After ready with unavailable player: `NO SIGNAL`.
- After ready with available player: active page renders its own content.

The source string uses the single unicode ellipsis in code today; docs use
`...` to stay ASCII.

## Tests

The app uses stdlib `unittest`. Tests live in `companion_app/tests/`.

Coverage areas include:

- Config parsing and validation.
- Input event creation and keyboard mapping.
- Network framing and client state transitions.
- Pure state models.
- Font/render helpers and CRT overlays.
- Layout, shell, boot sequence, pages, status rendering.
- Typewriter console and debug event log.
- App helper functions for connection status, body text, and routing.

`tests/__init__.py` forces SDL dummy video and audio drivers so pygame tests run
headless.

Primary command:

```sh
.venv/bin/python -m unittest discover -s tests
```

Run from the `companion_app/` directory.

## Extension Rules

Use these boundaries when adding app features:

- Keep the app read-only. Do not add game commands to the app.
- Keep protocol changes in the server plans first. The app should consume
  exposed data, not invent it.
- Keep networking inside `net/`; do not spread socket logic into UI pages.
- Keep pygame rendering inside `render/`, `ui/`, and debug modules.
- Keep `state/` pure and import-light. It should remain safe to unit test
  without pygame or sockets.
- Keep input vocabulary stable unless the hardware/control model changes.
- Add page-local UI state only where the page needs it; do not create a broad
  global UI state object prematurely.
- Preserve the fixed virtual resolution and scale at the final blit unless a
  real display target changes.

## Known Gaps
- `AWAITING_AUTH` exists in the state enum and tests, but the current client
  sends `auth` and `hello` together and transitions directly to
  `AWAITING_WORLD`.
- `DATA`, `INVENTORY`, and `MAP` do not have live game data yet.
- Only player HP and max HP are rendered from server state.
- The app has no hardware input backend yet; keyboard input is dev emulation.
