"""Companion app entry point.

Owns the pygame main loop, the virtual surface, the quit handling,
the per-frame call into the screen layout (UI refactoring), network
client (M3), and page dispatch (STATUS placeholder in M4; full
navigation shell in M5).
"""
from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING

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
    PowerOnEffect,
    RoundedCornerOverlay,
    ScanlineOverlay,
    VerticalSweepOverlay,
    VignetteOverlay,
)
from companion_app.render.font import FontLoadError, load_font
from companion_app.state import AppState, ConnectionState
from companion_app.ui.layout import Layout
from companion_app.ui.pages import Page, SectionRenderer
from companion_app.ui.pages import StartupPage, VisiblePage
from companion_app.ui.pages.boot import (
    BOOT_CONSOLE_MAX_LINES,
    BootPage,
    BootSequence,
    SplashPage,
)
from companion_app.ui.pages.archives import ArchivesSection
from companion_app.ui.pages.automaps import AutomapsSection
from companion_app.ui import (
    inventory_list,
    item_actions,
    quest_list,
    sections,
    segmented_header,
)
from companion_app.ui.scroll_list import ListRow
from companion_app.ui.sections import (
    ARCHIVES_QUESTS,
    SECTION_TITLES,
    STATUS_INVENTORY,
    SectionsUiState,
)
from companion_app.ui.segmented_header import SUBHEADER_SIZE
from companion_app.ui.pages.status import (
    STATUS_BOX_SIZE,
    STATUS_HP_CHEVRON_SIZE,
    STATUS_HP_LABEL_SIZE,
    STATUS_HP_VALUE_SIZE,
    STATUS_ROW_SIZE,
    STATUS_SECTION_SIZE,
    STATUS_SPECIAL_SIZE,
    StatusSection,
)
from companion_app.ui.shell import BODY_SIZE, HEADER_SIZE, STATUS_SIZE

if TYPE_CHECKING:
    import pygame

VIRTUAL_WIDTH = 480
VIRTUAL_HEIGHT = 800
TARGET_FPS = 60


def _body_text(state: AppState) -> str:
    if state.connection is not ConnectionState.READY:
        return 'CONNECTING…'
    if not state.player.available:
        return 'NO SIGNAL'
    return ''


def _active_rows(
    current_page: Page,
    sections_ui: SectionsUiState,
    state: AppState,
) -> tuple[ListRow, ...]:
    """Content rows for the active sub-section, or empty if it has none.

    Derived per call rather than stored: the network client replaces
    ``player.inventory`` and ``player.quests`` wholesale on every update, so
    cached rows would need invalidating on each one. Only the cursor and the
    drill-down depth are state.

    For a drillable sub-section this returns the rows of **whichever level
    is showing**, so ``handle_input``'s wrap-around and ``resolve_cursor``
    work per level with no extra state.
    """
    seg = sections.for_page(sections_ui, current_page)
    if current_page is Page.STATUS and seg.selected_key == STATUS_INVENTORY:
        return inventory_list.build_rows(state.player.inventory)
    if current_page is Page.ARCHIVES and seg.selected_key == ARCHIVES_QUESTS:
        quests = state.player.quests
        if sections_ui.quest_location_key == "":
            return quest_list.build_location_rows(quests)
        location_index = quest_list.location_index_from_key(
            sections_ui.quest_location_key
        )
        if location_index is None:
            # A depth key that no longer decodes — only reachable if the
            # stored key were corrupted. Fall back to level 1 rather than
            # raising: the screen pops up a level instead of crashing.
            return quest_list.build_location_rows(quests)
        return quest_list.build_quest_rows(quests, location_index)
    return ()


def _selected_inventory_item(sections_ui: SectionsUiState, state: AppState):
    """The currently focused inventory object, if the list owns focus."""
    if not sections_ui.activated:
        return None
    return inventory_list.item_for_key(
        state.player.inventory, sections_ui.inventory_cursor.selected_key
    )


