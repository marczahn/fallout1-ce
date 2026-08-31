"""TASK-025 ARCHIVES/HOLODISKS: projection, navigation, reader, encoding.

Follows the project's habits: select state explicitly rather than driving the
UI to reach it, keep the pure layers pygame-free, and assert pixels only where
rendering is the thing under test.

**What is deliberately NOT tested here.** The sentinel rules (`**END-DISK**`
ends the disk, `**END-PAR**` becomes a blank line) are a *backend* invariant in
`companionHolodiskBody`, which has no unit-test target. The reader renders
whatever it is handed, so an app-side "the sentinel is not rendered" test would
only prove the app is obedient — and adding a client-side sentinel filter to
make such a test meaningful would duplicate the rule and weaken it. That
invariant is asserted in `scripts/companion_smoke_test.py` and by the
side-by-side live check. What *is* tested here is the app's half: an empty line
arriving from the wire renders as blank space.
"""
from __future__ import annotations

import json
import unittest

import pygame

from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderRightEvent,
    PageButtonEvent,
)
from companion_app.net.client import NetworkClient
from companion_app.net.framing import read_line
from companion_app.state import AppState, ConnectionState, Holodisk
from companion_app.ui import holodisk_list, sections
from companion_app.ui.pages import archives
from companion_app.ui.scroll_list import ListCursor
from companion_app.ui.sections import (
    ARCHIVES_HOLODISKS,
    ARCHIVES_QUESTS,
    Page,
    SubSectionFocus,
)

_BODY_RECT = pygame.Rect(0, 112, 480, 688)
_CONTENT_RECT = pygame.Rect(0, 56, 480, 744)


def _state(disks=()) -> AppState:
    state = AppState()
    state.connection = ConnectionState.READY
    state.player.holodisks = list(disks)
    return state


def _client(state: AppState) -> NetworkClient:
    """A client wired to ``state`` but never connected — parsing only."""
    return NetworkClient(host="127.0.0.1", port=28080, password="testpw", state=state)


def _disk(index: int, title: str = "", body: tuple[str, ...] = ()) -> Holodisk:
    return Holodisk(index=index, title=title or f"DISK {index}", body=body)


def _render(state: AppState, focus: SubSectionFocus) -> pygame.Surface:
    pygame.init()
    surface = pygame.Surface((480, 800))
    surface.fill((0, 0, 0))
    archives.ArchivesSection().render(
        surface, _CONTENT_RECT, state, ARCHIVES_HOLODISKS, focus
    )
    return surface


def _first_text_row_signature(surface: pygame.Surface) -> tuple:
    """Pixels of the reader's first document line — what the eye actually sees.

    Hashes rendered pixels rather than inspecting state, because the whole
    point of the regression this guards is that the state moved while the
    screen did not.
    """
    text_rect = archives.reader_text_rect(_BODY_RECT)
    return tuple(
        surface.get_at((x, y))[:3]
        for y in range(text_rect.top, text_rect.top + archives._READER_LINE_HEIGHT)
        for x in range(text_rect.left, text_rect.right, 3)
    )


def _render_single_line_signature(line: str) -> tuple:
    """The signature `_first_text_row_signature` would produce for ``line``."""
    text_rect = archives.reader_text_rect(_BODY_RECT)
    surface = pygame.Surface((480, 800))
    surface.fill((0, 0, 0))
    archives.font.draw_text_left(
        surface,
        line,
        (text_rect.left + archives.list_geometry.ROW_PAD_X, text_rect.top),
        archives._READER_SIZE,
        archives.palette.FOREGROUND,
    )
    return _first_text_row_signature(surface)


def _lit_rows(surface: pygame.Surface, top: int, bottom: int) -> list[int]:
    """Y coordinates in ``[top, bottom)`` that have any non-black pixel."""
    return [
        y
        for y in range(top, min(bottom, 800))
        if any(surface.get_at((x, y))[:3] != (0, 0, 0) for x in range(0, 480, 2))
    ]


