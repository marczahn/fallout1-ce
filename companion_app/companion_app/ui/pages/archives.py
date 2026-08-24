"""ARCHIVES section — QUESTS and HOLODISKS.

Replaces the old DATA page (TASK-017). That page's root/detail model for
*sub-section* navigation (select a tab, ``Confirm`` to enter it) is
deliberately gone — sub-sections switch immediately on the encoder, like
every other section.

**QUESTS is live as of TASK-021.** It mirrors the in-game Pip-Boy's quest
screen with the same two levels: level 1 is the location list with each
location's progress counts, ``Confirm`` drills into a location, level 2 is
that location's quest lines, ``Back`` comes back up. That is drill-down
*inside activated content*, which is the space TASK-018 opened — not a
revival of the sub-section navigation TASK-017 removed.

**HOLODISKS is still a placeholder.** Its content comes from a different
source (holodisk message ids, ``holocount``) and is a separate ticket;
QUESTS sets the pattern it will follow.

Three rules this renderer inherits rather than invents:

* **Exactly one filled element on screen** marks whatever the encoder
  drives — the sub-header segment when not activated, the selected list
  row once activated. Same rule as STATUS/INVENTORY, drawn the same way.
* **Row metrics come from ``ui/list_geometry``**, shared with the inventory
  so the device's two lists cannot drift apart.
* **Quest text wraps, never truncates.** The real strings live in the game
  data, not in this repo, so their lengths cannot be measured here; an
  unexpectedly long line has to degrade into a second row rather than lose
  text.

Completed quests render **struck through**, mirroring the engine's own
``PIPBOY_TEXT_STYLE_STRIKE_THROUGH``. ``DIM`` is deliberately not reused
for them: it means *disabled* everywhere else on the device, and a finished
quest is not disabled.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Sequence

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState
from companion_app.ui import list_geometry, quest_list, scroll_list
from companion_app.ui.sections import ARCHIVES_QUESTS
from companion_app.ui.shell import SUBHEADER_BAND_HEIGHT

if TYPE_CHECKING:
    from companion_app.ui.sections import SubSectionFocus

_PLACEHOLDER_TEXT: str = "NOT YET IMPLEMENTED"
_PLACEHOLDER_SIZE: int = 24

# Level-1 empty state, centred like the HOLODISKS placeholder so the two
# read as the same kind of message.
_EMPTY_SIZE: int = 20

# Each extra wrapped line, and the water label, cost one of these.
_WRAP_LINE_HEIGHT: int = 18

# The water countdown, drawn beneath its own quest's line.
_WATER_SIZE: int = 13
_WATER_INDENT: int = 18


def body_rect_for(content_rect: pygame.Rect) -> pygame.Rect:
    """The section body: ``content_rect`` below the sub-header band."""
    body = content_rect.copy()
    body.top += SUBHEADER_BAND_HEIGHT
    body.height = content_rect.height - SUBHEADER_BAND_HEIGHT
    return body


def list_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The rows area: inner body, left of the gutter.

    The gutter is excluded whether or not it is drawn, so a row's geometry
    does not change when a list grows past the viewport — the same rule the
    inventory follows.
    """
    inner = list_geometry.body_inner_rect(body_rect)
    rect = inner.copy()
    rect.width = inner.width - list_geometry.GUTTER_WIDTH - list_geometry.GUTTER_GAP
    return rect


def gutter_rect_for(body_rect: pygame.Rect) -> pygame.Rect:
    """The scroll-indicator track, hugging the inner right edge."""
    inner = list_geometry.body_inner_rect(body_rect)
    list_rect = list_rect_for(body_rect)
    return pygame.Rect(
        inner.right - list_geometry.GUTTER_WIDTH,
        list_rect.top,
        list_geometry.GUTTER_WIDTH,
        list_rect.height,
    )


def wrap_label(label: str, width: int, size: int) -> tuple[str, ...]:
    """Split ``label`` into lines that each fit ``width`` pixels.

    Word wrapping, measured with the real font rather than an assumed
    character width — the vendored face is proportional, so a character
    count would be wrong by a different amount for every string.

    A single word wider than the whole row is left overlong rather than
    broken mid-word: that degrades to one clipped row instead of scrambling
    the text, and real quest prose has no such word.
    """
    if not label:
        return ()
    if width <= 0:
        return (label,)

    lines: list[str] = []
    current = ""
    for word in label.split():
        candidate = f"{current} {word}" if current else word
        if current and font.measure_width(candidate, size) > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return tuple(lines)


def _text_width(list_rect: pygame.Rect) -> int:
    # The chevron ("> ") is drawn inside the row's text area, so the wrap
    # width has to allow for it or the first line would overrun by its
    # width alone.
    return (
        list_rect.width
        - 2 * list_geometry.ROW_PAD_X
        - font.measure_width("> ", list_geometry.ROW_SIZE)
    )


def _wrapped_for_row(
    row: scroll_list.ListRow,
    list_rect: pygame.Rect,
) -> tuple[str, ...]:
    return wrap_label(row.label, _text_width(list_rect), list_geometry.ROW_SIZE)


def quest_row_height(line_count: int, *, with_water: bool) -> int:
    """Height of a level-2 row holding ``line_count`` wrapped lines."""
    height = list_geometry.ROW_HEIGHT + max(line_count - 1, 0) * _WRAP_LINE_HEIGHT
    if with_water:
        height += _WRAP_LINE_HEIGHT
    return height