def _route_input(
    current_page: Page,
    sections_ui: SectionsUiState,
    input_event: InputEvent,
    state: AppState,
) -> tuple[Page, SectionsUiState]:
    """Route one input event to the section model.

    Section buttons switch sections and preserve every sub-section
    selection and the content cursor (TASK-010's MAP behavior, generalized
    in TASK-017). The one thing they reset is **activation**: leaving a
    section always hands the encoder back to the sub-section row.
    """
    if isinstance(input_event, PageButtonEvent):
        try:
            target_page = Page(input_event.index)
        except ValueError:
            # Index 4 is the device's close/shutdown button, not a section
            # (its action is out of scope). Catching ValueError rather than
            # testing for 4 keeps any future index inert too.
            return current_page, sections_ui
        return target_page, sections.deactivated(sections_ui)

    return current_page, sections.handle_input(
        sections_ui,
        current_page,
        input_event,
        rows=_active_rows(current_page, sections_ui, state),
    )


def _render_section(
    surface: "pygame.Surface",
    layout: Layout,
    current_page: Page,
    sections_ui: SectionsUiState,
    state: AppState,
    body: str,
    section_renderers: dict[Page, SectionRenderer],
) -> None:
    """Draw one frame of the main UI.

    Every section renders the same structure — shared header, segmented
    sub-header, content — and the sub-header is drawn here rather than by
    each section so the geometry cannot drift between them.

    When ``body`` is non-empty (``CONNECTING…`` / ``NO SIGNAL``) it
    replaces the whole section, sub-header included. That matches the
    behavior before TASK-017, where the sub-header was drawn by the page
    renderer and so never appeared on the disconnected screen.
    """
    layout.draw(surface, SECTION_TITLES[current_page])
    if body:
        layout.draw_placeholder(surface, body)
        return

    content_rect = layout.content_rect
    seg = sections.for_page(sections_ui, current_page)
    # The solid inverse fill always marks whatever the encoder currently
    # drives: the sub-header segment when at the sub-section row, the
    # content's selected row once activated. Exactly one filled element on
    # screen, which is the whole focus indicator — no breadcrumb needed.
    segmented_header.render(
        surface, content_rect, seg, focused=not sections_ui.activated
    )
    section_renderers[current_page].render(
        surface,
        content_rect,
        state,
        seg.selected_key,
        sections.focus_for(sections_ui, current_page, seg.selected_key),
    )


def _visible_page(
    boot_sequence: BootSequence,
    current_page: Page,
) -> VisiblePage:
    if boot_sequence.show_main_ui:
        return current_page
    if boot_sequence.show_boot_console:
        return StartupPage.BOOT
    return StartupPage.SPLASH


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


