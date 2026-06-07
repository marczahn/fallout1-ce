# Companion App

Python + pygame companion app for Fallout 1 CE. Renders the contents
of a Pip-Boy 2000 Mk I-style CRT screen and (later) consumes data
from the in-game companion server.

This package corresponds to milestone **M1** of
`docs/companion_app/plans/mvp-milestones.md`: app skeleton, main
loop, and dev keyboard input. No networking, no UI chrome.

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

## Config schema (M1)

```json
{
  "display": { "scale": 1.0 },
  "input": {
    "keymap": {
      "SectionButton1": ["1"],
      "SectionButton2": ["2"],
      "SectionButton3": ["3"],
      "SectionButton4": ["4"],
      "EncoderLeft":    ["up"],
      "EncoderRight":   ["down"],
      "Confirm":        ["return"],
      "Back":           ["backspace"]
    }
  }
}
```

Future config keys reserved for later milestones (do not put them in
M1 configs; they are ignored with a warning):

- `server.host`, `server.port` — companion server endpoint (M3)
- `display.crtOverlay` — CRT scanline overlay toggle (M2)

## Dev keys

- `1`..`4` — section buttons 1..4
- `Up` / `Down` — encoder left / right
- `Enter` — confirm
- `Backspace` — back
- `Escape` or `q` — quit

## Tests

Stdlib `unittest`, no extra deps. Run from `companion_app/`:

```sh
.venv/bin/python -m unittest discover -s tests
```

Tests force pygame's dummy SDL drivers via `tests/__init__.py`, so
they run headless on CI and on machines without a display.

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
- `malformed.json` — trailing-comma JSON for the malformed-input check.
