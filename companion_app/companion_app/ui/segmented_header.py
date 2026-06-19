"""Reusable sub-header segmented control (TASK-010).

A horizontal segmented button bar rendered as a sub-headline directly
beneath a page's main headline. It is an optional "second control
dimension": a page opts in, switches segments with the existing
``EncoderLeft``/``EncoderRight`` events, and the active segment is drawn
inverse-filled (solid foreground box with background-colored text).

Selection state is immutable and the cycle transitions are pure, so they
are unit-testable without a display (mirrors the ``data.py``
``move_selection_*`` pattern). The render geometry is measured from the
label widths rather than a fixed gap.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import pygame

from companion_app.render import font, palette
from companion_app.ui.shell import PAGE_MARGIN_X

# Slightly smaller than the page headline (HEADER_SIZE = 16); matches the
# existing STATUS sub-header scale (STATUS_SECTION_SIZE = 14).
SUBHEADER_SIZE: int = 14

_SUBHEADER_TOP_GAP: int = 6
# Anchor to the shared page margin so the sub-header's left edge aligns with
# the header bar's left rule.
_SUBHEADER_LEFT_X: int = PAGE_MARGIN_X
_SEG_PAD_X: int = 8
_SEG_PAD_Y: int = 4
_SEG_GAP: int = 12

# Sentinel selected_key meaning "no active segment". Intentionally not a
# valid segment key.
_NO_SELECTION: str = ""


@dataclass(frozen=True)
class Segment:
    key: str
    label: str
    enabled: bool = True


@dataclass(frozen=True)
class SegmentedHeaderState:
    segments: tuple[Segment, ...]
    selected_key: str


def create(segments: Sequence[Segment]) -> SegmentedHeaderState:
    """Build a state whose selection is the first *enabled* segment.

    A disabled leading segment is skipped. If no segment is enabled, the
    selection is the empty-string sentinel (no active segment).
    """
    segs = tuple(segments)
    selected_key = _NO_SELECTION
    for seg in segs:
        if seg.enabled:
            selected_key = seg.key
            break
    return SegmentedHeaderState(segments=segs, selected_key=selected_key)


def _selected_index(state: SegmentedHeaderState) -> int | None:
    for index, seg in enumerate(state.segments):
        if seg.key == state.selected_key:
            return index
    return None


def _cycle(state: SegmentedHeaderState, step: int) -> SegmentedHeaderState:
    # Guard before any index lookup: nothing to do without an enabled
    # segment or a resolvable current selection (e.g. the sentinel).
    if not any(seg.enabled for seg in state.segments):
        return state
    current = _selected_index(state)
    if current is None:
        return state

    count = len(state.segments)
    index = current
    for _ in range(count):
        index = (index + step) % count
        if state.segments[index].enabled:
            return SegmentedHeaderState(
                segments=state.segments,
                selected_key=state.segments[index].key,
            )
    return state


def cycle_next(state: SegmentedHeaderState) -> SegmentedHeaderState:
    """Advance to the next enabled segment, wrapping endlessly."""
    return _cycle(state, 1)


def cycle_prev(state: SegmentedHeaderState) -> SegmentedHeaderState:
    """Move to the previous enabled segment, wrapping endlessly."""
    return _cycle(state, -1)


def _segment_text_color(seg: Segment, selected_key: str) -> tuple[int, int, int]:
    if not seg.enabled:
        return palette.DIM
    if seg.key == selected_key:
        return palette.BACKGROUND
    return palette.FOREGROUND


def render(
    surface: pygame.Surface,
    content_rect: pygame.Rect,
    state: SegmentedHeaderState,
    *,
    top_gap: int = _SUBHEADER_TOP_GAP,
) -> None:
    """Draw the segmented control left-aligned beneath the page headline.

    The active segment is inverse-filled; inactive enabled segments are
    plain foreground text; disabled segments are dimmed. Layout is stable
    regardless of which segment is active because each segment advances by
    the same padded width whether or not it carries the active box.
    """
    x = content_rect.left + _SUBHEADER_LEFT_X
    y = content_rect.top + top_gap

    for seg in state.segments:
        is_active = seg.enabled and seg.key == state.selected_key
        text_color = _segment_text_color(seg, state.selected_key)
        text_surf = font.font_render_surface(seg.label, SUBHEADER_SIZE, text_color)
        if text_surf is None:
            continue

        text_w, text_h = text_surf.get_size()
        box_w = text_w + 2 * _SEG_PAD_X

        if is_active:
            box = pygame.Rect(x, y, box_w, text_h + 2 * _SEG_PAD_Y)
            pygame.draw.rect(surface, palette.FOREGROUND, box)

        # Inactive labels sit at the same inset as the active label so the
        # row does not shift when the selection changes.
        surface.blit(text_surf, (x + _SEG_PAD_X, y + _SEG_PAD_Y))
        x += box_w + _SEG_GAP