# ── a. level-1 projection ────────────────────────────────────────────


class HolodiskProjectionTests(unittest.TestCase):
    def test_rows_are_ordered_by_engine_table_index(self) -> None:
        rows = holodisk_list.project(
            [_disk(11), _disk(1), _disk(5)]
        )
        self.assertEqual([r.index for r in rows], [1, 5, 11])

    def test_unresolvable_title_becomes_a_visible_label_not_a_dropped_row(self) -> None:
        rows = holodisk_list.project([Holodisk(index=3, title="", body=("x",))])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, holodisk_list.NO_TITLE_LABEL)

    def test_keys_round_trip(self) -> None:
        for index in range(18):
            key = holodisk_list.holodisk_key(index)
            self.assertEqual(holodisk_list.holodisk_index_from_key(key), index)

    def test_titles_are_not_suffixed(self) -> None:
        """Unlike transmissions: all 18 holodisk titles are distinct.

        If two ever collide the index still keys the row, so a suffix would be
        cosmetic — and adding one now would be untested speculation.
        """
        rows = holodisk_list.project(
            [_disk(0, "Same Tape"), _disk(1, "Same Tape")]
        )
        self.assertEqual([r.title for r in rows], ["Same Tape", "Same Tape"])
        self.assertNotEqual(rows[0].key, rows[1].key)


# ── c. blank lines ───────────────────────────────────────────────────


class BlankLineTests(unittest.TestCase):
    """`**END-PAR**` arrives already translated to `""` and must draw as air."""

    def test_empty_body_line_survives_as_a_blank_display_line(self) -> None:
        pygame.init()
        pygame.display.set_mode((480, 800))
        lines = archives.reader_display_lines(_disk(0, body=("one", "", "two")), _BODY_RECT)
        self.assertEqual(lines, ["one", "", "two"])

    def test_blank_line_still_occupies_one_line_of_height(self) -> None:
        self.assertEqual(archives.wrap_body_line("", 400, 9), ("",))

    def test_a_literal_marker_would_be_visible_if_it_ever_arrived(self) -> None:
        """Guards the *contract*, not the app: markers must never be sent.

        The app renders what it is given, so if a `**END-PAR**` literal ever
        reaches the reader it shows up rather than being quietly swallowed.
        That is deliberate — silent filtering here would hide a server bug.
        """
        pygame.init()
        pygame.display.set_mode((480, 800))
        lines = archives.reader_display_lines(_disk(0, body=("**END-PAR**",)), _BODY_RECT)
        self.assertEqual(lines, ["**END-PAR**"])


# ── d. unreadable disk ───────────────────────────────────────────────


