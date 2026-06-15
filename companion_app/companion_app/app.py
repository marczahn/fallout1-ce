"""Companion app entry point.

Owns the pygame main loop, the virtual surface, the quit handling,
the per-frame call into the screen layout (UI refactoring), network
client (M3), and page dispatch (STATUS placeholder in M4; full
navigation shell in M5).
"""
from __future__ import annotations

import argparse
import sys

from companion_app.config import (
    Config,
    ConfigError,
    load_and_resolve_config,
)
from companion_app.ui.console import CONSOLE_FONT_SIZE, TypewriterConsole
from companion_app.debug.event_log import EventLogOverlay
from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    InputEvent,
    PageButtonEvent,
)
from companion_app.input.keyboard import KeyboardInput
from companion_app.net import NetworkClient
from companion_app.render.crt import (
    RoundedCornerOverlay,
    ScanlineOverlay,
    VerticalSweepOverlay,
    VignetteOverlay,
)
from companion_app.render.font import FontLoadError, load_font
from companion_app.state import AppState, ConnectionState
from companion_app.ui.layout import Layout
from companion_app.ui.pages import Page
from companion_app.ui.pages.boot import BOOT_CONSOLE_MAX_LINES, BootPage, BootSequence
from companion_app.ui.pages.data import (
    DataPage,
    DataPageUiState,
    enter_selected_tab,
    move_selection_left,
    move_selection_right,
    return_to_root,
)
from companion_app.ui.pages.inventory import InventoryPage
from companion_app.ui.pages.map import MapPage
from companion_app.ui.pages.status import (
    STATUS_HP_LABEL_SIZE,
    STATUS_HP_VALUE_SIZE,
    StatusPage,
)
from companion_app.ui.shell import BODY_SIZE, HEADER_SIZE, STATUS_SIZE

VIRTUAL_WIDTH = 480
VIRTUAL_HEIGHT = 800
TARGET_FPS = 60


def _connection_status(state: AppState) -> str:
    if state.connection is ConnectionState.READY:
        return 'OK' if state.player.available else 'NO SIGNAL'
    if state.connection is ConnectionState.RECONNECTING:
        return 'RECONNECTING'
    if state.connection is not ConnectionState.DISCONNECTED:
        return 'CONNECTING'
    return '--'


def _body_text(state: AppState) -> str:
    if state.connection is not ConnectionState.READY:
        return 'CONNECTING…'
    if not state.player.available:
        return 'NO SIGNAL'
    return ''


def _handle_data_input(
    ui_state: DataPageUiState,
    input_event: InputEvent,
) -> DataPageUiState:
    if isinstance(input_event, EncoderLeftEvent):
        return move_selection_left(ui_state)
    if isinstance(input_event, EncoderRightEvent):
        return move_selection_right(ui_state)
    if isinstance(input_event, ConfirmEvent):
        return enter_selected_tab(ui_state)
    if isinstance(input_event, BackEvent):
        return return_to_root(ui_state)
    return ui_state


def _route_input(
    current_page: Page,
    data_ui: DataPageUiState,
    input_event: InputEvent,
) -> tuple[Page, DataPageUiState]:
    if isinstance(input_event, PageButtonEvent):
        target_page = Page(input_event.index)
        if target_page is Page.DATA:
            return target_page, DataPageUiState()
        return target_page, data_ui

    if current_page is Page.DATA:
        return current_page, _handle_data_input(data_ui, input_event)

    return current_page, data_ui


def _start_network_client(
    config: Config,
    state: AppState,
    typewriter: TypewriterConsole,
) -> NetworkClient:
    typewriter.log('UPLINK TARGET.........%s:%s' % (config.server_host, config.server_port))
    typewriter.log('')
    typewriter.log('')
    typewriter.show_idle_cursor = True
    return NetworkClient(
        host=config.server_host,
        port=config.server_port,
        password=config.server_password,
        state=state,
        log_fn=typewriter.log,
    )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='companion_app')
    parser.add_argument(
        '--config',
        dest='config',
        default=None,
        help='Path to a JSON config file. Overrides ./companion_app.config.json.',
    )
    return parser.parse_args(argv)


