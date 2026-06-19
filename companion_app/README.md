# Companion App

Python + pygame companion app for Fallout 1 CE. Renders the contents
of a Pip-Boy 2000 Mk I-style CRT screen and consumes data from the
in-game companion server via TCP / newline-delimited JSON.

This package implements milestones **M1–M5** of
`docs/companion_app/plans/mvp-milestones.md`: app skeleton, CRT screen shell, dev keyboard input, network handshake, live STATUS rendering, and full MVP section navigation with placeholder DATA/INVENTORY/MAP pages.

## Documentation

- `docs/architecture.md` — current package structure, runtime flow,
  module boundaries, protocol handling, rendering model, tests, and
  known implementation gaps.

## Requirements

- Python >= 3.11
- pygame >= 2.5

## Install

From the repo root:

```sh
python3 -m venv companion_app/.venv
companion_app/.venv/bin/pip install -e companion_app/
```

## Run

```sh
companion_app/.venv/bin/python -m companion_app
```

Optional config:

```sh
companion_app/.venv/bin/python -m companion_app --config path/to/config.json
```

Config resolution order:

1. `--config PATH` if given.
2. `./companion_app.config.json` in the current working directory.
3. Built-in defaults.

## Config schema

```json
{
  "display": {
    "scale": 1.0,
    "crtOverlay": true,
    "powerOnEffect": true,
    "verticalSweep": true,
    "vignette": true,
    "roundedCrt": true
  },
  "debug": {
    "eventLog": false
  },
  "input": {
    "keymap": {
      "PageButton1": ["1"],
      "PageButton2": ["2"],
      "PageButton3": ["3"],
      "PageButton4": ["4"],
      "EncoderLeft":    ["up"],
      "EncoderRight":   ["down"],
      "Confirm":        ["return"],
      "Back":           ["backspace"]
    }
  },
  "server": {
    "host": "127.0.0.1",
    "port": 28080,
    "password": "changeme"
  },
  "map": {
    "greenLevels": 4,
    "pixelBlocks": 110
  }
}
```

Honored keys:

- `display.scale` — window scale factor over the 480×800 virtual
  surface. Must be a positive number. Default `1.0`.
- `display.crtOverlay` — master switch for the animated CRT layer stack.
  Enables the CRT-specific startup and steady-state effects. Must be a
  boolean. Default `true`. When `false`, the startup power-on effect,
  scanline overlay, and moving phosphor sweep are not built.
- `display.powerOnEffect` — startup-only CRT power-on effect. Briefly
  compresses the splash/boot image into a thin central raster that expands
  to full height with a subtle decaying wobble, approximating raster
  deflection settling plus a degauss-like shake. Must be a boolean.
  Default `true`. This flag is only honored when `display.crtOverlay`
  is also `true`.
- `display.verticalSweep` — draw the moving top-to-bottom phosphor sweep
  band that simulates an energized CRT refresh pass. Must be a boolean.
  Default `true`. This flag is only honored when `display.crtOverlay`
  is also `true`.
- `display.vignette` — radial edge-darkening overlay. Darkens the
  screen edges using a power-curve falloff to suggest CRT phosphor
  dropout near the bezel. Must be a boolean. Default `true`. When
  `false`, the overlay is not built.
- `display.roundedCrt` — black bezel overlay that masks the four
  corners into a rounded CRT shape. Must be a boolean. Default `true`.
  When `false`, the overlay is not built.
- `debug.eventLog` — developer aid. When `true`, the M1 debug event
  overlay (last 10 input events, rendered at the bottom of the
  screen in the default pygame font) is drawn on top of the shell.
  Must be a boolean. Default `false`. Keep this off for normal use;
  it is unstyled and overlaps the body intentionally.
- `input.keymap` — keyboard bindings per input event. Each entry is
  a list of pygame key *names* (resolved at startup).
- `server.host` — companion server hostname or IP. Must be a non-empty
  string. Default `"127.0.0.1"`.
- `server.port` — companion server TCP port. Must be an integer 1–65535.
  Default `28080`.
- `server.password` — companion server auth password. **Required**.
  Must be a non-empty string. The app aborts at startup (before
  pygame init) if this key is missing or empty.
- `map.greenLevels` — number of distinct green shades the world map is
  posterized to (the "limited Pip-Boy hardware" look). Integer 2–256;
  lower is chunkier (`2` is 1-bit black/green). Default `4`.
- `map.pixelBlocks` — pixelation coarseness: roughly how many chunky
  blocks span the displayed map width. Integer 2–2000; lower is blockier.
  Default `110`.

## Dev keys

- `1`..`4` — section buttons 1..4
- `Up` / `Down` — encoder left / right
- `Enter` — confirm
- `Backspace` — back
- `Escape` or `q` — quit

## Tests

Stdlib `unittest`, no extra deps beyond the project dependency on `pygame`. Run from `companion_app/` with the project virtualenv:

```sh
.venv/bin/python -m unittest discover -s tests
```

The page-render smoke tests are included in the suite. To run just those:

```sh
.venv/bin/python -m unittest tests.test_pages
```

Tests force pygame's dummy SDL drivers via `tests/__init__.py`, so they run headless on CI and on machines without a display.

## Fallout webfont (M2)

The CRT screen shell renders text in the Fallout webfont, vendored
inside the package at `companion_app/assets/jh_fallout-webfont.ttf`.
It is a one-time offline conversion of
`jh_fallout-webfont.woff` from
<https://github.com/xird/pip-boy-2000-mk-I> (see
`companion_app/assets/FONT_LICENSE.md` for the exact source URL,
attribution, and the `fontTools` conversion command). `fontTools` is
**not** a runtime dependency; redo the conversion only if the upstream
`.woff` changes.

## Example configs

`examples/` contains ready-to-use configs for manual checks:

- `keymap-default.json` — default keymap.
- `keymap-swapped-encoder.json` — swapped encoder, `display.scale=1.5`.
- `m2-default.json` — default M2 config with CRT effects enabled.
- `m2-debug-overlay.json` — debug overlay enabled, CRT effects off,
  `display.scale=1.5`.
- `malformed.json` — trailing-comma JSON for the malformed-input check.
