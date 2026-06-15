"""Companion app configuration loader.

JSON config file with two stages of validation:

1. Parse JSON. Malformed JSON is a hard error and is raised *before*
   pygame is initialized (so callers can fail fast with a non-zero
   exit code and no SDL state on the desktop).
2. After pygame has been initialized by the caller, resolve human
   key names ("up", "return", ...) to pygame key codes via
   `pygame.key.key_code`. Unknown event names or unknown key names
   abort with `ConfigError`.

Only the keys the current app consumes are honored. Unknown keys
are warned about and ignored.

Currently honored keys:
  - `display.scale`         (float, M1)
  - `display.crtOverlay`    (bool,  M2)
  - `display.powerOnEffect` (bool,  M6)
  - `display.verticalSweep` (bool,  M6)
  - `display.vignette`      (bool,  M2)
  - `display.roundedCrt`    (bool,  M2)
  - `debug.eventLog`        (bool,  M2)
  - `input.keymap`          (object, M1)
  - `server.host`           (str,   M3)
  - `server.port`           (int,   M3)
  - `server.password`       (str,   M3, required, no default)
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_EVENT_NAMES: tuple[str, ...] = (
    "PageButton1",
    "PageButton2",
    "PageButton3",
    "PageButton4",
    "EncoderLeft",
    "EncoderRight",
    "Confirm",
    "Back",
)

DEFAULT_DISPLAY_SCALE: float = 1.0
DEFAULT_DISPLAY_CRT_OVERLAY: bool = True
DEFAULT_DISPLAY_POWER_ON_EFFECT: bool = True
DEFAULT_DISPLAY_VERTICAL_SWEEP: bool = True
DEFAULT_DISPLAY_VIGNETTE: bool = True
DEFAULT_DISPLAY_ROUNDED_CRT: bool = True
DEFAULT_DEBUG_EVENT_LOG: bool = False

# Default keymap uses pygame key *names* (resolved later to codes).
DEFAULT_KEYMAP_NAMES: dict[str, list[str]] = {
    "PageButton1": ["1"],
    "PageButton2": ["2"],
    "PageButton3": ["3"],
    "PageButton4": ["4"],
    "EncoderLeft":    ["up"],
    "EncoderRight":   ["down"],
    "Confirm":        ["return"],
    "Back":           ["backspace"],
}

SERVER_DEFAULT_HOST: str = "127.0.0.1"
SERVER_DEFAULT_PORT: int = 28080

DEFAULT_CONFIG_FILENAME = "companion_app.config.json"


class ConfigError(Exception):
    """Raised for any unrecoverable config problem at startup."""


@dataclass
class Config:
    display_scale: float = DEFAULT_DISPLAY_SCALE
    display_crt_overlay: bool = DEFAULT_DISPLAY_CRT_OVERLAY
    display_power_on_effect: bool = DEFAULT_DISPLAY_POWER_ON_EFFECT
    display_vertical_sweep: bool = DEFAULT_DISPLAY_VERTICAL_SWEEP
    display_vignette: bool = DEFAULT_DISPLAY_VIGNETTE
    display_rounded_crt: bool = DEFAULT_DISPLAY_ROUNDED_CRT
    debug_event_log: bool = DEFAULT_DEBUG_EVENT_LOG
    # event name -> list of pygame key codes
    keymap: dict[str, list[int]] = field(default_factory=dict)
    server_host: str = SERVER_DEFAULT_HOST
    server_port: int = SERVER_DEFAULT_PORT
    server_password: str = ""


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


def _require_bool(key: str, value: Any) -> bool:
    # bool is a subclass of int; this is the right place to be strict.
    if not isinstance(value, bool):
        raise ConfigError(f"{key} must be a boolean, got {value!r}")
    return value


def _extract_fields(
    raw: dict[str, Any],
    source: Path | None,
) -> tuple[float, bool, bool, bool, bool, bool, dict[str, list[str]], str, int, str]:
    """Pull only the keys the app honors. Warn on the rest."""
    scale: float = DEFAULT_DISPLAY_SCALE
    crt_overlay: bool = DEFAULT_DISPLAY_CRT_OVERLAY
    power_on_effect: bool = DEFAULT_DISPLAY_POWER_ON_EFFECT
    vertical_sweep: bool = DEFAULT_DISPLAY_VERTICAL_SWEEP
    vignette: bool = DEFAULT_DISPLAY_VIGNETTE
    rounded_crt: bool = DEFAULT_DISPLAY_ROUNDED_CRT
    debug_event_log: bool = DEFAULT_DEBUG_EVENT_LOG
    keymap_names: dict[str, Any] | None = None
    server_host: str = SERVER_DEFAULT_HOST
    server_port: int = SERVER_DEFAULT_PORT
    server_password: str | None = None

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
                elif k == "crtOverlay":
                    crt_overlay = _require_bool("display.crtOverlay", v)
                elif k == "powerOnEffect":
                    power_on_effect = _require_bool("display.powerOnEffect", v)
                elif k == "verticalSweep":
                    vertical_sweep = _require_bool("display.verticalSweep", v)
                elif k == "vignette":
                    vignette = _require_bool("display.vignette", v)
                elif k == "roundedCrt":
                    rounded_crt = _require_bool("display.roundedCrt", v)
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
        elif top_key == "debug":
            if not isinstance(top_value, dict):
                raise ConfigError("debug section must be an object")
            for k, v in top_value.items():
                if k == "eventLog":
                    debug_event_log = _require_bool("debug.eventLog", v)
                else:
                    _warn(f"ignoring unknown config key debug.{k}")
        elif top_key == "server":
            if not isinstance(top_value, dict):
                raise ConfigError("server section must be an object")
            for k, v in top_value.items():
                if k == "host":
                    if not isinstance(v, str) or not v:
                        raise ConfigError(
                            f"server.host must be a non-empty string, got {v!r}"
                        )
                    server_host = v
                elif k == "port":
                    if isinstance(v, bool) or not isinstance(v, int):
                        raise ConfigError(
                            f"server.port must be an integer, got {v!r}"
                        )
                    if v < 1 or v > 65535:
                        raise ConfigError(
                            f"server.port must be between 1 and 65535, got {v}"
                        )
                    server_port = v
                elif k == "password":
                    if not isinstance(v, str) or not v:
                        raise ConfigError(
                            f"server.password must be a non-empty string, got {v!r}"
                        )
                    server_password = v
                else:
                    _warn(f"ignoring unknown config key server.{k}")
        else:
            _warn(f"ignoring unknown config key {top_key}")

    if server_password is None:
        raise ConfigError(
            "server.password is required (set it in the config file)"
        )

    resolved_names = _merge_keymap_names(keymap_names, source)
    return (
        scale, crt_overlay, power_on_effect, vertical_sweep,
        vignette, rounded_crt, debug_event_log,
        resolved_names, server_host, server_port, server_password,
    )


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
    (
        scale, crt_overlay, power_on_effect, vertical_sweep,
        vignette, rounded_crt, debug_event_log,
        _names, server_host, server_port, server_password,
    ) = _extract_fields(raw, source)
    return Config(
        display_scale=scale,
        display_crt_overlay=crt_overlay,
        display_power_on_effect=power_on_effect,
        display_vertical_sweep=vertical_sweep,
        display_vignette=vignette,
        display_rounded_crt=rounded_crt,
        debug_event_log=debug_event_log,
        keymap={},
        server_host=server_host,
        server_port=server_port,
        server_password=server_password,
    )


def load_and_resolve_config(path: str | None) -> Config:
    """Two-stage load: parse JSON first (may raise pre-pygame), then
    initialize pygame and resolve key names to codes.

    This is the entry point `app.main()` uses. It guarantees malformed
    JSON aborts before pygame is initialized.
    """
    raw, source = _load_raw(path)
    (
        scale, crt_overlay, power_on_effect, vertical_sweep,
        vignette, rounded_crt, debug_event_log,
        keymap_names, server_host, server_port, server_password,
    ) = _extract_fields(raw, source)

    # pygame must be initialized before key_code lookups.
    import pygame
    if not pygame.get_init():
        pygame.init()

    resolved = _resolve_key_codes(keymap_names)
    return Config(
        display_scale=scale,
        display_crt_overlay=crt_overlay,
        display_power_on_effect=power_on_effect,
        display_vertical_sweep=vertical_sweep,
        display_vignette=vignette,
        display_rounded_crt=rounded_crt,
        debug_event_log=debug_event_log,
        keymap=resolved,
        server_host=server_host,
        server_port=server_port,
        server_password=server_password,
    )
