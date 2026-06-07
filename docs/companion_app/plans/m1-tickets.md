# Companion App M1 — Feature Tickets

Derived from `docs/companion_app/plans/mvp-milestones.md` (M1) and
`docs/companion_app/plans/concept.md`. This document breaks M1 into
trackable tickets. It does not redefine the milestone; it makes it
actionable.

## Scope Statement

Deliver a runnable Python + pygame application skeleton that opens a
window at the virtual resolution 480×800 portrait, runs a
deterministic main loop at a fixed frame rate, loads its
configuration from a JSON file, and converts dev-keyboard input into
the locked hardware-style input event vocabulary
(`SectionButton(1..4)`, `EncoderLeft`, `EncoderRight`, `Confirm`,
`Back`). A throwaway debug overlay shows the last 10 emitted events
to allow manual verification. No networking, no real UI chrome, no
section logic.

## Out Of Scope (M1)

Carried over from the milestone, restated as a hard wall:

- No networking. No TCP client, no handshake code, no `state/`
  cache.
- No rendering primitives beyond the bare debug overlay (no Fallout
  font, no palette, no CRT overlay, no screen shell).
- No section content, no section navigation logic, no header line.
- No real hardware backend behind `input/` (GPIO/serial). Keyboard
  emulation only.
- No threads, no async framework, no web stack.
- No audio.
- No build of an installable distribution (wheel/exe). M1 is
  developer-run only.
- No tests beyond what is needed to verify the input event mapping
  is deterministic; M1 is primarily manually validated.

## Cross-Cutting Constraints

- **Simple solution bias.** Stick to the standard library plus
  `pygame`. Do not pull in a config schema library, a logging
  framework, or an event-bus library for an app that does not yet
  have a UI.
- **Built-in functionality preferred.** `json` from stdlib for
  config. `argparse` for the optional `--config` flag. `logging`
  from stdlib if any logging is added; otherwise plain `print` to
  stderr is acceptable for M1.
- **Single thread, single process.** Pygame main loop drives
  everything. No background workers in M1, and none introduced
  "for later."
- **Locked input vocabulary.** Exactly five event types, no more,
  no fewer: `SectionButton(n)` with `n ∈ {1,2,3,4}`,
  `EncoderLeft`, `EncoderRight`, `Confirm`, `Back`. Any future
  hardware mapping (GPIO/serial) must produce the same vocabulary.
- **Replaceable input backend.** `input/` exposes a narrow
  interface so the keyboard backend can be swapped for a hardware
  backend without touching `ui/` (which does not exist yet) or
  `app.py`. M1 ships only the keyboard backend.
- **No section logic leaks into M1.** Section buttons emit events;
  nothing in M1 consumes them as navigation. The debug overlay is
  the only consumer.
- **Localized diff.** Touch only the new `companion_app/`
  subdirectory, its package files, and one short note in the
  existing milestone plan if a clarification is unavoidable.
- **Deterministic loop.** Fixed frame rate via `pygame.time.Clock`.
  No frame-time-dependent input logic in M1.

## Resolved Decisions

1. **Code location.** All companion-app code lives in
   `companion_app/` at the repo root. Python package name is
   `companion_app`. This keeps it visibly separate from the C++
   engine in `src/` and from server-side plans in `docs/plans/`.
2. **Package layout.**
   ```
   companion_app/
     pyproject.toml
     README.md            # one-page run instructions
     companion_app/
       __init__.py
       __main__.py        # `python -m companion_app`
       app.py             # main loop
       config.py          # config loader + defaults
       input/
         __init__.py
         events.py        # event dataclasses + enum
         keyboard.py      # pygame keyboard backend
       debug/
         __init__.py
         event_log.py     # last-10-events overlay (M1 only)
     config.example.json
   ```
   The `net/`, `state/`, `ui/`, `render/` packages from the
   architecture sketch are **not** created in M1. They land in
   their respective milestones.
3. **Python and pygame versions.** Python ≥ 3.11 (stdlib `tomllib`,
   stable `dataclasses`, modern typing). `pygame` ≥ 2.5. Pin loose
   lower bounds only; no upper pins.
4. **Dependency management.** `pyproject.toml` with PEP 621
   metadata and a single runtime dep (`pygame`). Dev dep group
   carries only what M1 actually uses (nothing required beyond
   `pygame` itself for M1; the dev group exists but is empty or
   contains `ruff` if the engineer wants a linter — optional).
   No `poetry`, no `pipenv`, no `conda`. `pip install -e .` is the
   contract.
