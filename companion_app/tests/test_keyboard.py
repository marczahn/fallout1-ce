"""Unit tests for the keyboard input backend."""
from __future__ import annotations

import unittest


import pygame

from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    PageButtonEvent,
)
from companion_app.input.keyboard import KeyboardInput


def _kd(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYDOWN, key=key)


def _ku(key: int) -> pygame.event.Event:
    return pygame.event.Event(pygame.KEYUP, key=key)


class KeyboardInputTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        pygame.init()

    @classmethod
    def tearDownClass(cls) -> None:
        pygame.quit()

    def test_default_keymap_dispatch(self) -> None:
        keymap = {
            "PageButton1": [pygame.K_1],
            "PageButton2": [pygame.K_2],
            "PageButton3": [pygame.K_3],
            "PageButton4": [pygame.K_4],
            "EncoderLeft":    [pygame.K_UP],
            "EncoderRight":   [pygame.K_DOWN],
            "Confirm":        [pygame.K_RETURN],
            "Back":           [pygame.K_BACKSPACE],
        }
        kb = KeyboardInput(keymap)
        out = kb.poll([
            _kd(pygame.K_1), _kd(pygame.K_2), _kd(pygame.K_3), _kd(pygame.K_4),
            _kd(pygame.K_UP), _kd(pygame.K_DOWN),
            _kd(pygame.K_RETURN), _kd(pygame.K_BACKSPACE),
        ])
        self.assertEqual(
            [type(e).__name__ for e in out],
            [
                "PageButtonEvent", "PageButtonEvent",
                "PageButtonEvent", "PageButtonEvent",
                "EncoderLeftEvent", "EncoderRightEvent",
                "ConfirmEvent", "BackEvent",
            ],
        )
        page_indices = [e.index for e in out if isinstance(e, PageButtonEvent)]
        self.assertEqual(page_indices, [1, 2, 3, 4])

    def test_keyup_is_ignored(self) -> None:
        kb = KeyboardInput({"Confirm": [pygame.K_RETURN]})
        out = kb.poll([_ku(pygame.K_RETURN)])
        self.assertEqual(out, [])

    def test_unmapped_key_is_ignored(self) -> None:
        kb = KeyboardInput({"Confirm": [pygame.K_RETURN]})
        out = kb.poll([_kd(pygame.K_a), _kd(pygame.K_F1)])
        self.assertEqual(out, [])

    def test_mixed_events_preserve_order(self) -> None:
        kb = KeyboardInput({
            "PageButton1": [pygame.K_1],
            "Confirm":     [pygame.K_RETURN],
            "Back":        [pygame.K_BACKSPACE],
        })
        out = kb.poll([
            _kd(pygame.K_RETURN),
            _ku(pygame.K_RETURN),       # ignored
            _kd(pygame.K_a),            # ignored
            _kd(pygame.K_1),
            _kd(pygame.K_BACKSPACE),
        ])
        self.assertEqual(
            [type(e).__name__ for e in out],
            ["ConfirmEvent", "PageButtonEvent", "BackEvent"],
        )
        self.assertEqual(out[1].index, 1)  # type: ignore[union-attr]

    def test_multiple_keys_can_bind_one_event(self) -> None:
        kb = KeyboardInput({"Confirm": [pygame.K_RETURN, pygame.K_SPACE]})
        out = kb.poll([_kd(pygame.K_RETURN), _kd(pygame.K_SPACE)])
        self.assertEqual(len(out), 2)
        self.assertTrue(all(isinstance(e, ConfirmEvent) for e in out))

    def test_empty_input_returns_empty(self) -> None:
        kb = KeyboardInput({"Confirm": [pygame.K_RETURN]})
        self.assertEqual(kb.poll([]), [])

    def test_swapped_encoder_config_inverts_direction(self) -> None:
        # Mirrors the keymap-swapped-encoder example config.
        kb = KeyboardInput({
            "EncoderLeft":  [pygame.K_DOWN],
            "EncoderRight": [pygame.K_UP],
        })
        out = kb.poll([_kd(pygame.K_UP), _kd(pygame.K_DOWN)])
        self.assertIsInstance(out[0], EncoderRightEvent)
        self.assertIsInstance(out[1], EncoderLeftEvent)


if __name__ == "__main__":
    unittest.main()
