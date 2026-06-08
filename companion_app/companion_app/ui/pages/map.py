"""MAP page — stub (post-MVP)."""
from __future__ import annotations

from companion_app.render import font, palette


class MapPage:
    """Placeholder MAP page."""

    def render(self, surface, content_rect, state) -> None:
        font.draw_text_centered(
            surface,
            "NOT YET IMPLEMENTED",
            content_rect,
            32,
            palette.DIM,
        )
