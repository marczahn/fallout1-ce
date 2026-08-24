"""ARCHIVES/QUESTS renderer tests (TASK-021).

Headless renders at both levels, in both focus states, for the empty /
one-location / long-scroll cases. Assertions are about pixels and geometry
rather than "it did not raise": the screen's whole job is to show what the
in-game Pip-Boy shows, so a test that only proves the code ran would not
have caught any of the defects this file guards.
"""
from __future__ import annotations

import unittest

import pygame

from companion_app.render import palette
from companion_app.state import AppState, ConnectionState, PlayerState, Quest, WaterStatus
from companion_app.ui import list_geometry, quest_list, sections
from companion_app.ui.pages import Page
from companion_app.ui.pages import archives
from companion_app.ui.pages.archives import ArchivesSection
from companion_app.ui.scroll_list import ListCursor
from companion_app.ui.sections import ARCHIVES_HOLODISKS, ARCHIVES_QUESTS, SubSectionFocus

SURFACE_SIZE = (480, 800)
# The rect app.py hands a section: full virtual width, below the header.
CONTENT_RECT = pygame.Rect(0, 41, 480, 759)

FG = tuple(palette.FOREGROUND)


def _surface() -> pygame.Surface:
    if not pygame.display.get_init():
        pygame.display.init()
    return pygame.Surface(SURFACE_SIZE)


def _quest(
    location_index: int,
    slot: int,
    *,
    location: str,
    text: str,
    completed: bool = False,
    water_chip: bool = False,
) -> Quest:
    return Quest(
        location_index=location_index,
        slot=slot,
        location=location,
        text=text,
        completed=completed,
        water_chip=water_chip,
    )


VAULT13 = (
    _quest(0, 3, location="Vault 13", text="Find the water chip.", water_chip=True),
    _quest(0, 4, location="Vault 13", text="Catch the water thief.", completed=True),
)
JUNKTOWN = tuple(
    _quest(3, slot, location="Junktown", text=f"Junktown job {slot}.")
    for slot in range(6)
)


def _state(
    quests: tuple[Quest, ...],
    *,
    days: int = 137,
    countdown: bool = True,
) -> AppState:
    return AppState(
        connection=ConnectionState.READY,
        player=PlayerState(
            available=True,
            quests=list(quests),
            water=WaterStatus(days_remaining=days, countdown_active=countdown),
        ),
    )


def _focus(
    *,
    activated: bool = False,
    cursor: ListCursor | None = None,
    location_key: str = "",
) -> SubSectionFocus:
    return SubSectionFocus(
        activated=activated,
        cursor=cursor if cursor is not None else ListCursor(),
        location_key=location_key,
    )


def _render(state: AppState, focus: SubSectionFocus, key: str = ARCHIVES_QUESTS):
    surface = _surface()
    ArchivesSection().render(surface, CONTENT_RECT, state, key, focus)
    return surface


def _lit_pixel_count(surface: pygame.Surface) -> int:
    return sum(
        1
        for x in range(SURFACE_SIZE[0])
        for y in range(SURFACE_SIZE[1])
        if tuple(surface.get_at((x, y))[:3]) != (0, 0, 0)
    )


def _body_rect() -> pygame.Rect:
    return archives.body_rect_for(CONTENT_RECT)