class UnreadableDiskTests(unittest.TestCase):
    def test_empty_body_renders_a_visible_failure(self) -> None:
        """Something is drawn **below the title**, which is always drawn.

        The first version counted lit pixels across the whole body, so the
        title alone satisfied it and deleting `DISK UNREADABLE` would not have
        failed it. Caught by the code review.
        """
        state = _state([_disk(3, "Sophia Tape", body=())])
        surface = _render(
            state,
            SubSectionFocus(
                activated=True,
                cursor=ListCursor(),
                location_key=holodisk_list.holodisk_key(3),
            ),
        )
        text_rect = archives.reader_text_rect(_BODY_RECT)
        self.assertGreater(
            len(_lit_rows(surface, text_rect.top, text_rect.bottom)),
            0,
            "no failure message drawn in the document area",
        )

    def test_a_readable_disk_and_an_unreadable_one_do_not_look_alike(self) -> None:
        def body_pixels(disk):
            surface = _render(
                _state([disk]),
                SubSectionFocus(
                    activated=True,
                    cursor=ListCursor(),
                    location_key=holodisk_list.holodisk_key(disk.index),
                ),
            )
            rect = archives.reader_text_rect(_BODY_RECT)
            return _lit_rows(surface, rect.top, rect.bottom)

        self.assertNotEqual(
            body_pixels(_disk(3, "Sophia Tape", body=())),
            body_pixels(_disk(3, "Sophia Tape", body=("real text",))),
        )

    def test_unreadable_disk_still_appears_in_the_list(self) -> None:
        rows = holodisk_list.list_rows([_disk(3, "Sophia Tape", body=())])
        self.assertEqual(len(rows), 1)

    def test_a_malformed_body_is_rejected_whole_not_patched_up(self) -> None:
        """All-or-nothing survives the client, not just the server.

        The first version only asserted that an *already* empty body draws
        nothing, and said so — it would have passed while the client silently
        dropped a bad line and rendered a document with a hole in it that
        looked complete. Code review caught that; this is the real test.
        """
        state = _state()
        client = _client(state)
        self.addCleanup(client.cleanup)

        client._apply_holodisks(
            {"holodisks": [{"index": 3, "title": "T", "body": ["first", None, "last"]}]}
        )
        self.assertEqual(state.player.holodisks[0].body, ())

        client._apply_holodisks(
            {"holodisks": [{"index": 3, "title": "T", "body": "not a list"}]}
        )
        self.assertEqual(state.player.holodisks[0].body, ())

    def test_a_clean_body_is_kept_intact(self) -> None:
        """The other half of all-or-nothing: valid bodies are not over-rejected."""
        state = _state()
        client = _client(state)
        self.addCleanup(client.cleanup)
        client._apply_holodisks(
            {"holodisks": [{"index": 3, "title": "T", "body": ["a", "", "b"]}]}
        )
        self.assertEqual(state.player.holodisks[0].body, ("a", "", "b"))


# ── e/j. navigation: scroll, drill, back ─────────────────────────────


