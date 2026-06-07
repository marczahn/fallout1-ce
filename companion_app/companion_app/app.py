"""Companion app entry point.

Owns the pygame main loop, the virtual surface, the quit handling,
the per-frame call into the screen shell (M2), network client (M3),
and section routing (M4+).
"""
from __future__ import annotations

import argparse
from enum import Enum
import sys

from companion_app.config import (
    Config,
    ConfigError,
    load_and_resolve_config,
)
from companion_app.debug.console import TypewriterConsole
from companion_app.debug.event_log import EventLogOverlay
from companion_app.input.keyboard import KeyboardInput
from companion_app.net import NetworkClient
from companion_app.render.crt import (
    RoundedCornerOverlay,
    ScanlineOverlay,
    VignetteOverlay,
)
from companion_app.render.font import FontLoadError, load_font
from companion_app.state import AppState, ConnectionState
from companion_app.ui.shell import BODY_SIZE, HEADER_SIZE, draw_shell
from companion_app.ui.status import draw_status

VIRTUAL_WIDTH = 480
VIRTUAL_HEIGHT = 800
TARGET_FPS = 60


class Section(Enum):
    STATUS = 1
    DATA = 2
    INVENTORY = 3
    MAP = 4


def _connection_status(state: AppState) -> str:
    """Map the current app state to a short header status string."""
    if state.connection is ConnectionState.READY:
        return "OK" if state.player.available else "NO SIGNAL"
    if state.connection is ConnectionState.RECONNECTING:
        return "RECONNECTING"
    if state.connection is not ConnectionState.DISCONNECTED:
        return "CONNECTING"
    return "--"


def _body_text(state: AppState) -> str:
    """Return the body placeholder text for the current connection state.

    When the connection is READY and a player is available, returns an
    empty string so the active section can draw its own content (M4+).
    """
    if state.connection is not ConnectionState.READY:
        return "CONNECTING\u2026"
    if not state.player.available:
        return "NO SIGNAL"
    return ""


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

    # Preload the Fallout webfont at all sizes used by the shell and
    # sections, so a missing/unreadable asset aborts here (caught by
    # main()) instead of mid-frame inside the main loop.
    load_font(HEADER_SIZE)
    load_font(BODY_SIZE)
    load_font(28)
    load_font(48)

    keyboard = KeyboardInput(config.keymap)

    state = AppState()

    typewriter = TypewriterConsole()
    typewriter.log("companion app starting")
    typewriter.log(f"server: {config.server_host}:{config.server_port}")

    net = NetworkClient(
        host=config.server_host,
        port=config.server_port,
        password=config.server_password,
        state=state,
        log_fn=typewriter.log,
    )

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

    current_section: Section = Section.STATUS

    running = True
    while running:
        pygame_events = pygame.event.get()
        for event in pygame_events:
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_ESCAPE, pygame.K_q):
                    running = False
                elif event.key == pygame.K_TAB:
                    typewriter.visible = not typewriter.visible

        input_events = keyboard.poll(pygame_events)
        for input_event in input_events:
            if debug_overlay is not None:
                debug_overlay.record(input_event)
            if hasattr(input_event, "index"):
                current_section = Section(input_event.index)

        net.poll()
        typewriter.tick()
        status = _connection_status(state)
        body = _body_text(state)
        section_name = current_section.name

        draw_shell(virtual, section_name, status, body)
        if state.connection is ConnectionState.READY and state.player.available:
            if current_section is Section.STATUS:
                draw_status(
                    virtual,
                    player_available=state.player.available,
                    hp=state.player.hp,
                    max_hp=state.player.max_hp,
                )
        if vignette is not None:
            vignette.draw(virtual)
        if scanlines is not None:
            scanlines.draw(virtual)
        if rounded_crt is not None:
            rounded_crt.draw(virtual)
        if debug_overlay is not None:
            debug_overlay.draw(virtual)
        typewriter.draw(virtual)

        if window_size == (VIRTUAL_WIDTH, VIRTUAL_HEIGHT):
            window.blit(virtual, (0, 0))
        else:
            pygame.transform.scale(virtual, window_size, window)

        pygame.display.flip()
        clock.tick(TARGET_FPS)

    net.cleanup()
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