class EmptyStateTests(unittest.TestCase):
    def test_no_quests_draws_the_empty_message_not_a_blank_body(self) -> None:
        surface = _render(_state(()), _focus())
        blank = _surface()
        self.assertNotEqual(
            pygame.image.tostring(surface, "RGB"),
            pygame.image.tostring(blank, "RGB"),
            "empty state must draw something",
        )

    def test_empty_state_is_centred_in_the_body(self) -> None:
        surface = _render(_state(()), _focus())
        inner = list_geometry.body_inner_rect(_body_rect())
        lit_ys = [
            y
            for y in range(SURFACE_SIZE[1])
            for x in range(SURFACE_SIZE[0])
            if tuple(surface.get_at((x, y))[:3]) != (0, 0, 0)
        ]
        self.assertTrue(lit_ys)
        self.assertAlmostEqual(
            (min(lit_ys) + max(lit_ys)) // 2, inner.centery, delta=12
        )

    def test_empty_state_draws_nothing_in_the_subheader_band(self) -> None:
        # app.py draws the sub-header itself; a section that painted into
        # that band would overdraw it.
        surface = _render(_state(()), _focus())
        body = _body_rect()
        for y in range(CONTENT_RECT.top, body.top):
            for x in range(SURFACE_SIZE[0]):
                self.assertEqual(
                    tuple(surface.get_at((x, y))[:3]),
                    (0, 0, 0),
                    f"drew into the sub-header band at ({x},{y})",
                )


class HolodisksUnchangedTests(unittest.TestCase):
    def test_holodisks_still_renders_the_placeholder(self) -> None:
        with_quests = _render(
            _state(VAULT13), _focus(), key=ARCHIVES_HOLODISKS
        )
        without = _render(_state(()), _focus(), key=ARCHIVES_HOLODISKS)
        self.assertEqual(
            pygame.image.tostring(with_quests, "RGB"),
            pygame.image.tostring(without, "RGB"),
            "HOLODISKS must ignore quest state entirely",
        )

    def test_holodisks_is_unaffected_by_focus_and_depth(self) -> None:
        plain = _render(_state(VAULT13), _focus(), key=ARCHIVES_HOLODISKS)
        focused = _render(
            _state(VAULT13),
            _focus(activated=True, cursor=ListCursor("L0", 0), location_key="L0"),
            key=ARCHIVES_HOLODISKS,
        )
        self.assertEqual(
            pygame.image.tostring(plain, "RGB"),
            pygame.image.tostring(focused, "RGB"),
        )


class LevelOneTests(unittest.TestCase):
    def test_one_location_renders(self) -> None:
        surface = _render(_state(VAULT13), _focus())
        self.assertGreater(_lit_pixel_count(surface), 0)

    def test_level_one_differs_from_the_empty_state(self) -> None:
        with_data = _render(_state(VAULT13), _focus())
        empty = _render(_state(()), _focus())
        self.assertNotEqual(
            pygame.image.tostring(with_data, "RGB"),
            pygame.image.tostring(empty, "RGB"),
        )

    def test_selection_is_outlined_when_not_activated_and_filled_when_it_is(
        self,
    ) -> None:
        """Exactly one filled element on screen — the shared focus rule.

        Not activated, the selected row is an outline (the sub-header
        carries the fill, drawn by app.py). Activated, the row is solid.
        A solid row covers far more pixels than its outline, which is what
        this measures.
        """
        state = _state(VAULT13 + JUNKTOWN)
        cursor = ListCursor("L0", 0)
        outlined = _lit_pixel_count(_render(state, _focus(cursor=cursor)))
        filled = _lit_pixel_count(
            _render(state, _focus(activated=True, cursor=cursor))
        )
        self.assertGreater(filled, outlined * 2)

    def test_level_one_row_is_never_struck_through(self) -> None:
        """A completed *quest* is struck; a location row never is.

        Vault 13's slot-4 quest is completed. If strike-through leaked from
        a quest to its location row, the level-1 render of a location with
        a completed quest would carry a rule that the same location without
        one does not — so its extra pixels would exceed what the differing
        ``0/2`` vs ``1/2`` count glyph can account for.
        """
        completed = _state(VAULT13)
        none_completed = _state(
            (
                _quest(0, 3, location="Vault 13", text="Find the water chip.",
                       water_chip=True),
                _quest(0, 4, location="Vault 13", text="Catch the water thief."),
            )
        )
        focus = _focus(cursor=ListCursor("L0", 0))
        with_completed = _lit_pixel_count(_render(completed, focus))
        without = _lit_pixel_count(_render(none_completed, focus))
        # A rule across a row would add roughly the row's width in pixels
        # (~380). One differing digit glyph is a couple of dozen at most.
        self.assertLess(abs(with_completed - without), 100)

    def test_all_locations_fit_without_scrolling_when_few(self) -> None:
        state = _state(VAULT13)
        rows = quest_list.build_location_rows(state.player.quests)
        list_rect = archives.list_rect_for(_body_rect())
        self.assertLessEqual(
            len(rows) * list_geometry.ROW_HEIGHT, list_rect.height
        )