5. **Frame rate.** Fixed at **60 FPS** via
   `pygame.time.Clock().tick(60)`. Configurable later if needed;
   not configurable in M1.
6. **Virtual resolution.** Fixed at **480×800 portrait**. Pygame
   renders to a `pygame.Surface` of that size and blits it scaled
   to the window. Window size in M1 = virtual size × `display.scale`
   (default `1.0`). Scaling preserves aspect ratio; no letterboxing
   logic needed at 1.0.
7. **Config file format.** JSON (not INI, not TOML). One file,
   resolved in this order:
   1. `--config PATH` CLI flag (explicit override).
   2. `./companion_app.config.json` in the current working
      directory.
   3. Built-in defaults (no file needed to run).
   Unknown keys are ignored with a warning. Missing keys fall back
   to defaults. Malformed JSON is a hard error at startup.
8. **Config keys present in M1.** Only the keys M1 actually uses:
   - `display.scale` (float, default `1.0`)
   - `input.keymap` (object, dev only; see decision 10)
   Future keys (`server.host`, `server.port`, `display.crtOverlay`)
   are documented in `config.example.json` as commented-out hints
   but are **not** read by M1 code. They land in their milestones.
9. **Key repeat policy.** **Filtered.** Holding a key produces
   exactly one event on `KEYDOWN`. `pygame.key.set_repeat(0)` is
   set explicitly. Rationale: hardware buttons and an encoder do
   not "repeat" on the bus; if real hardware ever wants repeat
   semantics, it will emit discrete events itself.
10. **Default dev keymap.** Matches the milestone doc, with the
    minor concept-doc options collapsed to one choice each:
    - `1` `2` `3` `4` → `SectionButton(1..4)`
    - `Up` → `EncoderLeft`
    - `Down` → `EncoderRight`
    - `Return` (Enter) → `Confirm`
    - `Backspace` → `Back`
    - `Escape` or `q` → quit app (dev only; not an input event,
      handled directly by `app.py`)
    Keymap is overridable via `input.keymap` in config. Format is
    `{ "<event>": ["<pygame key name>", ...] }` where event names
    are the literal strings `SectionButton1`, `SectionButton2`,
    `SectionButton3`, `SectionButton4`, `EncoderLeft`,
    `EncoderRight`, `Confirm`, `Back`. Multiple keys may map to
    one event. Unknown event names or key names abort startup
    with a clear error.
11. **Event representation.** Tagged dataclasses, not raw tuples.
    `SectionButtonEvent(index: int)`, `EncoderLeftEvent()`,
    `EncoderRightEvent()`, `ConfirmEvent()`, `BackEvent()`.
    A `union` type alias `InputEvent` covers all five. This is
    the interface every future backend (hardware, test stub) must
    produce.
12. **Debug overlay.** Renders with pygame's built-in default font
    (`pygame.font.Font(None, ...)`). Bottom of the screen, most
    recent event last. Capped at 10 lines. **M1 only** — it is
    explicitly slated for removal or feature-flagging in M2 when
    the real screen shell lands.
13. **Quit semantics.** `Escape`, `q`, and the window close button
    all quit cleanly: stop the main loop, call `pygame.quit()`,
    return `0` from `main()`. No `sys.exit` from deep call sites.

## Top-Level Success Criteria (For Closing M1)

1. `pip install -e companion_app/` succeeds in a fresh Python 3.11+
   virtualenv on Linux.
2. `python -m companion_app` opens a 480×800 (× `display.scale`)
   window without traceback.
3. Pressing each mapped key produces exactly one event of the
   correct type, visible at the bottom of the window in the debug
   overlay.
4. Holding any mapped key produces exactly **one** event (key
   repeat is filtered, per decision 9).
5. The four section buttons produce `SectionButton(1)` through
   `SectionButton(4)` with the correct `index` value.
6. `Up` and `Down` produce `EncoderLeft` and `EncoderRight`
   respectively.
7. `Return` produces `Confirm`; `Backspace` produces `Back`.
8. `Escape`, `q`, and clicking the window close button all exit
   cleanly with return code `0` and no lingering pygame state
   (no orphan SDL window on the desktop, no Python tracebacks).
9. Passing `--config path/to/file.json` with a non-default keymap
   re-routes events correctly without code changes.
10. Running with no config file present succeeds using built-in
    defaults.
11. Running with a malformed JSON config aborts at startup with a
    one-line error and a non-zero return code.

