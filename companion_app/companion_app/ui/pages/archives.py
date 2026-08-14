"""ARCHIVES section — QUESTS and HOLODISKS (TASK-017).

Replaces the old DATA page. Both sub-sections are placeholders: the
navigation is the deliverable here, the content is not. The DATA page's
root/detail model (select a tab, ``Confirm`` to enter it) is deliberately
gone — sub-sections switch immediately on the encoder, like every other
section.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from companion_app.render import font, palette
from companion_app.state import AppState
from companion_app.ui.shell import SUBHEADER_BAND_HEIGHT

if TYPE_CHECKING:
    import pygame

    from companion_app.ui.sections import SubSectionFocus

_PLACEHOLDER_TEXT: str = "NOT YET IMPLEMENTED"
_PLACEHOLDER_SIZE: int = 24


class ArchivesSection:
    """ARCHIVES section: placeholder bodies for both sub-sections."""

    title = "ARCHIVES"

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        selected_key: str,
        focus: SubSectionFocus,
    ) -> None:
        _ = state
        _ = selected_key
        _ = focus  # nothing in ARCHIVES is activatable yet
        body_rect = content_rect.copy()
        body_rect.top += SUBHEADER_BAND_HEIGHT
        body_rect.height = content_rect.height - SUBHEADER_BAND_HEIGHT
        font.draw_text_centered(
            surface,
            _PLACEHOLDER_TEXT,
            body_rect,
            _PLACEHOLDER_SIZE,
            palette.FOREGROUND,
        )
