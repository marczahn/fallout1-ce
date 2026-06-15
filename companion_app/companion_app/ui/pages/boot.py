"""Startup boot page and transition timeline for the companion app."""
from __future__ import annotations

import io
from dataclasses import dataclass
from enum import Enum, auto
from importlib import resources
from importlib.resources.abc import Traversable

import pygame

from companion_app.render import background
from companion_app.ui.console import TypewriterConsole

SPLASH_HOLD_MS: int = 3000
SPLASH_RESOURCE_PACKAGE = "companion_app.assets"
SPLASH_FILENAME = "startup_splash.png"
SPLASH_MAX_WIDTH_FILL = 2 / 3
SPLASH_CENTER_OFFSET_X = -18

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

_splash_bytes_cache: bytes | None = None


class SplashAssetLoadError(RuntimeError):
    """Raised when the startup splash asset cannot be loaded."""


def _resolve_splash_traversable() -> Traversable:
    try:
        candidate = resources.files(SPLASH_RESOURCE_PACKAGE) / SPLASH_FILENAME
    except (ModuleNotFoundError, FileNotFoundError) as e:
        raise SplashAssetLoadError(
            f"splash asset package {SPLASH_RESOURCE_PACKAGE!r} not importable: {e}"
        ) from e
    if not candidate.is_file():
        raise SplashAssetLoadError(
            f"splash asset {SPLASH_FILENAME!r} not found at {candidate!s}"
        )
    return candidate


def _load_splash_bytes() -> bytes:
    global _splash_bytes_cache
    if _splash_bytes_cache is not None:
        return _splash_bytes_cache
    traversable = _resolve_splash_traversable()
    try:
        data = traversable.read_bytes()
    except OSError as e:
        raise SplashAssetLoadError(
            f"cannot read splash asset at {traversable!s}: {e}"
        ) from e
    if not data:
        raise SplashAssetLoadError(f"splash asset at {traversable!s} is empty")
    _splash_bytes_cache = data
    return data


def load_startup_splash() -> pygame.Surface:
    return pygame.image.load(io.BytesIO(_load_splash_bytes()), SPLASH_FILENAME)


class BootPhase(Enum):
    SPLASH = auto()
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
    phase: BootPhase = BootPhase.SPLASH
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

        if self.phase is BootPhase.SPLASH:
            self._phase_elapsed_ms += dt_ms
            if self._phase_elapsed_ms < SPLASH_HOLD_MS:
                return BootTickResult()
            self.phase = BootPhase.BOOTING
            self._phase_elapsed_ms = 0
            self.begin(console)
            return BootTickResult()

        if self.phase is BootPhase.BOOTING:
            if not self._boot_started:
                self.begin(console)
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

    @property
    def show_boot_console(self) -> bool:
        return self.phase in {
            BootPhase.BOOTING,
            BootPhase.CURSOR_HOLD,
            BootPhase.CONNECTING,
            BootPhase.READY_HOLD,
        }


class BootPage:
    """Dedicated startup page with a full-screen console layout."""

    title = None

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


class SplashPage:
    """Bitmap splash page shown before the boot console appears."""

    title = None

    def __init__(self) -> None:
        self._image = load_startup_splash()

    def render(self, surface: pygame.Surface) -> None:
        background.fill_background(surface)

        image_rect = self._image.get_rect()
        target_rect = surface.get_rect()
        scale = min(
            (target_rect.width * SPLASH_MAX_WIDTH_FILL) / image_rect.width,
            target_rect.height / image_rect.height,
        )
        scaled_size = (
            max(1, int(image_rect.width * scale)),
            max(1, int(image_rect.height * scale)),
        )
        image = self._image
        if image_rect.size != scaled_size:
            image = pygame.transform.smoothscale(self._image, scaled_size)
        dest_rect = image.get_rect(
            center=(target_rect.centerx + SPLASH_CENTER_OFFSET_X, target_rect.centery),
        )
        surface.blit(image, dest_rect)