class ReaderNavigationTests(unittest.TestCase):
    def setUp(self) -> None:
        ui = sections.default_sections_ui()
        # Cycle to HOLODISKS the way the encoder does, matching
        # `test_transmissions._ui` rather than reaching past the public API.
        seg = sections.for_page(ui, Page.ARCHIVES)
        while seg.selected_key != ARCHIVES_HOLODISKS:
            seg = sections.cycle_next(seg)
        self.ui = sections.with_page(ui, Page.ARCHIVES, seg)
        # Comfortably longer than a screenful (52 lines at the reader's size),
        # or there is nothing to scroll and the navigation tests assert
        # nothing. A 40-line fixture passed only because a larger type size
        # briefly made 40 lines overflow — see `test_a_document_that_fits`.
        self.disk = _disk(0, "FEV Experiment Tape", body=tuple(f"line {n}" for n in range(300)))
        self.state = _state([self.disk])

    def _rows(self, ui):
        drill = sections.drill_key_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS)
        if drill:
            return archives.reader_scroll_rows(self.disk, _BODY_RECT)
        return holodisk_list.list_rows(self.state.player.holodisks)

    def _send(self, ui, event):
        return sections.handle_input(ui, Page.ARCHIVES, event, rows=self._rows(ui))

    def test_confirm_activates_then_drills_into_the_document(self) -> None:
        ui = self._send(self.ui, ConfirmEvent())
        self.assertTrue(ui.activated)
        self.assertEqual(ui.holodisk_drill_key, "")

        ui = self._send(ui, ConfirmEvent())
        self.assertEqual(ui.holodisk_drill_key, holodisk_list.holodisk_key(0))

    def test_encoder_scrolls_one_line_at_a_time(self) -> None:
        ui = self._send(self.ui, ConfirmEvent())
        ui = self._send(ui, ConfirmEvent())
        rows = self._rows(ui)

        first = sections.cursor_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS)
        self.assertEqual(
            sections.scroll_list.resolve_cursor(rows, first).selected_index, 0
        )

        for expected in (1, 2, 3):
            ui = self._send(ui, EncoderRightEvent())
            cursor = sections.cursor_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS)
            self.assertEqual(cursor.selected_index, expected)

    def test_one_click_moves_the_page_immediately(self) -> None:
        """The regression that live QA found and the first suite missed.

        The reader draws no cursor, so "the cursor moved" is not observable —
        only "the page moved" is. The original test asserted the former and
        passed while the document sat still for 26 clicks.
        """
        long_disk = _disk(0, "FEV", body=tuple(f"line {n}" for n in range(300)))
        state = _state([long_disk])
        key = holodisk_list.holodisk_key(0)

        def top_line(index: int) -> str:
            rows = archives.reader_scroll_rows(long_disk, _BODY_RECT)
            cursor = ListCursor(selected_key=rows[index].key, selected_index=index)
            surface = _render(
                state,
                SubSectionFocus(activated=True, cursor=cursor, location_key=key),
            )
            return _first_text_row_signature(surface)

        self.assertNotEqual(
            top_line(0), top_line(1), "one encoder click did not move the page"
        )

    def test_every_scroll_position_renders_a_different_page(self) -> None:
        """No dead zone at either end — the other half of the same bug.

        Renders rather than reading `reader_display_lines`: the first version
        derived its answer from the data, so a renderer that always drew line
        zero would have passed it. Sampled across the range, including the
        last position, rather than all 264 — the render is the slow part and
        the failure mode is a *stuck* window, which sampling catches.
        """
        long_disk = _disk(0, "FEV", body=tuple(f"line {n}" for n in range(300)))
        state = _state([long_disk])
        rows = archives.reader_scroll_rows(long_disk, _BODY_RECT)
        key = holodisk_list.holodisk_key(0)

        seen = set()
        probes = [0, 1, 2, len(rows) // 2, len(rows) - 2, len(rows) - 1]
        for index in probes:
            cursor = ListCursor(selected_key=rows[index].key, selected_index=index)
            surface = _render(
                state,
                SubSectionFocus(activated=True, cursor=cursor, location_key=key),
            )
            seen.add(_first_text_row_signature(surface))
        self.assertEqual(len(seen), len(probes), "the rendered page repeated itself")

    def test_the_last_scroll_position_renders_the_end_of_the_document(self) -> None:
        long_disk = _disk(0, "FEV", body=tuple(f"line {n}" for n in range(300)))
        lines = archives.reader_display_lines(long_disk, _BODY_RECT)
        rows = archives.reader_scroll_rows(long_disk, _BODY_RECT)
        last = len(rows) - 1
        cursor = ListCursor(selected_key=rows[last].key, selected_index=last)
        surface = _render(
            _state([long_disk]),
            SubSectionFocus(
                activated=True, cursor=cursor, location_key=holodisk_list.holodisk_key(0)
            ),
        )
        # The final window starts at the line that puts the last line at the
        # bottom — so the top line drawn is exactly `lines[last]`.
        expected = _render_single_line_signature(lines[last])
        self.assertEqual(_first_text_row_signature(surface), expected)

    def test_a_cursor_from_a_longer_disk_cannot_scroll_past_a_shorter_one(self) -> None:
        """Switching disks leaves a stale cursor; it must clamp, not crash."""
        short = _disk(1, "Security Tape", body=("only line",))
        stale = ListCursor(selected_key=holodisk_list.line_key(250), selected_index=250)
        surface = _render(
            _state([short]),
            SubSectionFocus(
                activated=True, cursor=stale, location_key=holodisk_list.holodisk_key(1)
            ),
        )
        rect = archives.reader_text_rect(_BODY_RECT)
        self.assertGreater(
            len(_lit_rows(surface, rect.top, rect.bottom)),
            0,
            "a stale cursor blanked the document",
        )

    def test_a_disk_that_vanishes_mid_read_falls_back_to_the_list(self) -> None:
        """The server stops reporting the disk while it is open."""
        surface = _render(
            _state([_disk(5, "Other Tape", body=("x",))]),
            SubSectionFocus(
                activated=True,
                cursor=ListCursor(),
                location_key=holodisk_list.holodisk_key(11),
            ),
        )
        self.assertGreater(
            len(_lit_rows(surface, 112, 800)), 0, "vanished disk blanked the screen"
        )

    def test_scrolling_never_runs_past_the_last_line(self) -> None:
        pygame.init()
        pygame.display.set_mode((480, 800))
        long_disk = _disk(0, "FEV", body=tuple(f"line {n}" for n in range(300)))
        lines = archives.reader_display_lines(long_disk, _BODY_RECT)
        rows = archives.reader_scroll_rows(long_disk, _BODY_RECT)
        visible = archives.reader_visible_line_count(_BODY_RECT)
        # The final position still fills the screen: no scrolling into black.
        self.assertEqual(len(rows) - 1 + visible, len(lines))

    def test_a_document_that_fits_has_exactly_one_scroll_position(self) -> None:
        """A document shorter than the viewport does not scroll at all.

        Worth an explicit test: at the reader's size 52 lines fit, so 13 of
        the 18 real disks never scroll, and "the encoder does nothing here" is
        correct behaviour rather than the bug live QA found.
        """
        pygame.init()
        pygame.display.set_mode((480, 800))
        self.assertEqual(len(archives.reader_scroll_rows(_disk(1, body=("one line",)), _BODY_RECT)), 1)
        short = _disk(2, body=tuple(f"line {n}" for n in range(40)))
        self.assertEqual(len(archives.reader_scroll_rows(short, _BODY_RECT)), 1)

    def test_back_returns_to_the_list_on_the_disk_just_read(self) -> None:
        ui = self._send(self.ui, ConfirmEvent())
        ui = self._send(ui, ConfirmEvent())
        ui = self._send(ui, BackEvent())
        self.assertEqual(ui.holodisk_drill_key, "")
        self.assertTrue(ui.activated)
        self.assertEqual(
            sections.cursor_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS).selected_key,
            holodisk_list.holodisk_key(0),
        )

    def test_back_again_deactivates(self) -> None:
        ui = self._send(self.ui, ConfirmEvent())
        ui = self._send(ui, ConfirmEvent())
        ui = self._send(ui, BackEvent())
        ui = self._send(ui, BackEvent())
        self.assertFalse(ui.activated)

    def test_leaving_the_section_clears_holodisk_depth(self) -> None:
        """The F4 trap, asserted directly.

        `deactivated()` and the level-1 `Back` branch used to clear the drill
        keys by naming them literally, so a third drillable sub-section would
        have kept its depth across a section switch. Both now derive the reset
        from the registry.
        """
        ui = self._send(self.ui, ConfirmEvent())
        ui = self._send(ui, ConfirmEvent())
        self.assertNotEqual(ui.holodisk_drill_key, "")

        ui = sections.deactivated(ui)
        self.assertEqual(ui.holodisk_drill_key, "")
        self.assertEqual(ui.quest_drill_key, "")
        self.assertEqual(ui.transmission_drill_key, "")

    def test_every_drillable_subsection_is_covered_by_the_reset(self) -> None:
        """Structural: the reset must name every registered drill field."""
        cleared = sections._cleared_drill_keys()
        self.assertEqual(
            set(cleared), set(sections._DRILL_FIELD_BY_SUBSECTION.values())
        )

    def test_holodisk_cursor_is_not_the_quest_or_transmission_cursor(self) -> None:
        ui = self._send(self.ui, ConfirmEvent())
        self.assertEqual(
            sections.cursor_for(ui, Page.ARCHIVES, ARCHIVES_QUESTS), ListCursor()
        )