class LevelTwoTests(unittest.TestCase):
    def test_drilled_view_differs_from_level_one(self) -> None:
        state = _state(VAULT13 + JUNKTOWN)
        level_one = _render(state, _focus(activated=True, cursor=ListCursor("L0", 0)))
        level_two = _render(
            state,
            _focus(activated=True, cursor=ListCursor("Q0.3", 0), location_key="L0"),
        )
        self.assertNotEqual(
            pygame.image.tostring(level_one, "RGB"),
            pygame.image.tostring(level_two, "RGB"),
        )

    def test_completed_quest_is_struck_through(self) -> None:
        """The completed row must carry more lit pixels than the same row
        uncompleted — the strike rule is measured, not assumed."""
        struck_state = _state(
            (_quest(0, 4, location="Vault 13", text="Catch the water thief.",
                    completed=True),)
        )
        plain_state = _state(
            (_quest(0, 4, location="Vault 13", text="Catch the water thief."),)
        )
        focus = _focus(location_key="L0", cursor=ListCursor("Q0.4", 0))
        self.assertGreater(
            _lit_pixel_count(_render(struck_state, focus)),
            _lit_pixel_count(_render(plain_state, focus)),
        )

    def test_water_label_is_drawn_on_the_water_chip_row(self) -> None:
        with_water = _state(VAULT13, days=137, countdown=True)
        # Same rows, but nothing flagged as the water-chip quest, so no
        # label should be drawn at all.
        without_flag = _state(
            (
                _quest(0, 3, location="Vault 13", text="Find the water chip."),
                _quest(0, 4, location="Vault 13", text="Catch the water thief.",
                       completed=True),
            ),
            days=137,
            countdown=True,
        )
        focus = _focus(location_key="L0", cursor=ListCursor("Q0.3", 0))
        self.assertGreater(
            _lit_pixel_count(_render(with_water, focus)),
            _lit_pixel_count(_render(without_flag, focus)),
            "the countdown label must add pixels on the flagged row",
        )

    def test_the_four_countdown_states_each_render_differently(self) -> None:
        """Running / secured / depleted must be visually distinct.

        The divergent case shares its label with running (by design — the
        server sends completed *and* countdownActive, and the projection
        reports both) so it is asserted separately below.
        """
        focus = _focus(location_key="L0", cursor=ListCursor("Q0.3", 0))
        water_only = (
            _quest(0, 3, location="Vault 13", text="Find the water chip.",
                   water_chip=True),
        )
        renders = {}
        for name, days, countdown in (
            ("running", 137, True),
            ("depleted", 0, True),
            ("secured", 42, False),
        ):
            surface = _render(_state(water_only, days=days, countdown=countdown), focus)
            renders[name] = pygame.image.tostring(surface, "RGB")

        self.assertNotEqual(renders["running"], renders["depleted"])
        self.assertNotEqual(renders["running"], renders["secured"])
        self.assertNotEqual(renders["depleted"], renders["secured"])

    def test_divergent_state_strikes_the_row_and_keeps_the_day_count(self) -> None:
        """GVAR > 2: struck through *and* a live day count on screen.

        The two engine rules disagree above 2 and both are reported. This
        renders differently from the secured state (which must show no
        number at all), which is the visible consequence.
        """
        divergent = (
            _quest(0, 3, location="Vault 13", text="Find the water chip.",
                   completed=True, water_chip=True),
        )
        focus = _focus(location_key="L0", cursor=ListCursor("Q0.3", 0))
        divergent_surface = _render(_state(divergent, days=90, countdown=True), focus)
        secured_surface = _render(_state(divergent, days=90, countdown=False), focus)
        self.assertNotEqual(
            pygame.image.tostring(divergent_surface, "RGB"),
            pygame.image.tostring(secured_surface, "RGB"),
        )
        # And the projection agrees about which label each one carries.
        self.assertEqual(
            quest_list.water_state(
                _state(divergent, days=90, countdown=True).player
            ).label,
            "WATER: 90 DAYS",
        )
        self.assertEqual(
            quest_list.water_state(
                _state(divergent, days=90, countdown=False).player
            ).label,
            quest_list.WATER_SECURED,
        )

    def test_empty_text_renders_the_no_text_marker(self) -> None:
        broken = (_quest(5, 2, location="Necropolis", text=""),)
        surface = _render(
            _state(broken),
            _focus(location_key="L5", cursor=ListCursor("Q5.2", 0)),
        )
        # A row was drawn: the placeholder is visible, not a blank line.
        self.assertGreater(_lit_pixel_count(surface), 0)
        rows = quest_list.build_quest_rows(broken, 5)
        self.assertEqual(rows[0].label, quest_list.NO_TEXT_LABEL)

    def test_a_location_key_that_does_not_decode_falls_back_to_level_one(
        self,
    ) -> None:
        state = _state(VAULT13)
        level_one = _render(state, _focus(cursor=ListCursor("L0", 0)))
        bogus = _render(
            state, _focus(cursor=ListCursor("L0", 0), location_key="not-a-key")
        )
        self.assertEqual(
            pygame.image.tostring(level_one, "RGB"),
            pygame.image.tostring(bogus, "RGB"),
        )

    def test_drilling_into_an_unreported_location_shows_the_empty_state(self) -> None:
        # Location 1 is one of the engine's four all-zero locations, so the
        # server never reports it.
        surface = _render(_state(VAULT13), _focus(location_key="L1"))
        empty = _render(_state(()), _focus())
        self.assertEqual(
            pygame.image.tostring(surface, "RGB"),
            pygame.image.tostring(empty, "RGB"),
        )


