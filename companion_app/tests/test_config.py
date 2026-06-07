"""Unit tests for the JSON config loader.

Covers the deterministic logic of `load_and_resolve_config`: defaults,
override merging, unknown-key warnings, and the error paths called
out in the M1-T3 acceptance criteria (malformed JSON, unknown event
name, unknown key name, missing explicit path).
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


import pygame

from companion_app.config import (
    DEFAULT_DISPLAY_SCALE,
    Config,
    ConfigError,
    load_and_resolve_config,
)


class _Tempdir:
    """Context manager that cds into a fresh tempdir for the duration."""

    def __enter__(self) -> Path:
        self._prev_cwd = os.getcwd()
        self._td = tempfile.TemporaryDirectory()
        os.chdir(self._td.name)
        return Path(self._td.name)

    def __exit__(self, *exc) -> None:
        os.chdir(self._prev_cwd)
        self._td.cleanup()


class LoadConfigTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def _write(self, path: Path, data) -> Path:
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_defaults_when_no_file_and_no_path(self) -> None:
        with _Tempdir():
            cfg = load_and_resolve_config(None)
        self.assertIsInstance(cfg, Config)
        self.assertEqual(cfg.display_scale, DEFAULT_DISPLAY_SCALE)
        # All eight events present with at least one resolved key code.
        for name in (
            "SectionButton1", "SectionButton2", "SectionButton3", "SectionButton4",
            "EncoderLeft", "EncoderRight", "Confirm", "Back",
        ):
            self.assertIn(name, cfg.keymap)
            self.assertTrue(all(isinstance(c, int) and c > 0 for c in cfg.keymap[name]))

    def test_cwd_config_file_is_picked_up(self) -> None:
        with _Tempdir() as td:
            self._write(td / "companion_app.config.json", {"display": {"scale": 1.25}})
            cfg = load_and_resolve_config(None)
        self.assertEqual(cfg.display_scale, 1.25)

    def test_explicit_path_overrides_cwd_file(self) -> None:
        with _Tempdir() as td:
            self._write(td / "companion_app.config.json", {"display": {"scale": 1.25}})
            other = self._write(td / "other.json", {"display": {"scale": 2.0}})
            cfg = load_and_resolve_config(str(other))
        self.assertEqual(cfg.display_scale, 2.0)

    def test_explicit_path_missing_is_error(self) -> None:
        with _Tempdir() as td:
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(td / "does-not-exist.json"))
            self.assertIn("not found", str(ctx.exception).lower())

    def test_malformed_json_raises_with_path_in_message(self) -> None:
        with _Tempdir() as td:
            p = td / "bad.json"
            p.write_text("{ this is not json", encoding="utf-8")
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn(str(p), str(ctx.exception))
            self.assertIn("malformed JSON", str(ctx.exception))

    def test_unknown_event_name_aborts(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"input": {"keymap": {"SectionButton5": ["1"]}}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("SectionButton5", str(ctx.exception))

    def test_unknown_key_name_aborts(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"input": {"keymap": {"Confirm": ["not-a-real-key"]}}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("not-a-real-key", str(ctx.exception))

    def test_keymap_must_be_list_of_strings(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"input": {"keymap": {"Confirm": "return"}}})
            with self.assertRaises(ConfigError):
                load_and_resolve_config(str(p))

    def test_negative_or_zero_scale_aborts(self) -> None:
        for bad in (0, -1, -0.5):
            with _Tempdir() as td:
                p = self._write(td / "c.json", {"display": {"scale": bad}})
                with self.assertRaises(ConfigError):
                    load_and_resolve_config(str(p))

    def test_boolean_scale_rejected(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"scale": True}})
            with self.assertRaises(ConfigError):
                load_and_resolve_config(str(p))

    def test_top_level_must_be_object(self) -> None:
        with _Tempdir() as td:
            p = td / "c.json"
            p.write_text("[1, 2, 3]", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_and_resolve_config(str(p))

    def test_unknown_keys_are_ignored(self) -> None:
        # Future-section keys must not crash; loader should warn and ignore.
        with _Tempdir() as td:
            p = self._write(td / "c.json", {
                "server": {"host": "127.0.0.1"},
                "display": {"scale": 1.0},
            })
            cfg = load_and_resolve_config(str(p))
        self.assertEqual(cfg.display_scale, 1.0)

    def test_display_crt_overlay_default_is_true(self) -> None:
        with _Tempdir():
            cfg = load_and_resolve_config(None)
        self.assertTrue(cfg.display_crt_overlay)

    def test_display_crt_overlay_false_honored(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"crtOverlay": False}})
            cfg = load_and_resolve_config(str(p))
        self.assertFalse(cfg.display_crt_overlay)

    def test_display_crt_overlay_must_be_bool(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"crtOverlay": "yes"}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("display.crtOverlay", str(ctx.exception))

    def test_debug_event_log_default_is_false(self) -> None:
        with _Tempdir():
            cfg = load_and_resolve_config(None)
        self.assertFalse(cfg.debug_event_log)

    def test_debug_event_log_true_honored(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"debug": {"eventLog": True}})
            cfg = load_and_resolve_config(str(p))
        self.assertTrue(cfg.debug_event_log)

    def test_debug_event_log_must_be_bool(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"debug": {"eventLog": 1}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("debug.eventLog", str(ctx.exception))

    def test_unknown_debug_key_warns_and_ignored(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"debug": {"someFutureFlag": True}})
            cfg = load_and_resolve_config(str(p))
        self.assertFalse(cfg.debug_event_log)

    def test_debug_section_must_be_object(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"debug": "on"})
            with self.assertRaises(ConfigError):
                load_and_resolve_config(str(p))

    def test_partial_keymap_merges_with_defaults(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"input": {"keymap": {"Confirm": ["space"]}}})
            cfg = load_and_resolve_config(str(p))
        # Override applied:
        self.assertEqual(cfg.keymap["Confirm"], [pygame.K_SPACE])
        # Other defaults still present:
        self.assertEqual(cfg.keymap["SectionButton1"], [pygame.K_1])
        self.assertEqual(cfg.keymap["EncoderLeft"], [pygame.K_UP])

    def test_display_vignette_default_is_true(self) -> None:
        with _Tempdir():
            cfg = load_and_resolve_config(None)
        self.assertTrue(cfg.display_vignette)

    def test_display_vignette_false_honored(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"vignette": False}})
            cfg = load_and_resolve_config(str(p))
        self.assertFalse(cfg.display_vignette)

    def test_display_vignette_must_be_bool(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"vignette": 1}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("display.vignette", str(ctx.exception))

    def test_display_rounded_crt_default_is_true(self) -> None:
        with _Tempdir():
            cfg = load_and_resolve_config(None)
        self.assertTrue(cfg.display_rounded_crt)

    def test_display_rounded_crt_false_honored(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"roundedCrt": False}})
            cfg = load_and_resolve_config(str(p))
        self.assertFalse(cfg.display_rounded_crt)

    def test_display_rounded_crt_must_be_bool(self) -> None:
        with _Tempdir() as td:
            p = self._write(td / "c.json", {"display": {"roundedCrt": "no"}})
            with self.assertRaises(ConfigError) as ctx:
                load_and_resolve_config(str(p))
            self.assertIn("display.roundedCrt", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