# ── f. the single-line disk ──────────────────────────────────────────


class SingleLineDiskTests(unittest.TestCase):
    """Index 1, "Security Tape", is one 38-byte line and nothing else."""

    SECURITY_TAPE = "Security override Gamma Omicron Delta."

    def _reader_surface(self) -> pygame.Surface:
        state = _state([_disk(1, "Security Tape", body=(self.SECURITY_TAPE,))])
        return _render(
            state,
            SubSectionFocus(
                activated=True,
                cursor=ListCursor(),
                location_key=holodisk_list.holodisk_key(1),
            ),
        )

    def test_it_fits_on_one_line(self) -> None:
        pygame.init()
        pygame.display.set_mode((480, 800))
        self.assertEqual(
            len(archives.wrap_body_line(self.SECURITY_TAPE, 398, archives._READER_SIZE)),
            1,
        )

    def test_no_scroll_gutter_is_drawn(self) -> None:
        surface = self._reader_surface()
        inner = archives.list_geometry.body_inner_rect(_BODY_RECT)
        gutter_x = inner.right - archives.list_geometry.GUTTER_WIDTH + 1
        lit = [
            y
            for y in range(inner.top, inner.bottom)
            if surface.get_at((gutter_x, y))[:3] != (0, 0, 0)
        ]
        self.assertEqual(lit, [], "a fitting document drew a scroll gutter")

    def test_nothing_is_drawn_below_the_single_line(self) -> None:
        surface = self._reader_surface()
        inner = archives.list_geometry.body_inner_rect(_BODY_RECT)
        first_line_top = inner.top + archives._DISK_TITLE_SIZE + archives._READER_HEADER_GAP
        below = _lit_rows(
            surface, first_line_top + 2 * archives._READER_LINE_HEIGHT, inner.bottom
        )
        self.assertEqual(below, [], "content drawn below the only line")