class WrapTests(unittest.TestCase):
    def test_long_text_wraps_rather_than_truncating(self) -> None:
        long_text = (
            "Recover the water chip from the necropolis before the vault "
            "runs dry and everyone you have ever known dies of thirst."
        )
        list_rect = archives.list_rect_for(_body_rect())
        lines = archives.wrap_label(
            long_text, list_rect.width - 2 * list_geometry.ROW_PAD_X,
            list_geometry.ROW_SIZE,
        )
        self.assertGreater(len(lines), 1, "a long line must wrap")
        # No text is lost: rejoining the lines reproduces the words.
        self.assertEqual(" ".join(lines).split(), long_text.split())

    def test_a_wrapped_row_is_taller_than_a_single_line_row(self) -> None:
        self.assertGreater(
            archives.quest_row_height(3, with_water=False),
            archives.quest_row_height(1, with_water=False),
        )

    def test_the_water_row_is_taller_than_the_same_row_without_it(self) -> None:
        self.assertGreater(
            archives.quest_row_height(1, with_water=True),
            archives.quest_row_height(1, with_water=False),
        )

    def test_short_label_stays_one_line(self) -> None:
        lines = archives.wrap_label("Help Saul.", 400, list_geometry.ROW_SIZE)
        self.assertEqual(lines, ("Help Saul.",))

    def test_empty_label_wraps_to_nothing(self) -> None:
        self.assertEqual(archives.wrap_label("", 400, list_geometry.ROW_SIZE), ())

    def test_nonpositive_width_returns_the_label_unsplit(self) -> None:
        self.assertEqual(archives.wrap_label("abc def", 0, 14), ("abc def",))

    def test_an_unbreakably_long_word_is_left_overlong(self) -> None:
        word = "W" * 200
        self.assertEqual(archives.wrap_label(word, 50, 14), (word,))


