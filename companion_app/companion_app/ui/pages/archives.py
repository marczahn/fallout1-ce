"""ARCHIVES section — QUESTS, HOLODISKS and TRANSMISSIONS.

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

**TRANSMISSIONS is live as of TASK-024**, and follows the pattern QUESTS set,
with one difference that shapes the whole screen: its level 2 is a
**player, not a list**. Level 1 is the disk list; ``Confirm`` opens a
disk; level 2 draws an equalizer and a transport state, and the encoder
seeks there rather than moving a cursor. It renders **no transmission body
text at all** — the disk's content is the recording. See the TASK-024
audio-over-video decision.

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

**HOLODISKS is live as of TASK-025**, and is the third shape this section
holds: level 1 is the disk list, and level 2 is a **document, not a list and
not a player**. It draws no cursor, so the encoder scrolls the text — its
level-2 rows are one per scroll position, built here rather than in
``holodisk_list`` because the extent depends on soft-wrapping. Nothing on this
path touches audio; a holodisk is a document and a transmission is a recording.

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
from companion_app.audio import equalizer
from companion_app.ui import (
    holodisk_list,
    transmission_list,
    list_geometry,
    quest_list,
    scroll_list,
)
from companion_app.ui.sections import (
    ARCHIVES_HOLODISKS,
    ARCHIVES_QUESTS,
    ARCHIVES_TRANSMISSIONS,
)
from companion_app.ui.shell import SUBHEADER_BAND_HEIGHT

if TYPE_CHECKING:
    from companion_app.ui.sections import SubSectionFocus

_PLACEHOLDER_TEXT: str = "NOT YET IMPLEMENTED"
_PLACEHOLDER_SIZE: int = 24

# Transmission player (level 2) geometry.
_DISK_TITLE_SIZE: int = 18
_DISK_STATE_SIZE: int = 16
_EQ_BAR_GAP: int = 4
_EQ_HEIGHT: int = 160
_EQ_TOP_GAP: int = 40

# Timebar: a filled progress track plus `M:SS / M:SS`.
#
# Without this the transport is invisible. Pause and the 5-second seek have
# always worked, but with only an equalizer and a PLAYING/PAUSED line on
# screen there is no way to see that a seek moved anything - which reads as
# "there are no controls" rather than "the controls give no feedback".
_TIMEBAR_HEIGHT: int = 6
_TIMEBAR_TOP_GAP: int = 14
_TIMEBAR_TEXT_SIZE: int = 14
_TIMEBAR_TEXT_GAP: int = 6
# Vertical space the timebar block claims below the equalizer.
_TIMEBAR_BLOCK: int = (
    _TIMEBAR_TOP_GAP + _TIMEBAR_HEIGHT + _TIMEBAR_TEXT_GAP + _TIMEBAR_TEXT_SIZE
)
# A paused/stopped bar is still drawn, as a floor, so the equalizer reads
# as "present but still" rather than as a failure to draw.
_EQ_FLOOR_PX: int = 2

PLAYING_TEXT: str = "PLAYING"
PAUSED_TEXT: str = "PAUSED"

# Level-1 empty state, centred like the TRANSMISSIONS placeholder so the two
# read as the same kind of message.
_EMPTY_SIZE: int = 20

# Holodisk reader (level 2) typography.
#
# **9. Settled on the device, after trying the alternative.** This is the one
# number in the reader that was argued twice, so the reasoning is recorded
# here rather than left to be rediscovered.
#
# The game's holodisk prose was authored for the Pip-Boy's ~604px content
# view; the reader has ~398px. Measured with the real vendored face over the
# 790 non-blank lines in the 18 bodies:
#
#     size 14 (ROW_SIZE) -> 626 lines overflow    size 10 -> 319
#     size 13            -> 608 lines overflow    size  9 -> 6
#     size 11            -> 541 lines overflow    size  8 -> 0
#
# So the size *is* the formatting: below ~10 the game's line breaks fit, above
# it almost nothing does. It shipped at 9, was raised to 13 when the human
# called 9 too small, and went back to 9 when the wrapping that 13 forced
# turned out to be the worse problem - "quite small, yet readable, and the
# formatting is correct". **Raising this is not a local change**; it re-breaks
# every line on the screen, and the fix for that is paragraph reflow, not a
# bigger number.
_READER_SIZE: int = 9
_READER_LINE_HEIGHT: int = 12
# Air between the title header and the first line of the document.
_READER_HEADER_GAP: int = 14
# Continuation marker for a soft-wrapped line. At the settled size only 3 of
# the game's 912 lines wrap, so this is rare by design - but when it fires it
# is what stops a continuation from reading as a new authored line. Kept from
# the size-13 experiment because it costs nothing and those 3 lines are
# exactly the ones a reader would otherwise misread.
_READER_WRAP_INDENT: str = "  "

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


def wrap_body_line(line: str, width: int, size: int) -> tuple[str, ...]:
    """Wrap one holodisk body line, **preserving its leading indent**.

    ``wrap_label`` cannot be reused here: it wraps with ``label.split()``,
    which collapses leading whitespace. Two disks depend on that whitespace —
    index 11 right-aligns its timestamps with ~52 leading spaces, index 5
    indents its measurements — and losing it is exactly the "re-wrapped prose"
    the acceptance criteria rule out.

    An empty line returns ``("",)`` rather than ``()`` so a paragraph break
    (the engine's ``**END-PAR**``, already translated) still occupies one line
    of vertical space, the way the in-game screen draws it.

    Continuations carry ``_READER_WRAP_INDENT`` on top of the original indent.
    Rare at the reader's settled size — 3 of the game's 912 lines — but those
    3 are exactly the ones where a continuation would otherwise read as a new
    authored line, which is what the authored-line-break criterion is about.
    """
    if not line:
        return ("",)

    stripped = line.lstrip(" ")
    indent = line[: len(line) - len(stripped)]
    if not stripped:
        # Whitespace only: keep it as one line rather than wrapping nothing.
        return (line,)

    available = width - font.measure_width(indent, size) if indent else width
    wrapped = wrap_label(stripped, available, size) or (stripped,)
    return tuple(
        indent + (part if position == 0 else _READER_WRAP_INDENT + part)
        for position, part in enumerate(wrapped)
    )


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


def reader_text_rect(body_rect: pygame.Rect) -> pygame.Rect:
    """The document area: inner body, below the title header, left of gutter."""
    inner = list_geometry.body_inner_rect(body_rect)
    header_height = _DISK_TITLE_SIZE + _READER_HEADER_GAP
    return pygame.Rect(
        inner.left,
        inner.top + header_height,
        inner.width - list_geometry.GUTTER_WIDTH - list_geometry.GUTTER_GAP,
        inner.height - header_height,
    )


def reader_display_lines(disk, body_rect: pygame.Rect) -> list[str]:
    """The disk's body flattened into drawable lines, wrapping applied.

    One authored line becomes one or more display lines. This is the single
    place that expansion happens, so the input router and the renderer cannot
    disagree about how far the document scrolls.

    ``body_rect`` is threaded through from the real layout rather than taken
    from a module constant. An earlier version assumed the app's fixed 480x800
    surface and derived it here; that quietly made the input path and the
    renderer two sources of truth, which would diverge the moment either the
    layout gained an inset or a test rendered into a different rect.
    """
    text_rect = reader_text_rect(body_rect)
    width = text_rect.width - 2 * list_geometry.ROW_PAD_X
    lines: list[str] = []
    for line in disk.body:
        lines.extend(wrap_body_line(holodisk_list.renderable(line), width, _READER_SIZE))
    return lines


def reader_visible_line_count(body_rect: pygame.Rect) -> int:
    return max(1, reader_text_rect(body_rect).height // _READER_LINE_HEIGHT)


def reader_scroll_rows(disk, body_rect: pygame.Rect) -> list[scroll_list.ListRow]:
    """One row per **scroll position**, not one per line.

    This is what makes the encoder scroll properly, and it is a correction to
    how the reader was first built. It originally handed ``scroll_list`` one
    row per body line and let ``scroll_list.visible`` pick the window — but
    that function keeps the *selection* roughly centred, which is right for a
    list that draws a selection box and wrong for a document that draws none.
    The measured effect was **26 encoder clicks with no visible change** before
    the page moved at all, and the unit test missed it because it asserted the
    cursor moved rather than that the page did.

    Modelling a scroll position as a row instead means the cursor index *is*
    the index of the top visible line: every click moves the document by
    exactly one line, in both directions, with no dead zone at either end. The
    count is clamped so the last position still fills the screen, so scrolling
    can never run off into blank space.
    """
    total = len(reader_display_lines(disk, body_rect))
    visible = reader_visible_line_count(body_rect)
    positions = max(1, total - visible + 1)
    return [
        scroll_list.ListRow(key=holodisk_list.line_key(offset), label="")
        for offset in range(positions)
    ]


def render_holodisk_reader(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
    disk,
) -> None:
    """Level 2: the disk's document, scrolled by the encoder.

    Deliberately **not** a list: no chevron, no selection box, no strike.
    ``_draw_row`` would put a filled rectangle around whichever line the
    encoder happens to sit on, which is right for a menu and wrong for a
    document. The cursor is a scroll anchor here, nothing more — its position
    is visible only as the text moving.

    No pagination and no "n of m" counter, unlike the engine's own screen,
    which pages at 35 lines. One encoder and two buttons make paging fiddly to
    navigate; scrolling is what INVENTORY and QUESTS already teach.
    """
    inner = list_geometry.body_inner_rect(body_rect)

    row = holodisk_list.row_for_key(
        state.player.holodisks, holodisk_list.holodisk_key(disk.index)
    )
    title = row.title if row is not None else holodisk_list.NO_TITLE_LABEL
    header_height = _DISK_TITLE_SIZE + _READER_HEADER_GAP
    font.draw_text_centered(
        surface,
        title,
        pygame.Rect(inner.left, inner.top, inner.width, _DISK_TITLE_SIZE + 8),
        _DISK_TITLE_SIZE,
        palette.FOREGROUND,
    )

    text_rect = reader_text_rect(body_rect)

    lines = reader_display_lines(disk, body_rect)
    if not lines:
        # An empty body means the server could not resolve the text — never
        # that the disk has none. A visible failure, not a blank screen.
        font.draw_text_centered(
            surface,
            holodisk_list.NO_TEXT_TEXT,
            text_rect,
            _EMPTY_SIZE,
            palette.FOREGROUND,
        )
        return

    # The cursor index IS the top visible line — see `reader_scroll_rows`.
    # Resolving against the same rows the input router used keeps the two in
    # step, and clamping guards a cursor left over from a longer document.
    rows = reader_scroll_rows(disk, body_rect)
    cursor = scroll_list.resolve_cursor(rows, focus.cursor)
    top = min(max(cursor.selected_index, 0), max(len(rows) - 1, 0))

    visible_count = reader_visible_line_count(body_rect)
    window = lines[top:top + visible_count]

    y = text_rect.top
    for line in window:
        font.draw_text_left(
            surface,
            line,
            (text_rect.left + list_geometry.ROW_PAD_X, y),
            _READER_SIZE,
            palette.FOREGROUND,
        )
        y += _READER_LINE_HEIGHT

    # Measured in display lines, which is what actually scrolls. No-ops when
    # the whole document fits, which is what keeps a single-line disk free of
    # a gutter.
    list_geometry.draw_scroll_gutter(
        surface,
        pygame.Rect(
            inner.right - list_geometry.GUTTER_WIDTH,
            text_rect.top,
            list_geometry.GUTTER_WIDTH,
            text_rect.height,
        ),
        len(lines),
        top,
        len(window),
    )


def render_holodisks(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
) -> None:
    """Draw whichever of the two holodisk levels ``focus`` selects."""
    holodisks = state.player.holodisks

    if focus.location_key:
        disk = holodisk_list.disk_for_key(holodisks, focus.location_key)
        if disk is not None:
            render_holodisk_reader(surface, body_rect, state, focus, disk)
            return
        # Drilled into a disk the server has since stopped reporting. Fall
        # through to level 1 rather than blanking; `_active_rows` pops the
        # same way, so the next `Back` lands on a coherent list.

    if not holodisks:
        # An explicit message, not a blank body: the app cannot tell "the
        # player has found no disks" from "the server has not reported any
        # yet", and either way a blank screen reads as a failure to draw.
        font.draw_text_centered(
            surface,
            holodisk_list.EMPTY_TEXT,
            list_geometry.body_inner_rect(body_rect),
            _EMPTY_SIZE,
            palette.FOREGROUND,
        )
        return

    rows = holodisk_list.list_rows(holodisks)
    list_rect = list_rect_for(body_rect)
    cursor = scroll_list.resolve_cursor(rows, focus.cursor)
    visible = scroll_list.visible(
        rows, cursor, list_rect.height, lambda _row: list_geometry.ROW_HEIGHT
    )

    for position, (_row_index, row) in enumerate(visible):
        row_rect = pygame.Rect(
            list_rect.left,
            list_rect.top + position * list_geometry.ROW_HEIGHT,
            list_rect.width,
            list_geometry.ROW_HEIGHT,
        )
        _draw_row(
            surface,
            row_rect,
            [row.label],
            selected=row.key == cursor.selected_key,
            activated=focus.activated,
            struck=False,
            water_label="",
        )

    list_geometry.draw_scroll_gutter(
        surface,
        gutter_rect_for(body_rect),
        len(rows),
        visible[0][0] if visible else 0,
        len(visible),
    )


def _draw_equalizer(
    surface: pygame.Surface,
    rect: pygame.Rect,
    levels: Sequence[float],
) -> None:
    """Bottom-anchored bars, one per envelope band.

    Every bar keeps a floor so a paused or silent moment still reads as an
    equalizer at rest rather than as a screen that failed to draw.
    """
    if not levels or rect.width <= 0 or rect.height <= 0:
        return

    count = len(levels)
    total_gap = _EQ_BAR_GAP * (count - 1)
    bar_width = max(1, (rect.width - total_gap) // count)
    x = rect.left
    for level in levels:
        clamped = 0.0 if level < 0.0 else (1.0 if level > 1.0 else level)
        height = max(_EQ_FLOOR_PX, int(round(rect.height * clamped)))
        surface.fill(
            palette.FOREGROUND,
            pygame.Rect(x, rect.bottom - height, bar_width, height),
        )
        x += bar_width + _EQ_BAR_GAP


def format_clock(milliseconds: int) -> str:
    """`M:SS`, floored, clamped at zero.

    Floored rather than rounded so the readout never shows a second the
    audio has not reached: at 999ms this says 0:00, which is what a
    stopwatch does.
    """
    if milliseconds < 0:
        milliseconds = 0
    total_seconds = milliseconds // 1000
    return f"{total_seconds // 60}:{total_seconds % 60:02d}"


def _draw_timebar(
    surface: pygame.Surface,
    rect: pygame.Rect,
    position_ms: int,
    duration_ms: int,
) -> None:
    """A progress track with an elapsed fill, and `M:SS / M:SS` beneath it.

    ``duration_ms`` must be the PCM's duration, not the envelope's - the
    envelope rounds up to a whole 50ms frame, so using it would leave the
    fill short of the end on every transmission.
    """
    if rect.width <= 0:
        return

    track = pygame.Rect(rect.left, rect.top, rect.width, _TIMEBAR_HEIGHT)
    surface.fill(palette.DIM, track)

    if duration_ms > 0:
        fraction = position_ms / duration_ms
        fraction = 0.0 if fraction < 0.0 else (1.0 if fraction > 1.0 else fraction)
        filled = int(round(track.width * fraction))
        if filled > 0:
            surface.fill(
                palette.FOREGROUND,
                pygame.Rect(track.left, track.top, filled, track.height),
            )

    label = f"{format_clock(position_ms)} / {format_clock(duration_ms)}"
    font.draw_text_centered(
        surface,
        label,
        pygame.Rect(
            rect.left,
            track.bottom + _TIMEBAR_TEXT_GAP,
            rect.width,
            _TIMEBAR_TEXT_SIZE + 4,
        ),
        _TIMEBAR_TEXT_SIZE,
        palette.FOREGROUND,
    )


def render_transmission_player(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    index: int,
    sink,
) -> None:
    """Level 2: title, equalizer, transport state. No body text."""
    inner = list_geometry.body_inner_rect(body_rect)
    audio = state.transmission_audio

    row = transmission_list.row_for_key(
        state.player.transmissions, audio, transmission_list.transmission_key(index)
    )
    title = row.title if row is not None else transmission_list.NO_TITLE_LABEL
    font.draw_text_centered(
        surface,
        title,
        pygame.Rect(inner.left, inner.top, inner.width, _DISK_TITLE_SIZE + 8),
        _DISK_TITLE_SIZE,
        palette.FOREGROUND,
    )

    recording = audio.recordings.get(index)
    if recording is None:
        # One state for all three causes — unreachable filler disk, not
        # baked, or still syncing — by decision. `unavailable_text` only
        # distinguishes "the sync may still deliver it".
        font.draw_text_centered(
            surface,
            transmission_list.unavailable_text(audio),
            inner,
            _EMPTY_SIZE,
            palette.FOREGROUND,
        )
        return

    eq_rect = pygame.Rect(
        inner.left,
        inner.top + _DISK_TITLE_SIZE + _EQ_TOP_GAP,
        inner.width,
        min(
            _EQ_HEIGHT,
            max(
                0,
                inner.height
                - _DISK_TITLE_SIZE
                - _EQ_TOP_GAP
                - _TIMEBAR_BLOCK
                - 40,
            ),
        ),
    )

    if sink is not None and sink.is_playing and not sink.is_paused:
        levels = equalizer.bar_levels(
            recording.envelope,
            recording.bands,
            recording.frames,
            recording.frame_ms,
            sink.position_ms,
        )
    else:
        # Paused or stopped: bars hold at the floor, which is what makes
        # pause visible at a glance as well as in the state line.
        levels = equalizer.silent_levels(recording.bands)

    _draw_equalizer(surface, eq_rect, levels)

    # Position comes from the sink, which is the only thing that knows it;
    # duration from the PCM, NOT `recording.duration_ms` (the envelope's,
    # rounded up to a whole frame).
    position_ms = sink.position_ms if sink is not None else 0
    _draw_timebar(
        surface,
        pygame.Rect(
            inner.left,
            eq_rect.bottom + _TIMEBAR_TOP_GAP,
            inner.width,
            _TIMEBAR_BLOCK,
        ),
        position_ms,
        recording.pcm_duration_ms,
    )

    paused = sink is not None and sink.is_paused
    font.draw_text_centered(
        surface,
        PAUSED_TEXT if paused else PLAYING_TEXT,
        pygame.Rect(
            inner.left,
            eq_rect.bottom + _TIMEBAR_BLOCK + 12,
            inner.width,
            _DISK_STATE_SIZE + 8,
        ),
        _DISK_STATE_SIZE,
        palette.FOREGROUND if not paused else palette.DIM,
    )


def render_transmissions(
    surface: pygame.Surface,
    body_rect: pygame.Rect,
    state: AppState,
    focus: SubSectionFocus,
    sink=None,
) -> None:
    """Draw whichever of the two transmission levels ``focus`` selects."""
    audio = state.transmission_audio
    rows_source = state.player.transmissions

    index = transmission_list.transmission_index_from_key(focus.location_key)
    if index is not None:
        render_transmission_player(surface, body_rect, state, index, sink)
        return

    if not rows_source:
        font.draw_text_centered(
            surface,
            transmission_list.EMPTY_TEXT,
            list_geometry.body_inner_rect(body_rect),
            _EMPTY_SIZE,
            palette.FOREGROUND,
        )
        return

    rows = transmission_list.list_rows(rows_source, audio)
    list_rect = list_rect_for(body_rect)
    cursor = scroll_list.resolve_cursor(rows, focus.cursor)
    visible = scroll_list.visible(
        rows, cursor, list_rect.height, lambda _row: list_geometry.ROW_HEIGHT
    )

    for position, (row_index, row) in enumerate(visible):
        row_rect = pygame.Rect(
            list_rect.left,
            list_rect.top + position * list_geometry.ROW_HEIGHT,
            list_rect.width,
            list_geometry.ROW_HEIGHT,
        )
        _draw_row(
            surface,
            row_rect,
            [row.label],
            selected=row.key == cursor.selected_key,
            activated=focus.activated,
            struck=False,
            water_label="",
        )

    list_geometry.draw_scroll_gutter(
        surface,
        gutter_rect_for(body_rect),
        len(rows),
        visible[0][0] if visible else 0,
        len(visible),
    )


class ArchivesSection:
    """ARCHIVES section: QUESTS, HOLODISKS and TRANSMISSIONS, all live.

    Three sub-sections, and the two that sound alike are not:
    **HOLODISKS** are text documents you read (TASK-025) and
    **TRANSMISSIONS** are replayable cutscenes played back as audio
    (TASK-024). Nothing on the holodisk path touches audio, and nothing on
    the transmission path renders body text — keeping them apart is the whole
    point of the split that created these two tickets.
    """

    title = "ARCHIVES"

    def __init__(self, sink=None) -> None:
        # The sink is read-only here: the renderer asks it for position and
        # paused-ness, never drives it. All transport lives in
        # `ui/transmission_playback.py`, called from the frame loop.
        self._sink = sink

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
        if selected_key == ARCHIVES_HOLODISKS:
            render_holodisks(surface, body_rect, state, focus)
            return
        if selected_key == ARCHIVES_TRANSMISSIONS:
            render_transmissions(surface, body_rect, state, focus, self._sink)
            return
        # No sub-section reaches this any more; kept as the branch for a key
        # that is not one of the three, so an unknown segment degrades to a
        # message rather than a blank body.
        font.draw_text_centered(
            surface,
            _PLACEHOLDER_TEXT,
            body_rect,
            _PLACEHOLDER_SIZE,
            palette.FOREGROUND,
        )
