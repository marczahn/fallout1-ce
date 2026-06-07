# Companion App M2 — Feature Tickets

Derived from `docs/companion_app/plans/mvp-milestones.md` (M2) and
`docs/companion_app/plans/concept.md`. This document breaks M2 into
trackable tickets. It does not redefine the milestone; it makes it
actionable.

## Scope Statement

Deliver the visual baseline of the companion app: load the Fallout
webfont, draw a monochrome-green CRT screen surface at 480×800
virtual resolution, and render a fixed screen shell composed of a
top header line (active section name on the left, connection-status
indicator on the right) and a body area (centered `PIPBOY 2000`
placeholder). All values in the shell are static in M2; live data
and section switching arrive in M3+. A config-driven CRT scanline
overlay is supported. The M1 debug event overlay is feature-flagged
off by default; it remains available behind a config flag for
developer use.

## Out Of Scope (M2)

Carried over from the milestone, restated as a hard wall:

- No networking. No TCP client, no handshake code, no `state/`
  cache.
- No live data of any kind. Header status field stays static (`--`).
  Section name stays static (`STATUS`).
- No section-switching logic. `SectionButton` events still emit
  (M1) but no section state machine consumes them in M2.
- No section-specific bodies (STATUS HP, DATA sub-tabs, etc.).
  Those land in M4 and M5.
- No bezel, case chrome, clock, date, or water-chip indicator.
- No idle screensaver, no animations, no audio.
- No hardware backend behind `input/`. Keyboard emulation only.
- No threads, no async, no web stack, no new runtime dependencies
  beyond what `pygame` already provides.

## Cross-Cutting Constraints

- **Simple solution bias.** No new runtime dependencies. The
  Fallout font is rendered through facilities `pygame` already
  ships with (`pygame.freetype` or `pygame.font`). If the font
  format cannot be loaded directly, convert offline once and vendor
  the converted file; do not add a font-conversion library to the
  runtime.
- **Built-in functionality preferred.** `pygame.freetype` for text,
  `pygame.Surface` for offscreen buffers, `pygame.transform.scale`
  for the existing virtual-to-window blit (already in place from
  M1).
- **Localized diff.** Touch only `companion_app/` (new
  `render/` and `ui/` packages, the vendored font under
  `assets/`, `config.py`, `app.py`, `README.md`, and the example
  configs). Do not edit engine code. Do not edit unrelated docs.
- **Single thread, single process.** No background asset loaders.
  Font load happens once at startup, synchronously, before the
  main loop starts.
- **No leakage of future milestones.** M2 does not create
  `net/`, `state/`, `ui/status.py`, `ui/data.py`, `ui/inventory.py`,
  or `ui/map.py`. They land in M3/M4/M5.
- **Pure rendering layer.** `render/` knows nothing about the input
  layer, the (future) network layer, or sections. `ui/shell.py`
  composes `render/` primitives and is fed values by `app.py`.
- **Deterministic loop.** The 60 FPS budget from M1 stands. Any new
  per-frame work introduced in M2 (overlays, text rendering) must
  cache stable surfaces so the loop stays headroom-positive.
- **Replaceability of the shell.** `ui/shell.py` exposes a narrow
  draw API that takes section name, connection status, and the
  body surface as parameters. It does not own application state.
  M4/M5 wire real values in without rewriting the shell.

## Resolved Decisions

1. **Code location.**
   - `companion_app/companion_app/render/` — palette, font loader,
     text helpers, CRT overlay.
   - `companion_app/companion_app/ui/` — screen shell (`shell.py`).
   - `companion_app/assets/` — vendored font file (and its license
     note, if upstream requires it).
   - The `net/`, `state/`, and section UI modules are still **not**
     created in M2.
2. **Final M2 package layout (additions only).**
   ```
   companion_app/
     assets/
       jh_fallout-webfont.ttf    # see Decision 3
       FONT_LICENSE.md           # upstream attribution if applicable
     companion_app/
       render/
         __init__.py
         palette.py              # color constants
         font.py                 # font loader + text helpers
         background.py           # screen background fill
         crt.py                  # scanline overlay
       ui/
         __init__.py
         shell.py                # header + body composition
   ```
