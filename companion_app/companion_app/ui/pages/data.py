"""DATA page — stub (M5 will add quests / holodisks)."""
from __future__ import annotations

from companion_app.render import font, palette


class DataPage:
    """Placeholder DATA page."""

    def render(self, surface, content_rect, state) -> None:
        font.draw_text_centered(
            surface,
            "NOT YET IMPLEMENTED",
            content_rect,
            32,
            palette.DIM,
        )
