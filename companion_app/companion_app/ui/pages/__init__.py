"""Section enum (TASK-017).

Sections are the top-level navigation concept. Each maps to one of the
device's section buttons:

    1 = STATUS      2 = AUTOMAPS      3 = ARCHIVES

The device's fourth button is reserved for a close/shutdown action and is
**not** a section, so ``PageButtonEvent(4)`` resolves to no member here and
must be ignored by the router rather than passed to ``Page(...)``.

Every section renders the same structure — shared header, segmented
sub-header, content — and owns a set of sub-sections defined in
:mod:`companion_app.ui.sections`.
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    import pygame

    from companion_app.state import AppState


class Page(Enum):
    STATUS = 1
    AUTOMAPS = 2
    ARCHIVES = 3


class StartupPage(Enum):
    SPLASH = "splash"
    BOOT = "boot"


VisiblePage: TypeAlias = Page | StartupPage


class SectionRenderer(Protocol):
    """What every section must provide to be dispatched by ``app.py``.

    A section draws its selected sub-section into the shared content rect.
    It does **not** draw the segmented sub-header — the frame loop does
    that for all sections — but it must leave the first
    ``SUBHEADER_BAND_HEIGHT`` pixels of the rect clear for it.
    """

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        selected_key: str,
    ) -> None: ...

    @property
    def title(self) -> str: ...
