"""Startup boot page and transition timeline for the companion app."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto

import pygame

from companion_app.ui.console import TypewriterConsole
from companion_app.render import background

BOOT_CURSOR_HOLD_MS: int = 3000
BOOT_READY_HOLD_MS: int = 1000
BOOT_CONSOLE_MAX_LINES: int = 48
BOOT_TRANSCRIPT: tuple[str, ...] = (
    '********** PIP-05 (R) V7.1.0.8 **********',
    '',
    '',
    '',
    'COPYRIGHT 2075 ROBCO (R)',
    'LOADER 1.1',
    'EXEC VERSION 41.10',
    '64KB RAM SYSTEM',
    '38911 BYTES FREE',
    'NO HOLOTAPE FOUND',
    'LOAD ROM(1): DEITRIX 303',
    '',
    '',
)

_BOOT_MARGIN_X = 36
_BOOT_MARGIN_TOP = 36
_BOOT_MARGIN_BOTTOM = 36


class BootPhase(Enum):
    BOOTING = auto()
    CURSOR_HOLD = auto()
    CONNECTING = auto()
    READY_HOLD = auto()
    COMPLETE = auto()


@dataclass(frozen=True)
class BootTickResult:
    start_connect: bool = False


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

    def tick(
        self,
        dt_ms: int,
        console: TypewriterConsole,
        *,
        connection_ready: bool = False,
    ) -> BootTickResult:
        dt_ms = max(0, dt_ms)

        if self.phase is BootPhase.BOOTING:
            if console.is_idle():
                self.phase = BootPhase.CURSOR_HOLD
                self._phase_elapsed_ms = 0
                console.show_idle_cursor = True
                return BootTickResult()
            return BootTickResult()

        self._phase_elapsed_ms += dt_ms

        if self.phase is BootPhase.CURSOR_HOLD:
            if self._phase_elapsed_ms < BOOT_CURSOR_HOLD_MS:
                return BootTickResult()
            self.phase = BootPhase.CONNECTING
            self._phase_elapsed_ms = 0
            console.show_idle_cursor = False
            return BootTickResult(start_connect=True)

        if self.phase is BootPhase.CONNECTING:
            if not connection_ready or not console.is_idle():
                return BootTickResult()
            self.phase = BootPhase.READY_HOLD
            self._phase_elapsed_ms = 0
            console.show_idle_cursor = False
            return BootTickResult()

        if self.phase is BootPhase.READY_HOLD:
            if not console.is_idle():
                self._phase_elapsed_ms = 0
                return BootTickResult()
            if self._phase_elapsed_ms < BOOT_READY_HOLD_MS:
                return BootTickResult()
            self.phase = BootPhase.COMPLETE
            return BootTickResult()

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
