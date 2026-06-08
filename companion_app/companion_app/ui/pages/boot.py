"""Startup boot page and transition timeline for the companion app."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pygame

from companion_app.debug.console import TypewriterConsole
from companion_app.render import background

BOOT_CURSOR_HOLD_MS: int = 3000
REDIRECT_HOLD_MS: int = 1200
BOOT_TRANSCRIPT: tuple[str, ...] = (
    'ROBCO TERM BIOS V1.3',
    'PIP-BOY 2000 MK I.....OK',
    'CRT MATRIX............OK',
    'MEMORY BANKS..........64K',
    'LINK INTERFACE........READY',
)
REDIRECT_LINE = 'REDIRECTING TO STATUS PAGE'

_BOOT_MARGIN_X = 36
_BOOT_MARGIN_TOP = 64
_BOOT_MARGIN_BOTTOM = 56


class BootPhase(Enum):
    BOOTING = auto()
    CLEARING = auto()
    CONNECTING = auto()
    REDIRECTING = auto()
    COMPLETE = auto()


@dataclass(frozen=True)
class BootTickResult:
    start_connect: bool = False
    show_main_ui: bool = False
    clear_console: bool = False
    log_redirect: bool = False


@dataclass
class BootSequence:
    phase: BootPhase = BootPhase.BOOTING
    _boot_started: bool = False
    _phase_elapsed_ms: int = 0

    def begin(self, console: TypewriterConsole) -> None:
        if self._boot_started:
            return
        self._boot_started = True
        for line in BOOT_TRANSCRIPT:
            console.log(line)

    def tick(self, dt_ms: int, console: TypewriterConsole) -> BootTickResult:
        dt_ms = max(0, dt_ms)

        if self.phase is BootPhase.BOOTING:
            if console.is_idle():
                self.phase = BootPhase.CLEARING
                self._phase_elapsed_ms = 0
                console.clear()
                console.show_idle_cursor = True
                return BootTickResult(clear_console=True)
            return BootTickResult()

        self._phase_elapsed_ms += dt_ms

        if self.phase is BootPhase.CLEARING:
            if self._phase_elapsed_ms < BOOT_CURSOR_HOLD_MS:
                return BootTickResult()
            self.phase = BootPhase.CONNECTING
            self._phase_elapsed_ms = 0
            console.show_idle_cursor = False
            return BootTickResult(start_connect=True)

        if self.phase is BootPhase.CONNECTING:
            if not console.is_idle():
                return BootTickResult()
            self.phase = BootPhase.REDIRECTING
            self._phase_elapsed_ms = 0
            return BootTickResult(log_redirect=True)

        if self.phase is BootPhase.REDIRECTING:
            if not console.is_idle():
                return BootTickResult()
            if self._phase_elapsed_ms < REDIRECT_HOLD_MS:
                return BootTickResult()
            self.phase = BootPhase.COMPLETE
            return BootTickResult(show_main_ui=True)

        return BootTickResult()

    @property
    def show_main_ui(self) -> bool:
        return self.phase is BootPhase.COMPLETE


class BootPage:
    """Dedicated startup page with a full-screen console layout."""

    def __init__(self, virtual_size: tuple[int, int]) -> None:
        width, height = virtual_size
        self._console_rect = pygame.Rect(
            _BOOT_MARGIN_X,
            _BOOT_MARGIN_TOP,
            width - (_BOOT_MARGIN_X * 2),
            height - _BOOT_MARGIN_TOP - _BOOT_MARGIN_BOTTOM,
        )

    @property
    def console_rect(self) -> pygame.Rect:
        return self._console_rect.copy()

    def render(self, surface: pygame.Surface) -> None:
        background.fill_background(surface)