---

## Tickets

### M1-T1 — Project Skeleton

**Status:** done

**Goal:** Create the `companion_app/` package layout and make it
installable and runnable as `python -m companion_app`, with a no-op
entry point.

**Scope:**
- Create the directory tree from Resolved Decision 2.
- Write `pyproject.toml` (PEP 621):
  - `name = "companion_app"`
  - `requires-python = ">=3.11"`
  - `dependencies = ["pygame>=2.5"]`
  - Optional dev group containing nothing required (placeholder
    only).
  - `[project.scripts]` is **not** added in M1; entry is
    `python -m companion_app` only.
- `companion_app/__main__.py` calls `companion_app.app.main()` and
  exits with its return code.
- `companion_app/app.py` exports a `main()` that returns `0`
  immediately. The real loop lands in M1-T2.
- Write a one-page `companion_app/README.md` describing the
  install and run commands. No screenshots.
- Add a `config.example.json` at `companion_app/config.example.json`
  showing the schema with M1 keys filled in and future keys
  commented out (`// ...` style in a sibling note since JSON has
  no comments — keep the file as valid JSON and put hints in
  `README.md`).

**Acceptance:**
- `pip install -e companion_app/` succeeds in a fresh venv.
- `python -m companion_app` exits immediately with return code 0
  and no traceback.
- The directory tree matches Resolved Decision 2 exactly. No
  `net/`, `state/`, `ui/`, or `render/` packages are created.

**Notes:**
- Do not create empty placeholder modules for future milestones.
  They will be created when their milestones start.
- No CI changes in M1.

---

### M1-T2 — Pygame Main Loop And Window

**Status:** done

**Goal:** Open a window at the virtual resolution, run a 60 FPS
main loop, render a solid background, and exit cleanly on quit.

**Scope:**
- Initialize pygame in `app.main()`.
- Create a virtual surface of size `480×800`.
- Create a window of size `(480 * scale, 800 * scale)` where
  `scale` comes from config (default `1.0`).
- Call `pygame.key.set_repeat(0)` once at startup.
- Main loop:
  - Poll events.
  - Fill the virtual surface with a flat color (use `(0, 0, 0)`
    for M1; the green palette belongs to M2).
  - Blit the virtual surface scaled to the window.
  - `clock.tick(60)`.
- Quit handling: `pygame.QUIT`, `K_ESCAPE`, and `K_q` all set a
  `running = False` flag and break the loop.
- `pygame.quit()` is called exactly once on exit.

**Acceptance:**
- Window opens at the expected size for `scale = 1.0` and for
  `scale = 1.5` (verified manually).
- Window remains responsive (no "not responding" on Linux) under
  idle and under continuous key mashing.
- Closing the window via the OS close button, `Escape`, or `q`
  all return cleanly with code 0.
- No `pygame` warnings on stderr during normal startup/shutdown.

**Notes:**
- Do not introduce a render module in M1. The flat fill lives in
  `app.py`. M2 will refactor it into `render/`.
- Do not add FPS readout to the debug overlay in M1; the overlay
  is for input events only.

---

### M1-T3 — Configuration Loader

**Status:** done

**Goal:** Load M1's config keys from a JSON file with the
resolution order from Resolved Decision 7, applying defaults and
validating keymap entries.

**Scope:**
- Implement `companion_app/config.py`:
  - A `Config` dataclass with fields `display_scale: float` and
    `keymap: dict[str, list[int]]` (key constants resolved from
    pygame key names at load time).
  - `load_config(path: str | None) -> Config`:
    - If `path` is provided, read it; if missing, error out.
    - Otherwise, try `./companion_app.config.json`; if missing,
      use defaults.
    - Parse JSON. On parse error, raise with the file path in the
      message.
    - Merge over defaults key by key. Unknown keys log a warning
      and are ignored.
    - Resolve each key name in `input.keymap` via
      `pygame.key.key_code(name)` (or equivalent) at load time.
      Unknown key name → error with the offending value.
    - Unknown event name in `input.keymap` → error with the
      offending value.
- `app.main()` accepts `--config PATH` via `argparse` and passes
  it to `load_config`.

**Acceptance:**
- Running with no flag and no file uses defaults; window opens.
- Running with `--config` pointing at a valid file applies the
  overrides; `display.scale` change visibly resizes the window;
  a non-default keymap re-routes the events from M1-T4.
- Malformed JSON aborts at startup with a one-line error and a
  non-zero return code; pygame is not initialized.