3. **Font format.** Vendor the font as **TrueType (`.ttf`)**, not
   `.woff`. `pygame.freetype` does not officially support WOFF on
   all platforms `pygame` runs on, and adding a runtime font
   converter is not justified for one font. The conversion is done
   once, offline, by the engineer in M2-T1 using `fonttools`
   (developer-time only; not added to `pyproject.toml`). The
   `.ttf` file is the only font asset shipped. The conversion
   command and source URL are recorded in `assets/FONT_LICENSE.md`
   (or in the README if licensing requires no separate file).
4. **Palette.** Three colors only, defined as
   `tuple[int, int, int]` constants in `render/palette.py`:
   - `BACKGROUND = (0, 16, 0)` — near-black with a green bias.
   - `FOREGROUND = (51, 255, 102)` — bright Pip-Boy green.
   - `DIM       = (26, 160, 51)` — same hue, halved brightness, for
     deemphasized text and separator rules.
   Future sections may add palette aliases for "warning" or
   "critical" states; M2 does not introduce them.
5. **Font sizes.** Two sizes only in M2:
   - `HEADER = 22 px` — section name and connection status on the
     top header line.
   - `BODY   = 32 px` — the `PIPBOY 2000` centered placeholder.
   Sizes are pixel-accurate on the 480×800 virtual surface and
   scale with the window via the existing virtual-to-window
   `pygame.transform.scale` blit (M1).
6. **Header layout (virtual pixel coordinates).**
   - Header occupies the top **40 px** of the virtual surface.
   - Section name is left-aligned at `(16, 8)` baseline-top.
   - Connection status is right-aligned with a 16 px right margin
     on the same baseline.
   - A 1-pixel `DIM` separator rule is drawn at `y = 40`.
   - Body rect is `(0, 41)` to `(480, 800)`.
   These coordinates are constants in `ui/shell.py`. They are
   tweakable; they are not negotiable per-frame.
7. **Header status vocabulary (M2 reservation).** `ui/shell.py`
   accepts a status string parameter. M2 only ever passes `--`.
   The full M3+ vocabulary (`OK`, `NO SIGNAL`, `CONNECTING`,
   `RECONNECTING`) is reserved by documentation in
   `shell.py`'s module docstring so M3 does not need to renegotiate
   layout. M2 does not implement state-driven color changes; status
   text in M2 is always `FOREGROUND`.
8. **CRT overlay.**
   - Implementation: a single pre-rendered `pygame.Surface` the
     size of the virtual surface, with a 1-pixel `BACKGROUND`-colored
     line every 2 px at 35% alpha (`SRCALPHA`). Built once at
     startup, blitted on top of the body each frame.
   - Configurable via a new config key `display.crtOverlay`
     (bool, default `true`). Already mentioned as a future key in
     M1; M2 reads it.
   - When `false`, the overlay surface is not built and not
     blitted. Zero per-frame cost.
9. **Debug overlay (M1) feature flag.** A new config key
   `debug.eventLog` (bool, default `false`) controls whether the
   M1 debug overlay is constructed, fed, and drawn. Default `false`
   so the M2 visual is clean. When `true`, the overlay is drawn on
   top of the screen shell (including the CRT overlay) for
   developer use. The overlay code from M1-T5 is not deleted in M2;
   the M1 milestone doc earmarked it for "removal or
   feature-flagging," and feature-flagging is the chosen path.
10. **New config keys honored in M2.**
    - `display.crtOverlay` (bool, default `true`).
    - `debug.eventLog` (bool, default `false`).
    All other unknown keys continue to warn-and-ignore per M1.
    `config.example.json` is updated to surface both new keys.