def _handle_tab_key(
    boot_sequence: BootSequence,
    typewriter: TypewriterConsole,
    *,
    config: Config,
    state: AppState,
    net: NetworkClient | None,
) -> NetworkClient | None:
    if boot_sequence.show_main_ui:
        typewriter.visible = not typewriter.visible
        return net

    boot_tick = boot_sequence.skip(typewriter)
    if boot_tick.start_connect and net is None:
        return _start_network_client(config, state, typewriter)
    return net


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
        STATUS_HP_CHEVRON_SIZE,
        STATUS_HP_VALUE_SIZE,
        STATUS_BOX_SIZE,
        STATUS_ROW_SIZE,
        STATUS_SECTION_SIZE,
        STATUS_SPECIAL_SIZE,
        SUBHEADER_SIZE,
        CONSOLE_FONT_SIZE,
    }:
        load_font(size)

    keyboard = KeyboardInput(config.keymap)
    state = AppState()
    typewriter = TypewriterConsole(max_lines=BOOT_CONSOLE_MAX_LINES)
    boot_sequence = BootSequence()
    net: NetworkClient | None = None

    vignette: VignetteOverlay | None = None
    if config.display_vignette:
        vignette = VignetteOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    scanlines: ScanlineOverlay | None = None
    if config.display_crt_overlay:
        scanlines = ScanlineOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    power_on_effect: PowerOnEffect | None = None
    if config.display_crt_overlay and config.display_power_on_effect:
        power_on_effect = PowerOnEffect((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    vertical_sweep: VerticalSweepOverlay | None = None
    if config.display_crt_overlay and config.display_vertical_sweep:
        vertical_sweep = VerticalSweepOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    rounded_crt: RoundedCornerOverlay | None = None
    if config.display_rounded_crt:
        rounded_crt = RoundedCornerOverlay((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    debug_overlay: EventLogOverlay | None = None
    if config.debug_event_log:
        debug_overlay = EventLogOverlay()

    layout = Layout((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))
    splash_page = SplashPage()
    boot_page = BootPage((VIRTUAL_WIDTH, VIRTUAL_HEIGHT))

    status_section = StatusSection()
    automaps_section = AutomapsSection(
        green_levels=config.map_green_levels,
        pixel_blocks=config.map_pixel_blocks,
    )
    archives_section = ArchivesSection()
    section_renderers = {
        Page.STATUS: status_section,
        Page.AUTOMAPS: automaps_section,
        Page.ARCHIVES: archives_section,
    }

    current_page: Page = Page.STATUS
    sections_ui = sections.default_sections_ui()
    item_modal = item_actions.ModalState()
    visible_page: VisiblePage = StartupPage.SPLASH

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
                    net = _handle_tab_key(
                        boot_sequence,
                        typewriter,
                        config=config,
                        state=state,
                        net=net,
                    )

        input_events = keyboard.poll(pygame_events)
        if boot_sequence.show_main_ui:
            for input_event in input_events:
                if debug_overlay is not None:
                    debug_overlay.record(input_event)
                if item_modal.open:
                    item = _selected_inventory_item(sections_ui, state)
                    actions = item_actions.actions_for(item)
                    if item is None or not actions:
                        item_modal = item_actions.ModalState()
                    elif item_modal.pending:
                        continue
                    elif isinstance(input_event, BackEvent):
                        item_modal = item_actions.ModalState()
                    elif isinstance(input_event, EncoderLeftEvent):
                        item_modal = item_actions.move(item_modal, len(actions), -1)
                    elif isinstance(input_event, EncoderRightEvent):
                        item_modal = item_actions.move(item_modal, len(actions), 1)
                    elif isinstance(input_event, ConfirmEvent):
                        action = actions[item_modal.index]
                        if action.command == "cancel":
                            item_modal = item_actions.ModalState()
                        elif net is not None and net.send_inventory_action(
                            item.object_id, action.command
                        ):
                            item_modal = item_actions.ModalState(
                                open=True,
                                index=item_modal.index,
                                pending=True,
                            )
                    continue

                if (
                    isinstance(input_event, ConfirmEvent)
                    and current_page is Page.STATUS
                    and sections.for_page(sections_ui, current_page).selected_key == STATUS_INVENTORY
                    and sections_ui.activated
                ):
                    item = _selected_inventory_item(sections_ui, state)
                    if item_actions.actions_for(item):
                        item_modal = item_actions.ModalState(open=True)
                        state.command_error = ""
                        continue
                current_page, sections_ui = _route_input(
                    current_page, sections_ui, input_event, state
                )
        elif debug_overlay is not None:
            for input_event in input_events:
                debug_overlay.record(input_event)

        if net is not None:
            net.poll()
        if item_modal.pending and not state.command_pending:
            if state.command_error:
                item_modal = item_actions.ModalState(open=True, index=item_modal.index)
            else:
                item_modal = item_actions.ModalState()
        typewriter.tick(dt_ms)
        boot_tick = boot_sequence.tick(
            dt_ms,
            typewriter,
            connection_ready=state.connection is ConnectionState.READY,
        )
        if boot_tick.start_connect and net is None:
            net = _start_network_client(config, state, typewriter)

        body = _body_text(state)
        next_visible_page = _visible_page(boot_sequence, current_page)
        if vertical_sweep is not None:
            if next_visible_page != visible_page:
                vertical_sweep.reset()
            else:
                vertical_sweep.tick(dt_ms)
        visible_page = next_visible_page

        if boot_sequence.show_main_ui:
            _render_section(
                virtual,
                layout,
                current_page,
                sections_ui,
                state,
                body,
                section_renderers,
            )
            if item_modal.open:
                item = _selected_inventory_item(sections_ui, state)
                if item is not None:
                    item_actions.render(
                        virtual,
                        layout.content_rect,
                        item,
                        item_modal,
                        state.command_error,
                    )
        elif boot_sequence.show_boot_console:
            boot_page.render(virtual)
            typewriter.draw(virtual, boot_page.console_rect)
        else:
            splash_page.render(virtual)

        if (
            power_on_effect is not None
            and not boot_sequence.show_main_ui
            and not power_on_effect.is_complete
        ):
            power_on_effect.apply(virtual)
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
        if power_on_effect is not None and not power_on_effect.is_complete:
            power_on_effect.tick(dt_ms)

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