- Unknown event names (e.g. `SectionButton5`, `Submit`) abort with
  a clear error.

**Notes:**
- `pygame` must be importable (and minimally initialized for
  `pygame.key.key_code`) before keymap resolution. Do not open a
  display to resolve keys; `pygame.display.init()` is not
  required for the `key` module on supported backends. If a
  platform forces it, document the workaround in the file.
- Do not use `pydantic` or `jsonschema`. Hand-roll the validation.

---

### M1-T4 — Input Abstraction (Keyboard Backend)

**Status:** done

**Goal:** Translate pygame `KEYDOWN` events into the locked input
event vocabulary, behind a narrow interface that a future hardware
backend can replace.

**Scope:**
- Implement `companion_app/input/events.py`:
  - Dataclasses: `SectionButtonEvent(index: int)`,
    `EncoderLeftEvent`, `EncoderRightEvent`, `ConfirmEvent`,
    `BackEvent`.
  - Type alias `InputEvent = Union[...]`.
- Implement `companion_app/input/keyboard.py`:
  - `class KeyboardInput`:
    - `__init__(self, keymap: dict[str, list[int]])`
    - `poll(self, pygame_events: list[pygame.event.Event])
        -> list[InputEvent]`
    - Iterates `KEYDOWN` events, looks up the key in the inverted
      keymap, and appends the matching `InputEvent`.
    - Ignores keys not in the keymap.
    - Ignores `KEYUP` entirely.
- `app.py` instantiates `KeyboardInput` once, calls `poll` each
  frame, and forwards events to the debug overlay (and only the
  debug overlay, in M1).
- The interface contract is documented in `events.py`'s module
  docstring: "Any input backend must implement
  `poll(pygame_events) -> list[InputEvent]` and may produce
  zero or more events per frame."

**Acceptance:**
- All eight mapped keys produce the correct event type, verified
  via the debug overlay.
- `SectionButton(n)` carries the correct `index` (1, 2, 3, or 4).
- Holding any key produces exactly one event per press, not a
  stream (verified via overlay not flooding).
- Unmapped keys (e.g. `a`, `F1`) produce no events and no log
  output.
- A config-driven keymap change (e.g. swap `Up` and `Down`)
  inverts encoder behavior without code changes.

**Notes:**
- Do not generalize to a "backend factory" abstraction in M1.
  `KeyboardInput` is the only backend that exists. M2 does not
  add another either; that is a hardware-milestone concern.
- Do not introduce a separate `InputEventQueue` or a global event
  bus. `poll` returns a list; `app.py` consumes it.

---

### M1-T5 — Debug Event Overlay

**Status:** done

**Goal:** Render the last 10 input events at the bottom of the
window so M1 can be validated by eye.

**Scope:**
- Implement `companion_app/debug/event_log.py`:
  - `class EventLogOverlay`:
    - Holds a `collections.deque(maxlen=10)` of events.
    - `record(event: InputEvent) -> None`
    - `draw(surface: pygame.Surface) -> None`
  - Uses `pygame.font.Font(None, 18)` (default font). One line
    per event, most recent at the bottom. Left-aligned with a
    small margin.
  - Format: the dataclass `repr()` is acceptable
    (`SectionButtonEvent(index=2)`, `EncoderLeftEvent()`, …).
- `app.py` creates one overlay, records each polled event, and
  calls `draw` after the background fill, before the scale-blit.

**Acceptance:**
- Pressing any mapped key adds a line at the bottom of the
  overlay within one frame.
- After 10 events, older lines are dropped (FIFO).
- The overlay does not crash with zero events.
- The overlay is rendered at virtual resolution and scales with
  the window.

**Notes:**
- This module is explicitly M1-scoped. M2's screen shell ticket
  is allowed (and expected) to delete or feature-flag this
  overlay. Do not invest in styling it.
- No file logging in M1. The overlay is the validation surface.

---

### M1-T6 — Manual Validation

**Status:** done

**Goal:** Walk through the 11 success criteria above and record
pass/fail.

**Scope:**
- Execute each Top-Level Success Criterion from this document.
- For criteria that require config variations, ship two example
  configs alongside the validation note (default keymap; swapped
  encoder keymap) and run both.
- For the malformed-JSON criterion, use a deliberately broken
  file (e.g. trailing comma) and capture the exact exit message.

**Acceptance:**
- All 11 criteria pass on Linux with Python 3.11 and pygame ≥ 2.5.
- Any failure produces a written reproduction and a referenced
  `file:line`.