class LongScrollTests(unittest.TestCase):
    def _many_locations(self) -> tuple[Quest, ...]:
        return tuple(
            _quest(index, 0, location=f"Location {index}", text=f"Quest {index}.")
            for index in range(12)
        )

    def test_level_one_scrolls_and_keeps_the_selection_visible(self) -> None:
        quests = self._many_locations()
        rows = quest_list.build_location_rows(quests)
        list_rect = archives.list_rect_for(_body_rect())
        row_height = archives.row_height_fn(list_rect, "", False)
        from companion_app.ui import scroll_list

        for target in (rows[0], rows[len(rows) // 2], rows[-1]):
            cursor = scroll_list.resolve_cursor(
                rows, ListCursor(target.key, rows.index(target))
            )
            visible = scroll_list.visible(
                rows, cursor, list_rect.height, row_height
            )
            self.assertIn(
                target.key,
                [row.key for _i, row in visible],
                "the selected row must always be inside the viewport",
            )

    def test_a_long_level_two_list_renders_and_scrolls(self) -> None:
        long_location = tuple(
            _quest(7, slot, location="Boneyard",
                   text=f"A reasonably wordy Boneyard quest number {slot}.")
            for slot in range(9)
        )
        state = _state(long_location)
        first = _render(
            state,
            _focus(activated=True, cursor=ListCursor("Q7.0", 0), location_key="L7"),
        )
        last = _render(
            state,
            _focus(activated=True, cursor=ListCursor("Q7.8", 8), location_key="L7"),
        )
        self.assertNotEqual(
            pygame.image.tostring(first, "RGB"),
            pygame.image.tostring(last, "RGB"),
            "scrolling to the end must change the screen",
        )

    def test_rows_never_draw_past_the_body(self) -> None:
        """pygame clips silently, so overflow leaves no error to catch."""
        quests = self._many_locations()
        state = _state(quests)
        surface = _render(
            state,
            _focus(activated=True, cursor=ListCursor("L0", 0)),
        )
        body = _body_rect()
        for y in range(body.bottom, SURFACE_SIZE[1]):
            for x in range(SURFACE_SIZE[0]):
                self.assertEqual(
                    tuple(surface.get_at((x, y))[:3]),
                    (0, 0, 0),
                    f"drew below the body at ({x},{y})",
                )


class FocusPlumbingTests(unittest.TestCase):
    def test_focus_for_hands_quests_its_own_cursor(self) -> None:
        ui = sections.default_sections_ui()
        ui = sections.SectionsUiState(
            status=ui.status,
            automaps=ui.automaps,
            archives=ui.archives,
            activated=True,
            inventory_cursor=ListCursor("inv", 1),
            quest_cursor=ListCursor("L3", 2),
            quest_location_key="L3",
        )
        focus = sections.focus_for(ui, Page.ARCHIVES, ARCHIVES_QUESTS)
        self.assertEqual(focus.cursor, ListCursor("L3", 2))
        self.assertEqual(focus.location_key, "L3")

    def test_focus_for_hands_inventory_its_own_cursor(self) -> None:
        ui = sections.default_sections_ui()
        ui = sections.SectionsUiState(
            status=ui.status,
            automaps=ui.automaps,
            archives=ui.archives,
            activated=True,
            inventory_cursor=ListCursor("inv", 1),
            quest_cursor=ListCursor("L3", 2),
            quest_location_key="L3",
        )
        focus = sections.focus_for(ui, Page.STATUS, sections.STATUS_INVENTORY)
        self.assertEqual(focus.cursor, ListCursor("inv", 1))
        self.assertEqual(
            focus.location_key, "", "depth must not leak to a non-drillable list"
        )

    def test_holodisks_gets_no_depth_even_while_quests_is_drilled(self) -> None:
        ui = sections.default_sections_ui()
        ui = sections.SectionsUiState(
            status=ui.status,
            automaps=ui.automaps,
            archives=ui.archives,
            quest_location_key="L3",
        )
        focus = sections.focus_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS)
        self.assertEqual(focus.location_key, "")


if __name__ == "__main__":
    unittest.main()