def _run_loop(config: Config) -> int:
    import pygame

    pygame.key.set_repeat(0)

    scale = config.display_scale
    window_size = (
        max(1, int(VIRTUAL_WIDTH * scale)),
        max(1, int(VIRTUAL_HEIGHT * scale)),
    )
    window = pygame.display.set_mode(window_size)
    pygame.display.set_caption('Fallout CE Companion')

    virtual = pygame.Surface((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
    clock = pygame.time.Clock()

    pygame.font.init()

    for size in {
        HEADER_SIZE,
        BODY_SIZE,
        STATUS_SIZE,
        STATUS_HP_LABEL_SIZE,
        STATUS_HP_VALUE_SIZE,
        CONSOLE_FONT_SIZE,
    }:
        load_font(size)

    keyboard = KeyboardInput(config.keymap)
    state = AppState()
    typewriter = TypewriterConsole(max_lines=BOOT_CONSOLE_MAX_LINES)
    boot_sequence = BootSequence()
    boot_sequence.begin(typewriter)
    net: NetworkClient | None = None

    vignette: VignetteOverlay | None = None
    if config.display_vignette:
        vignette = VignetteOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    scanlines: ScanlineOverlay | None = None
    if config.display_crt_overlay:
        scanlines = ScanlineOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    vertical_sweep: VerticalSweepOverlay | None = None
    if config.display_crt_overlay and config.display_vertical_sweep:
        vertical_sweep = VerticalSweepOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    rounded_crt: RoundedCornerOverlay | None = None
    if config.display_rounded_crt:
        rounded_crt = RoundedCornerOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    debug_overlay: EventLogOverlay | None = None
    if config.debug_event_log:
        debug_overlay = EventLogOverlay()

    boot_page = BootPage((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
    layout = Layout((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    status_page = StatusPage()
    data_page = DataPage()
    inventory_page = InventoryPage()
    map_page = MapPage()

    current_page: Page = Page.STATUS
    data_ui = DataPageUiState()

    running = True
    while running:
        dt_ms = clock.tick(TARGET_FPS)
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
        if boot_sequence.show_main_ui:
            for input_event in input_events:
                if debug_overlay is not None:
                    debug_overlay.record(input_event)
                current_page, data_ui = _route_input(current_page, data_ui, input_event)
        elif debug_overlay is not None:
            for input_event in input_events:
                debug_overlay.record(input_event)

        if net is not None:
            net.poll()
        typewriter.tick(dt_ms)
        if vertical_sweep is not None:
            vertical_sweep.tick(dt_ms)
        boot_tick = boot_sequence.tick(
            dt_ms,
            typewriter,
            connection_ready=state.connection is ConnectionState.READY,
        )
        if boot_tick.start_connect and net is None:
            net = _start_network_client(config, state, typewriter)

        connection_status = _connection_status(state)
        body = _body_text(state)

        if boot_sequence.show_main_ui:
            layout.draw(virtual, current_page, connection_status)
            if body:
                layout.draw_placeholder(virtual, body)
            elif current_page is Page.STATUS:
                status_page.render(virtual, layout.content_rect, state)
            elif current_page is Page.DATA:
                data_page.render(virtual, layout.content_rect, state, data_ui)
            elif current_page is Page.INVENTORY:
                inventory_page.render(virtual, layout.content_rect, state)
            else:
                map_page.render(virtual, layout.content_rect, state)
        else:
            boot_page.render(virtual)
            typewriter.draw(virtual, boot_page.console_rect)

        if vignette is not None:
            vignette.draw(virtual)
        if scanlines is not None:
            scanlines.draw(virtual)
        if vertical_sweep is not None:
            vertical_sweep.draw(virtual)
        if rounded_crt is not None:
            rounded_crt.draw(virtual)
        if debug_overlay is not None:
            debug_overlay.draw(virtual)

        if window_size == (VIRTUAL_WIDTH, VIRTUAL_HEIGHT):
            window.blit(virtual, (0, 0))
        else:
            pygame.transform.scale(virtual, window_size, window)

        pygame.display.flip()

    if net is not None:
        net.cleanup()
    pygame.quit()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    try:
        config = load_and_resolve_config(args.config)
    except ConfigError as e:
        print(f'companion_app: config error: {e}', file=sys.stderr)
        return 2

    try:
        return _run_loop(config)
    except FontLoadError as e:
        import pygame
        if pygame.get_init():
            pygame.quit()
        print(f'companion_app: font error: {e}', file=sys.stderr)
        return 3
