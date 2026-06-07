"""Companion app entry point.

Owns the pygame main loop, the virtual surface, the quit handling,
and (M2) the per-frame call into the screen shell.
"""
from __future__ import annotations

import argparse
import sys

from companion_app.config import (
    Config,
    ConfigError,
    load_and_resolve_config,
)
from companion_app.debug.event_log import EventLogOverlay
from companion_app.input.keyboard import KeyboardInput
from companion_app.ui.shell import draw_shell

VIRTUAL_WIDTH = 480
VIRTUAL_HEIGHT = 800
TARGET_FPS = 60

# Static M2 shell strings. M3+ will replace these with live values
# without changing the shell API.
SECTION_NAME = "STATUS"
CONNECTION_STATUS = "--"
BODY_PLACEHOLDER = "PIPBOY 2000"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="companion_app")
    parser.add_argument(
        "--config",
        dest="config",
        default=None,
        help="Path to a JSON config file. Overrides ./companion_app.config.json.",
    )
    return parser.parse_args(argv)


def _run_loop(config: Config) -> int:
    import pygame

    # pygame is already initialized by load_and_resolve_config().
    pygame.key.set_repeat(0)

    scale = config.display_scale
    window_size = (
        max(1, int(VIRTUAL_WIDTH * scale)),
        max(1, int(VIRTUAL_HEIGHT * scale)),
    )
    window = pygame.display.set_mode(window_size)
    pygame.display.set_caption("Fallout CE Companion")

    virtual = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
    clock = pygame.time.Clock()

    pygame.font.init()
    keyboard = KeyboardInput(config.keymap)
    overlay = EventLogOverlay()

    running = True
    while running:
        pygame_events = pygame.event.get()
        for event in pygame_events:
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        for input_event in keyboard.poll(pygame_events):
            overlay.record(input_event)

        draw_shell(virtual, SECTION_NAME, CONNECTION_STATUS, BODY_PLACEHOLDER)
        overlay.draw(virtual)

        if window_size == (VIRTUAL_WIDTH, VIRTUAL_HEIGHT):
            window.blit(virtual, (0, 0))
        else:
            pygame.transform.scale(virtual, window_size, window)

        pygame.display.flip()
        clock.tick(TARGET_FPS)

    pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        config = load_and_resolve_config(args.config)
    except ConfigError as e:
        print(f"companion_app: config error: {e}", file=sys.stderr)
        return 2

    return _run_loop(config)