# ── g. the title header ──────────────────────────────────────────────


class ReaderHeaderTests(unittest.TestCase):
    def test_the_title_is_drawn_above_the_document(self) -> None:
        state = _state([_disk(9, "Sophia Tape", body=("body line",))])
        surface = _render(
            state,
            SubSectionFocus(
                activated=True,
                cursor=ListCursor(),
                location_key=holodisk_list.holodisk_key(9),
            ),
        )
        inner = archives.list_geometry.body_inner_rect(_BODY_RECT)
        header = _lit_rows(
            surface, inner.top, inner.top + archives._DISK_TITLE_SIZE + 8
        )
        self.assertGreater(len(header), 0, "no title header drawn")


# ── h. authored whitespace ───────────────────────────────────────────


class AuthoredWhitespaceTests(unittest.TestCase):
    """Disks 5 and 11 align with leading spaces; wrapping must keep them."""

    TIMESTAMP = " " * 52 + "0000 - 0004"
    MEASUREMENT = "    Muscle Mass: 77.41% "

    def setUp(self) -> None:
        pygame.init()
        pygame.display.set_mode((480, 800))

    def test_leading_indent_survives(self) -> None:
        out = archives.wrap_body_line(self.TIMESTAMP, 398, 9)
        self.assertTrue(out[0].startswith(" " * 52), repr(out[0]))

    def test_short_indented_line_is_untouched(self) -> None:
        out = archives.wrap_body_line(self.MEASUREMENT, 398, 9)
        self.assertEqual(out, (self.MEASUREMENT.rstrip(" "),))

    def test_continuations_inherit_the_indent(self) -> None:
        line = "    " + "word " * 60
        out = archives.wrap_body_line(line, 200, 9)
        self.assertGreater(len(out), 1, "expected this to wrap")
        for part in out:
            self.assertTrue(part.startswith("    "), repr(part))

    def test_wrap_label_would_have_destroyed_it(self) -> None:
        """Why `wrap_body_line` exists at all — pins the difference."""
        naive = archives.wrap_label(self.TIMESTAMP, 398, 9)
        self.assertFalse(naive[0].startswith(" "))


# ── i. mid-session updates ───────────────────────────────────────────


