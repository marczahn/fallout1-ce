"""Typewriter console text for connection and system messages."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import pygame

from companion_app.render import palette
from companion_app.render.font import font_render_surface

CONSOLE_FONT_SIZE: int = 12
CONSOLE_MAX_LINES: int = 10
CONSOLE_LINE_HEIGHT: int = 16
CONSOLE_PADDING: int = 0
CONSOLE_CHAR_INTERVAL_MS: int = 28
CONSOLE_LINE_DELAY_MS: int = 180
CONSOLE_CURSOR_BLINK_MS: int = 320
CONSOLE_CURSOR_GLYPH: str = '_'

@dataclass
class ConsoleLine:
    text: str
    typed_chars: int = 0
    typing_complete: bool = True


@dataclass(frozen=True)
class CursorDrawState:
    text: str
    cursor_at_bottom: bool = False


@dataclass
class TypewriterConsole:
    max_lines: int = CONSOLE_MAX_LINES
    visible: bool = True
    show_idle_cursor: bool = False
    lines: deque[ConsoleLine] = field(default_factory=lambda: deque(maxlen=CONSOLE_MAX_LINES))
    _pending: deque[str] = field(default_factory=deque)
    _char_timer_ms: int = 0
    _line_delay_ms: int = 0
    _cursor_timer_ms: int = 0
    _cursor_visible: bool = True

    def __post_init__(self) -> None:
        if self.max_lines <= 0:
            raise ValueError(f"max_lines must be > 0, got {self.max_lines}")
        if self.lines.maxlen != self.max_lines:
            self.lines = deque(self.lines, maxlen=self.max_lines)

    def log(self, msg: str) -> None:
        normalized = msg.upper()
        if self._active_line() is None and self._line_delay_ms == 0 and not self._pending:
            self.lines.append(ConsoleLine(text=normalized, typed_chars=0, typing_complete=not normalized))
            return
        self._pending.append(normalized)

    def tick(self, dt_ms: int = 16) -> None:
        dt_ms = max(0, dt_ms)
        self._advance_cursor(dt_ms)

        active = self._active_line()
        if active is None:
            if self._line_delay_ms > 0:
                self._line_delay_ms = max(0, self._line_delay_ms - dt_ms)
                if self._line_delay_ms > 0:
                    return
            if self._pending:
                while self._pending:
                    text = self._pending.popleft()
                    self.lines.append(ConsoleLine(text=text, typed_chars=0, typing_complete=not text))
                    if text:
                        break
            return

        self._char_timer_ms += dt_ms
        while self._char_timer_ms >= CONSOLE_CHAR_INTERVAL_MS and active.typed_chars < len(active.text):
            active.typed_chars += 1
            self._char_timer_ms -= CONSOLE_CHAR_INTERVAL_MS

        if active.typed_chars >= len(active.text):
            active.typed_chars = len(active.text)
            active.typing_complete = True
            self._char_timer_ms = 0
            if self._pending and active.text:
                self._line_delay_ms = CONSOLE_LINE_DELAY_MS

    def draw(self, surface: pygame.Surface, rect: pygame.Rect | None = None) -> None:
        if not self.visible or (not self.lines and not self.show_idle_cursor):
            return

        panel_rect = rect or pygame.Rect(0, 0, surface.get_width(), 220)
        lines = list(self.lines)
        available_rows = max(1, panel_rect.height // CONSOLE_LINE_HEIGHT)
        visible_lines = lines[-available_rows:]
        active = self._active_line()
        y = panel_rect.top
        for index, line in enumerate(visible_lines):
            state = _display_state(
                line,
                cursor_visible=self._cursor_visible,
                is_active=line is active,
                is_last_visible=index == len(visible_lines) - 1,
                show_idle_cursor=self.show_idle_cursor and active is None,
            )
            rendered = font_render_surface(state.text, CONSOLE_FONT_SIZE, _line_color(line.text))
            if rendered is not None:
                surface.blit(rendered, (panel_rect.left + CONSOLE_PADDING, y))
            if state.cursor_at_bottom:
                cursor_rendered = font_render_surface(
                    CONSOLE_CURSOR_GLYPH,
                    CONSOLE_FONT_SIZE,
                    _line_color(line.text),
                )
                if cursor_rendered is not None:
                    cursor_y = y + CONSOLE_LINE_HEIGHT - cursor_rendered.get_height()
                    surface.blit(
                        cursor_rendered,
                        (panel_rect.left + CONSOLE_PADDING, cursor_y),
                    )
            y += CONSOLE_LINE_HEIGHT
        if not visible_lines and self.show_idle_cursor and self._cursor_visible:
            rendered = font_render_surface(
                CONSOLE_CURSOR_GLYPH,
                CONSOLE_FONT_SIZE,
                palette.FOREGROUND,
            )
            if rendered is not None:
                surface.blit(rendered, (panel_rect.left + CONSOLE_PADDING, y))

    def is_idle(self) -> bool:
        return self._active_line() is None and self._line_delay_ms == 0 and not self._pending

    def clear(self) -> None:
        self.lines.clear()
        self._pending.clear()
        self._char_timer_ms = 0
        self._line_delay_ms = 0

    def _active_line(self) -> ConsoleLine | None:
        for line in reversed(self.lines):
            if not line.typing_complete:
                return line
        return None

    def _advance_cursor(self, dt_ms: int) -> None:
        self._cursor_timer_ms += dt_ms
        while self._cursor_timer_ms >= CONSOLE_CURSOR_BLINK_MS:
            self._cursor_timer_ms -= CONSOLE_CURSOR_BLINK_MS
            self._cursor_visible = not self._cursor_visible


def _line_color(text: str) -> tuple[int, int, int]:
    _ = text
    return palette.FOREGROUND


def _display_state(
    line: ConsoleLine,
    *,
    cursor_visible: bool,
    is_active: bool,
    is_last_visible: bool,
    show_idle_cursor: bool,
) -> CursorDrawState:
    text = line.text[:line.typed_chars]
    draw_cursor = cursor_visible and (is_active or (show_idle_cursor and is_last_visible))
    if show_idle_cursor and is_last_visible and not is_active:
        text = line.text
    cursor_at_bottom = (
        draw_cursor
        and show_idle_cursor
        and is_last_visible
        and not is_active
        and not line.text
    )
    if draw_cursor and not cursor_at_bottom:
        text = f'{text}{CONSOLE_CURSOR_GLYPH}'
    return CursorDrawState(text=text, cursor_at_bottom=cursor_at_bottom)
