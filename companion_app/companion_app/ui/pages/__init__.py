"""Page enum and page dispatch registry (UI refactoring).

Pages are the top-level navigation concept — they replace the old
``Section`` enum. Each page maps to one of the four hardware section
buttons (1=STATUS, 2=DATA, 3=INVENTORY, 4=MAP).
"""
from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeAlias

if TYPE_CHECKING:
    import pygame

    from companion_app.state import AppState


class Page(Enum):
    STATUS = 1
    DATA = 2
    INVENTORY = 3
    MAP = 4


class StartupPage(Enum):
    SPLASH = "splash"
    BOOT = "boot"


VisiblePage: TypeAlias = Page | StartupPage


class PageRenderer(Protocol):
    """Minimal contract every page must satisfy.

    A page renders itself into the layout's content rect using the
    shared ``AppState``. Pages are stateless-per-frame objects owned
    by ``app.py``.
    """

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
    ) -> None: ...

    @property
    def title(self) -> str | None: ...
