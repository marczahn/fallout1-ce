"""Companion app configuration loader (M1).

JSON config file with two stages of validation:

1. Parse JSON. Malformed JSON is a hard error and is raised *before*
   pygame is initialized (so callers can fail fast with a non-zero
   exit code and no SDL state on the desktop).
2. After pygame has been initialized by the caller, resolve human
   key names ("up", "return", ...) to pygame key codes via
   `pygame.key.key_code`. Unknown event names or unknown key names
   abort with `ConfigError`.

Only the keys M1 actually consumes are honored. Unknown keys (e.g.
`server.host`, `display.crtOverlay`) are warned about and ignored.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_EVENT_NAMES: tuple[str, ...] = (
    "SectionButton1",
    "SectionButton2",
    "SectionButton3",
    "SectionButton4",
    "EncoderLeft",
    "EncoderRight",
    "Confirm",
    "Back",
)

DEFAULT_DISPLAY_SCALE: float = 1.0

# Default keymap uses pygame key *names* (resolved later to codes).
DEFAULT_KEYMAP_NAMES: dict[str, list[str]] = {
    "SectionButton1": ["1"],
    "SectionButton2": ["2"],
    "SectionButton3": ["3"],
    "SectionButton4": ["4"],
    "EncoderLeft":    ["up"],
    "EncoderRight":   ["down"],
    "Confirm":        ["return"],
    "Back":           ["backspace"],
}

DEFAULT_CONFIG_FILENAME = "companion_app.config.json"


class ConfigError(Exception):
    """Raised for any unrecoverable config problem at startup."""


@dataclass
class Config:
    display_scale: float = DEFAULT_DISPLAY_SCALE
    # event name -> list of pygame key codes
    keymap: dict[str, list[int]] = field(default_factory=dict)


def _warn(msg: str) -> None:
    print(f"companion_app: warning: {msg}", file=sys.stderr)


def _parse_json_file(path: Path) -> dict[str, Any]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConfigError(f"cannot read config file {path}: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(
            f"malformed JSON in {path}: line {e.lineno} col {e.colno}: {e.msg}"
        ) from e
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top-level value must be a JSON object")
    return data


def _merge_keymap_names(
    raw: dict[str, Any] | None,
    source: Path | None,
) -> dict[str, list[str]]:
    if raw is None:
        return {k: list(v) for k, v in DEFAULT_KEYMAP_NAMES.items()}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"input.keymap must be an object, got {type(raw).__name__}"
        )
    result = {k: list(v) for k, v in DEFAULT_KEYMAP_NAMES.items()}
    for event_name, key_names in raw.items():
        if event_name not in VALID_EVENT_NAMES:
            raise ConfigError(
                f"unknown event name in input.keymap: {event_name!r} "
                f"(valid: {', '.join(VALID_EVENT_NAMES)})"
            )
        if not isinstance(key_names, list) or not all(
            isinstance(k, str) for k in key_names
        ):
            raise ConfigError(
                f"input.keymap[{event_name!r}] must be a list of strings"
            )
        result[event_name] = list(key_names)
    return result


def _load_raw(path: str | None) -> tuple[dict[str, Any], Path | None]:
    """Resolve the config file and parse it. No pygame interaction."""
    if path is not None:
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"config file not found: {p}")
        return _parse_json_file(p), p

    cwd_candidate = Path.cwd() / DEFAULT_CONFIG_FILENAME
    if cwd_candidate.exists():
        return _parse_json_file(cwd_candidate), cwd_candidate

    return {}, None


def _extract_m1_fields(
    raw: dict[str, Any],
    source: Path | None,
) -> tuple[float, dict[str, list[str]]]:
    """Pull only the keys M1 cares about. Warn on the rest."""
    scale: float = DEFAULT_DISPLAY_SCALE
    keymap_names: dict[str, Any] | None = None

    for top_key, top_value in raw.items():
        if top_key == "display":
            if not isinstance(top_value, dict):
                raise ConfigError("display section must be an object")
            for k, v in top_value.items():
                if k == "scale":
                    if not isinstance(v, (int, float)) or isinstance(v, bool):
                        raise ConfigError(
                            f"display.scale must be a number, got {v!r}"
                        )
                    if v <= 0:
                        raise ConfigError(
                            f"display.scale must be > 0, got {v}"
                        )
                    scale = float(v)
                else:
                    _warn(f"ignoring unknown config key display.{k}")
        elif top_key == "input":
            if not isinstance(top_value, dict):
                raise ConfigError("input section must be an object")
            for k, v in top_value.items():
                if k == "keymap":
                    keymap_names = v
                else:
                    _warn(f"ignoring unknown config key input.{k}")
        else:
            _warn(f"ignoring unknown config key {top_key}")

    resolved_names = _merge_keymap_names(keymap_names, source)
    return scale, resolved_names


def _resolve_key_codes(keymap_names: dict[str, list[str]]) -> dict[str, list[int]]:
    """Resolve key names to pygame key codes. pygame must be initialized."""
    import pygame  # local import: kept off the malformed-JSON failure path

    resolved: dict[str, list[int]] = {}
    for event_name, names in keymap_names.items():
        codes: list[int] = []
        for name in names:
            try:
                code = pygame.key.key_code(name)
            except ValueError as e:
                # pygame's own message is just "unknown key name"; preserve
                # the offending value and the binding context so the user
                # can find it in their config.
                raise ConfigError(
                    f"unknown key name {name!r} for event {event_name}: {e}"
                ) from e
            # Be defensive in case a future pygame returns 0 instead.
            if code == 0:
                raise ConfigError(
                    f"unknown key name {name!r} for event {event_name}"
                )
            codes.append(code)
        resolved[event_name] = codes
    return resolved


def load_config(path: str | None) -> Config:
    """Parse the config file (if any). Defer key-code resolution.

    Returns a `Config` whose `keymap` is *empty*. Call
    `resolve_keymap(config, names)` after `pygame.init()` to populate
    it, or use `load_and_resolve_config()` which handles both stages.
    """
    raw, source = _load_raw(path)
    scale, _names = _extract_m1_fields(raw, source)
    return Config(display_scale=scale, keymap={})


def load_and_resolve_config(path: str | None) -> Config:
    """Two-stage load: parse JSON first (may raise pre-pygame), then
    initialize pygame and resolve key names to codes.

    This is the entry point `app.main()` uses. It guarantees malformed
    JSON aborts before pygame is initialized.
    """
    raw, source = _load_raw(path)
    scale, keymap_names = _extract_m1_fields(raw, source)

    # pygame must be initialized before key_code lookups.
    import pygame
    if not pygame.get_init():
        pygame.init()

    resolved = _resolve_key_codes(keymap_names)
    return Config(display_scale=scale, keymap=resolved)