- A short validation log is appended to this ticket on completion,
  mirroring the style of the T7 validation log in
  `docs/plans/companion-server-step-1-tickets.md`.

**Notes:**
- This is a hand-off to the QA persona. Engineering does not
  self-approve.
- Windows and macOS are not part of M1's validation matrix.
  Document that fact in the validation log; do not stub anything
  platform-specific for them in M1.

#### Validation log — headless pass (engineer-run, awaits QA sign-off)

Environment: Linux, Python 3.12.3, pygame 2.6.1 (SDL 2.28.4),
`SDL_VIDEODRIVER=dummy`. Windows / macOS explicitly out of scope.

Example configs shipped under `companion_app/examples/`:

- `keymap-default.json` — default keymap, `display.scale = 1.0`.
- `keymap-swapped-encoder.json` — swaps `EncoderLeft`/`EncoderRight`,
  `display.scale = 1.5`.
- `malformed.json` — trailing-comma JSON used to drive C11.

Reproduction: from `companion_app/`, run the harness embedded in the
T6 ticket discussion (headless pygame driver, posted SDL events for
the keyboard paths, subprocess invocation for the malformed-JSON
exit). Full per-criterion log:

| # | Status   | Evidence |
|---|----------|----------|
| 1 | PASS     | `companion_app` importable; pygame 2.6.1. |
| 2 | PASS     | `load_and_resolve_config(None)` → `scale=1.0`, computed window `(480, 800)`. |
| 3 | PENDING  | Overlay rendering verified to draw without crash and FIFO-trim at 10; visual "line appears within one frame" requires a human at a real display. |
| 4 | PASS     | `pygame.key.set_repeat(0)` present in `_run_loop` (`app.py:43`); one `KEYDOWN` → one `InputEvent`. |
| 5 | PASS     | `K_1..K_4` → `SectionButtonEvent(index=1..4)`. |
| 6 | PASS     | `K_UP` → `EncoderLeftEvent`, `K_DOWN` → `EncoderRightEvent`. |
| 7 | PASS     | `K_RETURN` → `ConfirmEvent`, `K_BACKSPACE` → `BackEvent`. |
| 8 | PARTIAL  | Posted `KEYDOWN(K_ESCAPE)`, `KEYDOWN(K_q)`, and `pygame.QUIT` each cause `main([])` to return `0`. OS window-close button (`WM_DELETE_WINDOW`) is dispatched as `pygame.QUIT` by SDL and is therefore covered by the QUIT case in code, but the user-side click path is **PENDING** manual confirmation. |
| 9 | PASS     | `examples/keymap-swapped-encoder.json` → `K_UP` produces `EncoderRightEvent`, `K_DOWN` produces `EncoderLeftEvent`; `scale=1.5` applied. |
| 10 | PASS    | In a tempdir with no `companion_app.config.json`, defaults load (`scale=1.0`, default keymap populated). |
| 11 | PASS    | `python -m companion_app --config examples/malformed.json` exits with code `2`; single stderr line: `companion_app: config error: malformed JSON in examples/malformed.json: line 2 col 30: Expecting property name enclosed in double quotes`. |

Manual sign-off (user-run on real display):

- C3: confirmed. Mapped keys (`1`, `2`, `3`, `4`, arrows, Enter,
  Backspace) each print a line in the bottom overlay on press.
- C8: confirmed. OS window close button, `Escape`, and `q` all exit
  cleanly with no traceback.

All 11 success criteria pass. T6 closed.

---

## Suggested Ordering

M1-T1 → M1-T2 → M1-T3 → M1-T4 → M1-T5, then M1-T6 (QA). M1-T3 and
M1-T4 can be implemented in either order once M1-T2 is in place,
but the keymap loader (T3) is the natural prerequisite for
T4's input mapping.

## Rejection Heuristics For Future Proposals

Push back on any of:

- Adding a config schema library (`pydantic`, `jsonschema`,
  `attrs`-based loaders) "for safety."
- Introducing an event bus or pub/sub layer "since the structure
  will need it later."
- Creating empty `net/`, `state/`, `ui/`, or `render/` packages
  "to reserve the namespace."
- Adding a hardware backend stub "to prove the interface."
- Wiring section-button events into a navigation stack "since
  it'll save time in M5."
- Adding a logging framework configuration file for an app that
  does not yet log anything.

M1 is the skeleton. It earns its keep by being small enough to
read end to end. Defend that.
