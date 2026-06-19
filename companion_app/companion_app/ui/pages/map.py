"""MAP page — GLOBAL / LOCAL sub-header control demo (TASK-010).

Adopts the reusable sub-header segmented control with ``GLOBAL`` /
``LOCAL`` segments and a per-segment placeholder body. Actual location
rendering and real ``LOCAL``-availability gating are later tickets; both
segments are enabled here so the control's UX is demonstrable.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from companion_app.render import font, palette
from companion_app.state import AppState
from companion_app.ui import segmented_header
from companion_app.ui.segmented_header import Segment, SegmentedHeaderState

if TYPE_CHECKING:
    import pygame

_MAP_BODY_TOP: int = 56
_BODY_SIZE: int = 22

_PLACEHOLDERS: dict[str, str] = {
    "GLOBAL": "GLOBAL MAP - NOT YET IMPLEMENTED",
    "LOCAL": "LOCAL MAP - NOT YET IMPLEMENTED",
}


def default_map_ui() -> SegmentedHeaderState:
    """Initial MAP control state: GLOBAL and LOCAL, GLOBAL selected."""
    return segmented_header.create(
        (
            Segment("GLOBAL", "GLOBAL"),
            Segment("LOCAL", "LOCAL"),
        )
    )


class MapPage:
    """MAP page with a GLOBAL / LOCAL sub-header segmented control."""

    title = "MAP"

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        ui_state: SegmentedHeaderState,
    ) -> None:
        _ = state
        segmented_header.render(surface, content_rect, ui_state)

        body_rect = content_rect.copy()
        body_rect.top += _MAP_BODY_TOP
        body_rect.height = content_rect.height - _MAP_BODY_TOP
        text = _PLACEHOLDERS.get(ui_state.selected_key, "NOT YET IMPLEMENTED")
        font.draw_text_centered(surface, text, body_rect, _BODY_SIZE, palette.FOREGROUND)
