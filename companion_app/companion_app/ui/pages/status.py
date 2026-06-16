"""STATUS page — full-screen live monitor matching the STATUS concept art."""
from __future__ import annotations

from typing import TYPE_CHECKING

import pygame

from companion_app.render import font, palette
from companion_app.state import AppState, PlayerState

if TYPE_CHECKING:
    import pygame

# Font sizes (the vendored Fallout face is the only typeface; sizes are tuned
# to the concept art proportions).
# Font sizes are anchored to the shared page-headline size (HEADER_SIZE = 16,
# the title size every other page uses) and scaled to preserve the size
# relationships of the STATUS concept art:
#   title 1.00 · HP value 1.45 · HP label 0.85 · sections 0.72
#   rows/special 0.70 · box 0.65   (relative to the headline/title)
STATUS_TITLE_SIZE: int = 16
STATUS_HP_LABEL_SIZE: int = 14
STATUS_HP_CHEVRON_SIZE: int = 13
STATUS_HP_VALUE_SIZE: int = 23
STATUS_BOX_SIZE: int = 10
STATUS_ROW_SIZE: int = 11
STATUS_SPECIAL_SIZE: int = 11
STATUS_SECTION_SIZE: int = 12

# All Y coordinates below are absolute offsets from the top of the rect the
# page is rendered into (the full virtual screen).
_LEFT_X: int = 40
_RIGHT_MARGIN: int = 28

_TITLE_CENTER_Y: int = 40

_HP_LABEL_Y: int = 100
_HP_VALUE_Y: int = 126
_HP_CHEVRON_X: int = 44
_HP_CHEVRON_Y: int = 131
_HP_DIGITS_X: int = 60

_BOX_LEFT: int = 300
_BOX_RIGHT: int = 432
_BOX_TOP: int = 92
_BOX_BOTTOM: int = 186
_BOX_CORNER: int = 22
_BOX_LABEL_X: int = 314
_BOX_VALUE_X: int = 354
_BOX_TEXT_Y: int = 110
_BOX_ROW_GAP: int = 26

_MID_TOP_Y: int = 236
_MID_ROW_GAP: int = 37
_LEFT_LABEL_X: int = 40
_LEFT_VALUE_X: int = 100
_RIGHT_LABEL_X: int = 256
_RIGHT_VALUE_X: int = 338

_SPECIAL_TITLE_Y: int = 440
_SPECIAL_ROW_Y: int = 482
_SPECIAL_ROW_GAP: int = 28
_SPECIAL_LABEL_X: int = 48
_SPECIAL_VALUE_X: int = 104
_SPECIAL_BAR_X: int = 132

_FX_TITLE_Y: int = 716
_FX_ROW_Y: int = 752

_SECTION_RULE_GAP: int = 14
_SECTION_RULE_Y_OFFSET: int = 7

_STIMPACK_PID: int = 40
_SUPER_STIMPACK_PID: int = 144
_BAR_SEGMENT_WIDTH: int = 4
_BAR_SEGMENT_HEIGHT: int = 12
_BAR_SEGMENT_GAP: int = 3

_TITLE_TEXT: str = "—= STATUS =—"


def synthesize_state_label(player: PlayerState) -> str:
    if player.max_hp > 0:
        hp_ratio = player.hp / player.max_hp
        if hp_ratio <= 0.25:
            return "CRITICAL"
        if hp_ratio <= 0.5:
            return "INJURED"
    if player.radiation != 0:
        return "IRRADIATED"
    if player.poison != 0:
        return "POISONED"
    return "STABLE"


def synthesize_status_fx_label(player: PlayerState) -> str:
    del player
    return "NONE"


def synthesize_stim_counts(player: PlayerState) -> tuple[int, int]:
    stimpacks = 0
    super_stimpacks = 0
    for item in player.inventory:
        if item.pid == _STIMPACK_PID:
            stimpacks += item.count
        elif item.pid == _SUPER_STIMPACK_PID:
            super_stimpacks += item.count
    return stimpacks, super_stimpacks


def _format_3(value: int) -> str:
    return f"{value:03d}"