11. **No public render API beyond what M2 uses.** `render/font.py`
    exposes only the helpers the shell actually needs:
    `load_font(size: int) -> Font`, `draw_text_left(...)`,
    `draw_text_right(...)`, `draw_text_centered(...)`. No
    underline/strike-through helpers in M2; the milestone doc
    mentions "hooks for later sections" but a hook with no caller
    is dead code. They land when their consumer lands.
12. **Font load failures are fatal at startup.** Missing or
    unreadable font file aborts before the main loop with a clear
    error message (similar shape to `ConfigError`). The fallback to
    the pygame default font is **not** allowed in M2: the green CRT
    look depends on the right font.
13. **Asset path resolution.** The vendored font is shipped inside
    the installed package via `[tool.setuptools.package-data]` (or
    PEP 621 equivalent) so `pip install -e companion_app/` still
    finds it. Path is resolved via `importlib.resources`. No
    relative-CWD path tricks.
14. **Existing virtual surface and scaling stay in `app.py` for
    M2.** The milestone doc mentions "virtual-resolution-to-window
    scaling" under M2 scope; it is already implemented in M1-T2
    (`app.py:74-77`). M2 does not refactor it into `render/`. If a
    later milestone (e.g. M3's connection-state display) needs to
    share that logic, it moves then.

## Top-Level Success Criteria (For Closing M2)

1. `pip install -e companion_app/` still succeeds; the vendored
   font asset is installed alongside the package.
2. `python -m companion_app` opens the 480×800 (× `display.scale`)
   window without traceback and shows:
   - `BACKGROUND` green-tinted fill across the whole virtual
     surface.
   - Top header line at the configured coordinates with
     `STATUS` on the left and `--` on the right, rendered in
     the Fallout font at the `HEADER` size in `FOREGROUND`.
   - A `DIM` separator rule under the header.
   - Body area with `PIPBOY 2000` centered horizontally and
     vertically within the body rect, rendered in the Fallout
     font at the `BODY` size in `FOREGROUND`.
3. With `display.crtOverlay = true` (default), horizontal scanlines
   are visible on top of the body. With `display.crtOverlay = false`
   they are absent. Toggling the value across runs produces the
   expected visual difference without artifacts.
4. With `debug.eventLog = false` (default), the M1 debug event
   overlay is **not** drawn. With `debug.eventLog = true`, the
   overlay reappears at the bottom of the screen and behaves as in
   M1.
5. The Fallout font renders correctly for the printable ASCII range
   the M2 strings use (`STATUS`, `--`, `PIPBOY 2000`).
6. Window scaling preserves aspect ratio without distortion at at
   least two scale factors (e.g. `1.0` and `1.5`), verified
   manually.
7. The app exits cleanly via `Escape`, `q`, and the OS window-close
   button, with return code `0` and no lingering pygame state. M1's
   quit semantics are unchanged.
8. No new runtime dependency in `pyproject.toml` beyond `pygame`.
9. Missing or unreadable font file aborts at startup with a
   one-line error and a non-zero return code; pygame is shut down
   cleanly.
10. Unknown config keys still warn-and-ignore; malformed JSON still
    aborts before pygame is initialized (M1 behavior preserved).
11. No bezel, frame, clock, date, water-chip indicator, or other
    chrome is drawn anywhere on the screen.

---

## Tickets

### M2-T1 — Font Asset Pipeline

**Status:** todo

**Goal:** Vendor the Fallout webfont as a TrueType file inside the
installed package, expose a font loader that returns sized `Font`
objects, and document the conversion path.

**Scope:**
- Convert `jh_fallout-webfont.woff` from
  <https://github.com/xird/pip-boy-2000-mk-I/blob/main/html/jh_fallout-webfont.woff>
  to `.ttf` offline (engineer's local one-time step). Record the
  command and the upstream URL in `companion_app/assets/FONT_LICENSE.md`
  along with whatever attribution upstream requires.
- Place the resulting `jh_fallout-webfont.ttf` under
  `companion_app/assets/`.
- Update `pyproject.toml` so the asset ships inside the installed
  package (via `[tool.setuptools]` `package-data` or a
  `[tool.setuptools.packages.find]` + MANIFEST setup — pick the
  simplest one that works for `pip install -e`).
- Implement `companion_app/companion_app/render/font.py`:
  - `load_font(size: int) -> pygame.freetype.Font` (or
    `pygame.font.Font`; pick one and stick with it for M2).
  - Resolves the font path via `importlib.resources`.
  - Raises a clear `FontLoadError` (new exception class) if the
    asset is missing or unreadable; the error message includes the
    resolved path.
  - Caches the underlying file load so repeated `load_font(size)`
    calls do not re-read the file.
- Add a one-paragraph note to `companion_app/README.md` describing
  the font source, the conversion step (so future contributors can
  redo it), and the license file location.

**Acceptance:**
- `pip install -e companion_app/` in a fresh venv installs the
  `.ttf` and `load_font(22)` returns a usable Font instance from
  inside both the editable install and an installed wheel.
- Renaming the asset to an invalid path causes `load_font` to
  raise `FontLoadError` with the resolved path in the message.
- `pyproject.toml` declares no new runtime dependency.
- Imports of `render/font.py` do not initialize `pygame.display`.

**Notes:**
- Do not add a runtime font converter. The one-time conversion is a
  developer task, not a runtime feature.
- Do not introduce a font-fallback to the pygame default. M2's
  visual identity depends on this font; failing loud is correct.

---

### M2-T2 — Palette and Render Primitives

**Status:** todo

**Goal:** Establish the monochrome-green palette, the background
fill, and the text-drawing helpers the screen shell will compose.

**Scope:**
- Implement `companion_app/companion_app/render/palette.py`:
  - Module-level constants `BACKGROUND`, `FOREGROUND`, `DIM` per
    Resolved Decision 4.
- Implement `companion_app/companion_app/render/background.py`:
  - `fill_background(surface: pygame.Surface) -> None` fills the
    given surface with `palette.BACKGROUND`.
- Extend `companion_app/companion_app/render/font.py` with text
  helpers used by the shell:
  - `draw_text_left(surface, text, pos, size, color) -> Rect`
  - `draw_text_right(surface, text, right_pos, size, color) -> Rect`
  - `draw_text_centered(surface, text, rect, size, color) -> Rect`
  - All helpers use the loader from M2-T1. All return the blitted
    rect for downstream layout if needed.
- No new public API surface beyond these helpers in M2.

**Acceptance:**
- Calling each helper on a 480×800 surface produces visually
  correct positioning at the documented coordinates (manually
  verified in M2-T6).
- Helpers raise on negative sizes or missing surfaces with a
  `TypeError`/`ValueError` shaped to match Python conventions, not
  silent failures.
- Unit tests cover positional math for `draw_text_left` and
  `draw_text_right` (e.g. assert the returned rect's `x` matches
  the input for left-aligned and `right` matches for right-aligned)
  using a headless pygame display
  (`SDL_VIDEODRIVER=dummy`, same harness as M1's tests).
- `palette.py` contains only color constants; no functions, no
  imports beyond `__future__`.

**Notes:**
- No underline/strike-through helpers in M2 (Resolved Decision 11).
- No theme/skin abstraction. There is one palette.

---

### M2-T3 — Screen Shell (Header + Body)

**Status:** todo

**Goal:** Compose the static screen shell: header line with
section name and connection status, separator rule, and centered
body placeholder. Wire it into `app.py`.

**Scope:**
- Implement `companion_app/companion_app/ui/shell.py`:
  - Module docstring lists the reserved connection-status vocabulary
    (`OK`, `NO SIGNAL`, `CONNECTING`, `RECONNECTING`) so M3 does
    not have to renegotiate.
  - `HEADER_HEIGHT = 40`, `SEPARATOR_Y = 40`, plus the body rect
    constant.
  - `def draw_shell(surface, section_name: str, status: str,
        body_text: str) -> None`:
    - Calls `render.background.fill_background(surface)`.
    - Renders `section_name` left-aligned in the header at
      `HEADER` size, `FOREGROUND` color.
    - Renders `status` right-aligned in the header at `HEADER`
      size, `FOREGROUND` color.
    - Draws a 1-px `DIM` line at `SEPARATOR_Y`.
    - Renders `body_text` centered in the body rect at `BODY`
      size, `FOREGROUND` color.
- Update `companion_app/companion_app/app.py`:
  - Remove the M1 flat-black background fill.
  - On each frame call `draw_shell(virtual, "STATUS", "--",
    "PIPBOY 2000")`.
  - The M1 debug overlay is still constructed and fed, but it is
    only drawn when `config.debug_event_log` is `True` (see
    M2-T5). For this ticket, keep the existing M1 behavior; the
    flag lands in M2-T5.

**Acceptance:**
- Running `python -m companion_app` shows the static screen
  described in Success Criterion 2 above.
- `draw_shell` is a pure draw call — it does not mutate any module
  state, does not initialize pygame, and does not depend on
  `app.py`.
- Unit test: pass a mock surface (a small offscreen Surface,
  headless) and assert the returned `Rect`s from the font helpers
  fall inside the header / body rects respectively.
- No imports from `companion_app.input`, `companion_app.config`,
  or `companion_app.debug` in `ui/shell.py`.

**Notes:**
- `draw_shell` takes its strings as parameters specifically so M3
  can pass dynamic values without rewriting the shell.
- Do not introduce a "Section" or "Screen" base class. There is one
  shell.

---

### M2-T4 — CRT Scanline Overlay

**Status:** todo

**Goal:** Add a config-driven CRT scanline overlay on top of the
shell body.

**Scope:**
- Implement `companion_app/companion_app/render/crt.py`:
  - `build_scanline_overlay(size: tuple[int, int]) -> pygame.Surface`
    returns an `SRCALPHA` surface of the given size with
    `BACKGROUND`-colored lines every 2 pixels at 35% alpha
    (per Resolved Decision 8).
  - `class ScanlineOverlay`: holds the prebuilt surface; exposes
    `draw(target: pygame.Surface) -> None` blitting at `(0, 0)`.
- Extend `config.py`:
  - New field `display_crt_overlay: bool = True` on `Config`.
  - Honor the `display.crtOverlay` JSON key; type-check (must be
    bool); warn-and-ignore the rest.
- Update `app.py`:
  - If `config.display_crt_overlay` is `True`, build a
    `ScanlineOverlay` once at startup and call `overlay.draw(virtual)`
    after `draw_shell(...)` and before the scale-blit.
  - If `False`, do not build or draw it.
- Update `companion_app/config.example.json` and the README to
  document the new key.

**Acceptance:**
- With `display.crtOverlay` absent or `true`, scanlines are visible
  over the body each frame. With `false`, they are absent and no
  `ScanlineOverlay` instance is constructed.
- Loop frame budget at 60 FPS is preserved (no per-frame surface
  rebuild — the overlay is built once).
- Unit test: `build_scanline_overlay((480, 800))` produces a
  surface of the right size with at least one non-transparent
  pixel on every even Y and a transparent pixel on every odd Y
  (or vice versa, depending on which row is drawn — assert the
  pattern alternates with period 2).
- A non-bool value for `display.crtOverlay` aborts startup with a
  `ConfigError` referencing the offending key.

**Notes:**
- Do not animate scanlines in M2. No flicker, no jitter.
- Do not implement a full CRT shader (barrel distortion, glow,
  bloom). Scanlines only.

---

### M2-T5 — Debug Overlay Feature Flag

**Status:** todo

**Goal:** Move the M1 debug event overlay behind a config flag,
default off, so the M2 visual is clean but the overlay is still
available for developer use.

**Scope:**
- Extend `config.py`:
  - New field `debug_event_log: bool = False` on `Config`.
  - Honor the `debug.eventLog` JSON key; type-check (must be bool).
- Update `app.py`:
  - Only construct the `EventLogOverlay` when
    `config.debug_event_log` is `True`.
  - Only feed it events when present.
  - Only call `overlay.draw(virtual)` when present; draw it
    **after** the CRT overlay so events are readable.
- Update `companion_app/config.example.json` and the README to
  document the new key and explain it is a developer aid.
- Update or add a short note in M1-T5's ticket file pointing at
  this ticket as the feature-flag landing site (optional; only if
  it avoids future confusion — do not edit M1 prose otherwise).

**Acceptance:**
- Default run (`debug.eventLog` absent or `false`): no debug
  overlay is drawn, no `EventLogOverlay` is instantiated.
- `--config` pointing at a file with `"debug": { "eventLog": true }`
  produces the M1 behavior: last 10 events at the bottom of the
  screen.
- A non-bool value for `debug.eventLog` aborts startup with a
  `ConfigError`.
- The `companion_app/companion_app/debug/event_log.py` module is
  unchanged.

**Notes:**
- Do not delete the M1 debug module. M1-T5 explicitly allowed
  either deletion or feature-flagging; we chose feature-flagging
  (Resolved Decision 9).
- Do not promote the overlay into "the M2 visual" with styling. It
  remains the unstyled M1 helper.

---

### M2-T6 — Manual + Headless Validation

**Status:** todo

**Goal:** Walk through the M2 Top-Level Success Criteria and
record pass/fail in the same style as the M1-T6 validation log.

**Scope:**
- Execute each Top-Level Success Criterion (1–11) above.
- For criteria that need config variations, ship two example
  configs under `companion_app/examples/`:
  - `m2-default.json` — empty object (relies on defaults), or
    explicit `display.crtOverlay = true`, `debug.eventLog = false`.
  - `m2-debug-overlay.json` — `debug.eventLog = true`,
    `display.crtOverlay = false`, `display.scale = 1.5`.
- For the missing-font criterion (9), temporarily rename the
  vendored asset and capture the exact exit message.
- For the malformed-JSON criterion (10), reuse `examples/malformed.json`
  from M1-T6.
- Run unit tests added in M2-T2, M2-T3, and M2-T4 via the
  project's standard runner; record the green result.

**Acceptance:**
- All 11 criteria pass on Linux with Python 3.11+ and pygame ≥ 2.5.
- Any failure produces a written reproduction and a referenced
  `file:line`.
- A validation log is appended to this ticket on completion,
  mirroring M1-T6's table format.

**Notes:**
- This is the QA hand-off. Engineering does not self-approve.
- Windows and macOS remain out of the validation matrix; document
  it in the log.
- Visual checks (font legibility, scanline visibility, body
  centering) require a real display and are noted as `PENDING`
  in any headless pre-pass.

---

## Suggested Ordering

M2-T1 → M2-T2 → M2-T3 → M2-T4 → M2-T5, then M2-T6 (QA). M2-T4 and
M2-T5 can be implemented in either order once M2-T3 is in place;
they touch the same `app.py` integration point and should land
back-to-back to avoid integration churn.

## Rejection Heuristics For Future Proposals

Push back on any of:

- Adding a font-conversion library (`fonttools`, `Pillow`) to the
  runtime dependency set to "load `.woff` directly."
- Introducing a theme or skin abstraction "since we will want
  multiple palettes later."
- Animating the CRT overlay (flicker, scroll, glow) in M2.
- Adding underline / strike-through / blink text helpers without a
  caller (M3/M4 will request them when needed).
- Refactoring the virtual-surface scale-blit out of `app.py` into
  `render/` without a second consumer.
- Creating empty `net/`, `state/`, `ui/status.py`, `ui/data.py`,
  `ui/inventory.py`, or `ui/map.py` modules "to reserve the
  namespace."
- Replacing the static `STATUS` / `--` placeholders with any kind of
  read from input or future network state inside M2.
- Adding a logging framework to the codebase because "the overlay
  should also log to a file."

M2 is the visual baseline. It earns its keep by making the rest of
the app look like a Pip-Boy without committing to any live data.
Defend that.