class MidSessionTests(unittest.TestCase):
    def test_a_disk_found_mid_session_appears_without_a_restart(self) -> None:
        state = _state([_disk(0, "FEV Experiment Tape", body=("a",))])
        client = _client(state)
        self.addCleanup(client.cleanup)

        before = _render(
            state, SubSectionFocus(activated=True, cursor=ListCursor())
        )

        client._apply_holodisks(
            {
                "holodisks": [
                    {"index": 0, "title": "FEV Experiment Tape", "body": ["a"]},
                    {"index": 1, "title": "Security Tape", "body": ["b"]},
                ]
            }
        )
        self.assertEqual([d.index for d in state.player.holodisks], [0, 1])
        self.assertEqual(state.player.holodisks[1].body, ("b",))

        # And the new disk is actually **on screen** — asserting the state
        # alone would pass against a renderer holding a cached list.
        after = _render(state, SubSectionFocus(activated=True, cursor=ListCursor()))
        self.assertNotEqual(
            _lit_rows(before, 112, 800),
            _lit_rows(after, 112, 800),
            "the list did not redraw after a mid-session update",
        )


# ── client parsing, including k. the encoding regression ─────────────


class ClientParsingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.state = _state()
        self.client = _client(self.state)
        self.addCleanup(self.client.cleanup)

    def test_missing_body_degrades_to_empty(self) -> None:
        """A schemaVersion 13 server sends the kind but no `body`."""
        self.client._apply_holodisks({"holodisks": [{"index": 2, "title": "T"}]})
        self.assertEqual(self.state.player.holodisks[0].body, ())

    def test_non_string_body_entries_invalidate_the_whole_document(self) -> None:
        """Was `..._are_dropped_not_coerced`, which asserted the bug.

        Dropping bad entries yields a document with a hole in it that renders
        as complete — the very failure the server's all-or-nothing assembly
        exists to prevent. Code review caught it; the contract now holds on
        both sides of the wire. See `UnreadableDiskTests` for the pair.
        """
        self.client._apply_holodisks(
            {"holodisks": [{"index": 2, "title": "T", "body": ["a", None, 7, "b"]}]}
        )
        self.assertEqual(self.state.player.holodisks[0].body, ())

    def test_null_title_never_becomes_the_string_none(self) -> None:
        """The TASK-016 bug."""
        self.client._apply_holodisks(
            {"holodisks": [{"index": 2, "title": None, "body": []}]}
        )
        self.assertEqual(self.state.player.holodisks[0].title, "")

    def test_bool_index_is_rejected(self) -> None:
        self.client._apply_holodisks({"holodisks": [{"index": True, "title": "T"}]})
        self.assertEqual(self.state.player.holodisks, [])

    # k. the encoding regression, in two halves.

    def test_escaped_bullet_survives_the_wire_and_is_substituted(self) -> None:
        """The engine now emits `\\u2022`; the app must decode and draw it.

        This is the app-side half of the non-ASCII decision. The engine half
        (raw `0x95` -> `\\u2022`) is not reachable from Python and is proved by
        the B1 scratch check and the smoke script.
        """
        payload = {"holodisks": [{"index": 0, "title": "FEV", "body": ["• Log Date"]}]}
        wire = (json.dumps({"type": "update", "kind": "player.holodisks",
                            "payload": payload}) + "\n").encode("utf-8")

        msg, rest = read_line(bytearray(wire))
        self.assertIsNotNone(msg, "escaped bullet failed to decode")
        self.assertEqual(rest, bytearray())

        self.client._apply_holodisks(msg["payload"])
        body = self.state.player.holodisks[0].body
        self.assertEqual(body, ("• Log Date",))

        # The vendored face has no U+2022 glyph, so the reader substitutes
        # one it can actually draw rather than showing a box.
        self.assertEqual(holodisk_list.renderable(body[0]), "* Log Date")

    def test_a_raw_high_byte_is_still_rejected_and_that_is_correct(self) -> None:
        """The fix belongs in the producer, never in the parser.

        Loosening `read_line` would defeat the framing contract the whole
        protocol rests on. The first draft of this test asserted the opposite;
        the reviewer gate caught it.
        """
        wire = b'{"type":"update","kind":"player.holodisks","payload":{"holodisks":[' \
               b'{"index":0,"title":"FEV","body":["\x95 Log Date"]}]}}\n'
        msg, _rest = read_line(bytearray(wire))
        self.assertIsNone(msg, "a raw non-UTF-8 byte must not parse")