def _format_2(value: int) -> str:
    return f"{value:02d}"


def _format_grouped(value: int) -> str:
    return f"{value:,}"


def _format_percent(value: int) -> str:
    return f"{value:03d}%"


class StatusPage:
    """Renders the full-screen STATUS monitor into the given rect."""

    title = "STATUS"

    def render(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        state: AppState,
    ) -> None:
        player = state.player
        top = content_rect.top

        self._draw_title(surface, content_rect)
        self._draw_hp(surface, top, player)
        self._draw_progression_box(surface, top, player)
        self._draw_middle_rows(surface, top, player)
        self._draw_special_block(surface, content_rect, player)
        self._draw_status_fx(surface, content_rect, player)

    def _draw_title(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
    ) -> None:
        title_rect = pygame.Rect(
            content_rect.left,
            content_rect.top,
            content_rect.width,
            _TITLE_CENTER_Y * 2,
        )
        font.draw_text_centered(
            surface,
            _TITLE_TEXT,
            title_rect,
            STATUS_TITLE_SIZE,
            palette.FOREGROUND,
        )

    def _draw_hp(
        self,
        surface: pygame.Surface,
        top: int,
        player: PlayerState,
    ) -> None:
        font.draw_text_left(
            surface,
            "HP",
            (_LEFT_X, top + _HP_LABEL_Y),
            STATUS_HP_LABEL_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_left(
            surface,
            ">",
            (_HP_CHEVRON_X, top + _HP_CHEVRON_Y),
            STATUS_HP_CHEVRON_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_left(
            surface,
            f"{_format_3(player.hp)}/{_format_3(player.max_hp)}",
            (_HP_DIGITS_X, top + _HP_VALUE_Y),
            STATUS_HP_VALUE_SIZE,
            palette.FOREGROUND,
        )

    def _draw_progression_box(
        self,
        surface: pygame.Surface,
        top: int,
        player: PlayerState,
    ) -> None:
        self._draw_corner_box(
            surface,
            _BOX_LEFT,
            top + _BOX_TOP,
            _BOX_RIGHT,
            top + _BOX_BOTTOM,
            _BOX_CORNER,
        )

        rows = [
            ("LVL:", _format_2(player.level)),
            ("XP:", _format_grouped(player.experience)),
            ("NX:", _format_grouped(player.next_level_exp)),
        ]
        for index, (label, value) in enumerate(rows):
            y = top + _BOX_TEXT_Y + (index * _BOX_ROW_GAP)
            font.draw_text_left(
                surface, label, (_BOX_LABEL_X, y), STATUS_BOX_SIZE, palette.FOREGROUND
            )
            font.draw_text_left(
                surface, value, (_BOX_VALUE_X, y), STATUS_BOX_SIZE, palette.FOREGROUND
            )

    def _draw_middle_rows(
        self,
        surface: pygame.Surface,
        top: int,
        player: PlayerState,
    ) -> None:
        stimpacks, super_stimpacks = synthesize_stim_counts(player)
        left_rows = [
            ("CND:", synthesize_state_label(player)),
            ("RAD:", _format_3(player.radiation)),
            ("POI:", _format_3(player.poison)),
            ("ARM:", _format_3(player.armor_class)),
            ("EFF:", synthesize_status_fx_label(player)),
        ]
        right_rows = [
            ("STIM:", f"{_format_2(stimpacks)}/{_format_2(super_stimpacks)}"),
            ("CARRY:", f"{player.current_carry_weight}/{player.carry_weight}"),
            ("MELEE:", _format_2(player.melee_damage)),
            ("DR:", _format_percent(player.damage_resistance)),
        ]
        start_y = top + _MID_TOP_Y

        for index, (label, value) in enumerate(left_rows):
            y = start_y + (index * _MID_ROW_GAP)
            self._draw_compact_row(
                surface, _LEFT_LABEL_X, _LEFT_VALUE_X, y, label, value
            )

        for index, (label, value) in enumerate(right_rows):
            y = start_y + (index * _MID_ROW_GAP)
            self._draw_compact_row(
                surface, _RIGHT_LABEL_X, _RIGHT_VALUE_X, y, label, value
            )

    def _draw_special_block(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        player: PlayerState,
    ) -> None:
        top = content_rect.top
        self._draw_section_header(
            surface, content_rect, top + _SPECIAL_TITLE_Y, "S.P.E.C.I.A.L."
        )

        stats = [
            ("STR", player.strength),
            ("PER", player.perception),
            ("END", player.endurance),
            ("CHA", player.charisma),
            ("INT", player.intelligence),
            ("AGI", player.agility),
            ("LCK", player.luck),
        ]
        for index, (label, value) in enumerate(stats):
            y = top + _SPECIAL_ROW_Y + (index * _SPECIAL_ROW_GAP)
            font.draw_text_left(
                surface,
                f"> {label}",
                (_SPECIAL_LABEL_X, y),
                STATUS_SPECIAL_SIZE,
                palette.FOREGROUND,
            )
            font.draw_text_left(
                surface,
                _format_2(value),
                (_SPECIAL_VALUE_X, y),
                STATUS_SPECIAL_SIZE,
                palette.FOREGROUND,
            )
            self._draw_special_bar(surface, _SPECIAL_BAR_X, y + 2, value)

    def _draw_status_fx(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        player: PlayerState,
    ) -> None:
        top = content_rect.top
        self._draw_section_header(
            surface, content_rect, top + _FX_TITLE_Y, "STATUS FX"
        )
        font.draw_text_left(
            surface,
            f"> {synthesize_status_fx_label(player)}",
            (_SPECIAL_LABEL_X, top + _FX_ROW_Y),
            STATUS_SPECIAL_SIZE,
            palette.FOREGROUND,
        )

    def _draw_section_header(
        self,
        surface: pygame.Surface,
        content_rect: pygame.Rect,
        title_y: int,
        text: str,
    ) -> None:
        label_rect = font.draw_text_left(
            surface,
            text,
            (_LEFT_X, title_y),
            STATUS_SECTION_SIZE,
            palette.FOREGROUND,
        )
        rule_y = title_y + _SECTION_RULE_Y_OFFSET
        pygame.draw.line(
            surface,
            palette.FOREGROUND,
            (label_rect.right + _SECTION_RULE_GAP, rule_y),
            (content_rect.right - _RIGHT_MARGIN, rule_y),
            1,
        )

    def _draw_compact_row(
        self,
        surface: pygame.Surface,
        label_x: int,
        value_x: int,
        y: int,
        label: str,
        value: str,
    ) -> None:
        font.draw_text_left(
            surface,
            f"> {label}",
            (label_x, y),
            STATUS_ROW_SIZE,
            palette.FOREGROUND,
        )
        font.draw_text_left(
            surface,
            value,
            (value_x, y),
            STATUS_ROW_SIZE,
            palette.FOREGROUND,
        )

    def _draw_special_bar(
        self,
        surface: pygame.Surface,
        x: int,
        y: int,
        value: int,
    ) -> None:
        clamped = max(0, min(value, 10))
        for index in range(clamped):
            segment_x = x + index * (_BAR_SEGMENT_WIDTH + _BAR_SEGMENT_GAP)
            pygame.draw.rect(
                surface,
                palette.FOREGROUND,
                pygame.Rect(
                    segment_x,
                    y,
                    _BAR_SEGMENT_WIDTH,
                    _BAR_SEGMENT_HEIGHT,
                ),
                0,
            )

    def _draw_corner_box(
        self,
        surface: pygame.Surface,
        left: int,
        top: int,
        right: int,
        bottom: int,
        corner: int,
    ) -> None:
        pygame.draw.line(surface, palette.FOREGROUND, (left, top), (left + corner, top), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (left, top), (left, top + corner), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (right - corner, top), (right, top), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (right, top), (right, top + corner), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (left, bottom - corner), (left, bottom), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (left, bottom), (left + corner, bottom), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (right - corner, bottom), (right, bottom), 1)
        pygame.draw.line(surface, palette.FOREGROUND, (right, bottom - corner), (right, bottom), 1)