def row_height_fn(
    list_rect: pygame.Rect,
    water_key: str,
    level_two: bool,
) -> Callable[[scroll_list.ListRow], int]:
    """A ``row_height`` callable for ``scroll_list.visible``.

    Level-1 rows are single-line and uniform. Level-2 rows vary, because a
    long quest line wraps and the water-chip row carries an extra label
    beneath it — so the viewport has to measure rather than multiply.
    """

    def row_height(row: scroll_list.ListRow) -> int:
        if not level_two:
            return list_geometry.ROW_HEIGHT
        lines = _wrapped_for_row(row, list_rect)
        return quest_row_height(len(lines), with_water=row.key == water_key)

    return row_height


def _draw_row(
    surface: pygame.Surface,
    rect: pygame.Rect,
    lines: Sequence[str],
    *,
    selected: bool,
    activated: bool,
    struck: bool,
    water_label: str,
) -> None:
    """One list row: optional selection box, chevroned text, water label."""
    text_color = palette.FOREGROUND
    if selected:
        # Filled while the list holds the encoder, outlined otherwise — the
        # same rule the sub-header follows, inverted.
        pygame.draw.rect(
            surface,
            palette.FOREGROUND,
            rect,
            0 if activated else list_geometry.OUTLINE_WIDTH,
        )
        if activated:
            text_color = palette.BACKGROUND

    y = rect.top + list_geometry.ROW_PAD_Y
    for index, line in enumerate(lines):
        # Only the first line carries the "> " chevron (the CHARACTER and
        # INVENTORY rows' idiom); a wrapped continuation is indented to
        # match, so it reads as the same row rather than a new one.
        text = f"> {line}" if index == 0 else f"  {line}"
        font.draw_text_left(
            surface,
            text,
            (rect.left + list_geometry.ROW_PAD_X, y),
            list_geometry.ROW_SIZE,
            text_color,
            strike=struck,
        )
        y += _WRAP_LINE_HEIGHT

    if water_label:
        font.draw_text_left(
            surface,
            water_label,
            (rect.left + list_geometry.ROW_PAD_X + _WATER_INDENT, y),
            _WATER_SIZE,
            text_color,
        )


def _draw_empty(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
) -> None:
    font.draw_text_centered(
        surface,
        quest_list.EMPTY_TEXT,
        list_geometry.body_inner_rect(body_rect),
        _EMPTY_SIZE,
        palette.FOREGROUND,
    )


def render_quests(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
) -> None:
    """Draw whichever of the two quest levels ``focus`` selects."""
    quests = state.player.quests

    if not quests:
        # An explicit message, not a blank body: the app cannot tell "the
        # player has no quests" from "the server has not reported any yet",
        # and either way a blank screen reads as a failure to draw.
        # ``Confirm`` is already inert here — ``sections.handle_input``
        # refuses to activate a list with nothing selectable.
        _draw_empty(surface, body_rect)
        return

    location_index = quest_list.location_index_from_key(focus.location_key)
    level_two = location_index is not None
    if level_two:
        assert location_index is not None
        rows = quest_list.build_quest_rows(quests, location_index)
        if not rows:
            # Drilled into a location the server has since stopped
            # reporting. Show the empty state rather than a blank body; the
            # next ``Back`` returns to a level 1 that no longer lists it.
            _draw_empty(surface, body_rect)
            return
    else:
        rows = quest_list.build_location_rows(quests)

    list_rect = list_rect_for(body_rect)
    water_key = quest_list.water_row_key(quests) if level_two else ""
    water = quest_list.water_state(state.player)

    cursor = scroll_list.resolve_cursor(rows, focus.cursor)
    row_height = row_height_fn(list_rect, water_key, level_two)
    visible = scroll_list.visible(rows, cursor, list_rect.height, row_height)

    y = list_rect.top
    for _index, row in visible:
        height = row_height(row)
        row_rect = pygame.Rect(list_rect.left, y, list_rect.width, height)
        y += height

        if level_two:
            # ``or (row.label,)`` covers a row whose label is empty, which
            # ``build_quest_rows`` never produces (it substitutes
            # ``[NO TEXT]``) but which would otherwise draw nothing at all.
            lines = _wrapped_for_row(row, list_rect) or (row.label,)
            quest = quest_list.quest_for_key(quests, row.key)
            struck = quest.completed if quest is not None else False
            water_label = water.label if row.key == water_key else ""
        else:
            lines = (row.label,)
            struck = False
            water_label = ""

        _draw_row(
            surface,
            row_rect,
            lines,
            selected=row.key == cursor.selected_key,
            activated=focus.activated,
            struck=struck,
            water_label=water_label,
        )

    list_geometry.draw_scroll_gutter(
        surface,
        gutter_rect_for(body_rect),
        len(rows),
        visible[0][0] if visible else 0,
        len(visible),
    )


class ArchivesSection:
    """ARCHIVES section: the live QUESTS list, plus a HOLODISKS placeholder."""

    title = "ARCHIVES"

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
        selected_key: str,
        focus: SubSectionFocus,
    ) -> None:
        body_rect = body_rect_for(content_rect)
        if selected_key == ARCHIVES_QUESTS:
            render_quests(surface, body_rect, state, focus)
            return
        font.draw_text_centered(
            surface,
            _PLACEHOLDER_TEXT,
            body_rect,
            _PLACEHOLDER_SIZE,
            palette.FOREGROUND,
        )