# ── row-key disjointness ─────────────────────────────────────────────


class RowKeyDisjointnessTests(unittest.TestCase):
    def test_a_holodisk_key_never_decodes_as_a_transmission(self) -> None:
        from companion_app.ui import transmission_list

        for index in range(18):
            key = holodisk_list.holodisk_key(index)
            self.assertIsNone(transmission_list.transmission_index_from_key(key))

    def test_a_transmission_key_never_decodes_as_a_holodisk(self) -> None:
        from companion_app.ui import transmission_list

        for index in range(3, 14):
            key = transmission_list.transmission_key(index)
            self.assertIsNone(holodisk_list.holodisk_index_from_key(key))

    def test_a_body_line_key_never_decodes_as_a_disk(self) -> None:
        """"HL3" shares its first character with "H3" and must not collide."""
        for number in range(200):
            self.assertIsNone(
                holodisk_list.holodisk_index_from_key(holodisk_list.line_key(number))
            )


# ── F8. no audio on this path ────────────────────────────────────────


class _RecordingSink:
    """Fails loudly if the holodisk path touches it."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str):
        def record(*args, **kwargs):
            self.calls.append(name)
            return None

        return record

    @property
    def is_playing(self) -> bool:
        self.calls.append("is_playing")
        return False

    @property
    def is_paused(self) -> bool:
        self.calls.append("is_paused")
        return False


class NoAudioTests(unittest.TestCase):
    """Holodisks are documents. Nothing here may reach the audio layer.

    Behavioural rather than an import check: `ui/pages/archives.py` legitimately
    imports `audio.equalizer` for the transmission player and always will, so
    asserting "this module imports no audio" would be untestable there. The
    pure projection module *can* carry the import assertion.
    """

    def test_holodisk_list_imports_no_audio(self) -> None:
        import inspect

        source = inspect.getsource(holodisk_list)
        self.assertNotIn("companion_app.audio", source)
        self.assertNotIn("mixer", source)

    def test_rendering_and_navigating_never_touches_the_sink(self) -> None:
        sink = _RecordingSink()
        disk = _disk(0, "FEV Experiment Tape", body=tuple(f"line {n}" for n in range(40)))
        state = _state([disk])

        pygame.init()
        surface = pygame.Surface((480, 800))
        section = archives.ArchivesSection(sink)

        for focus in (
            SubSectionFocus(activated=False, cursor=ListCursor()),
            SubSectionFocus(activated=True, cursor=ListCursor()),
            SubSectionFocus(
                activated=True,
                cursor=ListCursor(),
                location_key=holodisk_list.holodisk_key(0),
            ),
        ):
            section.render(surface, _CONTENT_RECT, state, ARCHIVES_HOLODISKS, focus)

        self.assertEqual(sink.calls, [], f"holodisk path touched the sink: {sink.calls}")


class GlyphSubstitutionTests(unittest.TestCase):
    """Every substitution target must be a glyph the face really draws."""

    def test_targets_are_renderable_and_sources_are_not(self) -> None:
        pygame.init()
        pygame.display.set_mode((480, 800))
        from companion_app.render import font

        face = font.load_font(14)
        for missing, replacement in holodisk_list._GLYPH_SUBSTITUTIONS.items():
            self.assertIsNone(
                face.get_metrics(missing)[0],
                f"{missing!r} is not actually missing; the substitution is dead code",
            )
            self.assertIsNotNone(
                face.get_metrics(replacement)[0],
                f"{replacement!r} has no glyph either",
            )

    def test_the_middle_dot_is_not_used(self) -> None:
        """U+00B7 reports metrics but draws as a filled block in this face.

        Pinned because it is the obvious-looking choice and a metrics check
        alone endorses it. The only way to know was to render disk 0 and look.
        """
        self.assertNotIn("·", holodisk_list._GLYPH_SUBSTITUTIONS.values())


if __name__ == "__main__":
    unittest.main()
