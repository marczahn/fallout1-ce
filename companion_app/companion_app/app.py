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
from companion_app.render.crt import (
    RoundedCornerOverlay,
    ScanlineOverlay,
    VignetteOverlay,
)
from companion_app.render.font import FontLoadError, load_font
from companion_app.ui.shell import BODY_SIZE, HEADER_SIZE, draw_shell

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

    # Preload the Fallout webfont at the sizes the shell uses, so a
    # missing/unreadable asset aborts here (caught by main()) instead
    # of mid-frame inside the main loop.
    load_font(HEADER_SIZE)
    load_font(BODY_SIZE)

    keyboard = KeyboardInput(config.keymap)

    vignette: VignetteOverlay | None = None
    if config.display_vignette:
        vignette = VignetteOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    scanlines: ScanlineOverlay | None = None
    if config.display_crt_overlay:
        scanlines = ScanlineOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    rounded_crt: RoundedCornerOverlay | None = None
    if config.display_rounded_crt:
        rounded_crt = RoundedCornerOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    debug_overlay: EventLogOverlay | None = None
    if config.debug_event_log:
        debug_overlay = EventLogOverlay()

    running = True
    while running:
        pygame_events = pygame.event.get()
        for event in pygame_events:
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False

        input_events = keyboard.poll(pygame_events)
        if debug_overlay is not None:
            for input_event in input_events:
                debug_overlay.record(input_event)

        draw_shell(virtual, SECTION_NAME, CONNECTION_STATUS, BODY_PLACEHOLDER)
        if vignette is not None:
            vignette.draw(virtual)
        if scanlines is not None:
            scanlines.draw(virtual)
        if rounded_crt is not None:
            rounded_crt.draw(virtual)
        if debug_overlay is not None:
            debug_overlay.draw(virtual)

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

    try:
        return _run_loop(config)
    except FontLoadError as e:
        # Per M2 Resolved Decision 12 + acceptance criterion 9: missing
        # font asset aborts with a one-line message and a non-zero exit,
        # with pygame shut down cleanly.
        import pygame
        if pygame.get_init():
            pygame.quit()
        print(f"companion_app: font error: {e}", file=sys.stderr)
        return 3
