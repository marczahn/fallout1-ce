"""Per-section sub-navigation state (TASK-017).

One module owns every section's sub-section set and every transition
between them, so no page defines its own navigation model. This replaces
both of the models that existed before: the MAP page's segmented header
and the DATA page's bespoke root/detail state.

Navigation has two levels (TASK-018). At the **sub-section row** the
encoder cycles sub-sections and the content switches immediately. A
sub-section whose content has something selectable in it can be
**activated** with ``Confirm``, which hands the encoder to that content;
``Back`` hands it back. Only sub-sections listed in ``ACTIVATABLE`` can be
activated, so ``Confirm`` stays inert everywhere else.

Two rules about what survives what:

* **Selection is preserved per section** — switching sections and coming
  back leaves the previously selected sub-section selected.
* **Activation is never preserved.** Leaving a section always drops back
  to the sub-section row. The *cursor* inside the content is preserved
  though: the deactivated list still shows which row it would resume on,
  so discarding it would make that outline a lie.

TASK-021 **extends** that model rather than replacing it, in two ways:

* **Cursor ownership is per sub-section**, via
  ``_CURSOR_FIELD_BY_SUBSECTION``. It used to be hardwired to the
  inventory, which was fine while the inventory was the only activatable
  sub-section and stopped being fine the moment QUESTS joined it.
* **Activated content may have a second level**, for sub-sections listed
  in ``DRILLABLE``. ``Confirm`` at level 1 drills in; ``Back`` at level 2
  comes back up; ``Back`` at level 1 deactivates as before. So ``Back``
  gains a second meaning, but **only inside a drillable sub-section** —
  this is the one genuinely new gesture rule, and it is written down here
  rather than left implicit.

  Depth is stored as the level-1 *row key*, not an index: it is assigned
  straight from ``ListCursor.selected_key``, so nothing here has to decode
  it and this module keeps importing no projection module. Because the key
  is a pure function of the location index, it is exactly as stable across
  the wholesale quest-list replacement as an index would be.

  Depth is part of activation, so ``deactivated()`` clears it too. The
  documented rule that activation never survives a section switch applies
  unchanged to a two-level list — the *cursors* still survive.

State is immutable and the transitions are pure, so they unit-test
without a display (same contract as ``segmented_header``).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Sequence

from companion_app.input.events import (
    BackEvent,
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
    InputEvent,
)
from companion_app.ui import scroll_list, segmented_header
from companion_app.ui.pages import Page
from companion_app.ui.scroll_list import ListCursor, ListRow
from companion_app.ui.segmented_header import (
    Segment,
    SegmentedHeaderState,
    cycle_next,
    cycle_prev,
)

SECTION_TITLES: dict[Page, str] = {
    Page.STATUS: "STATUS",
    Page.AUTOMAPS: "AUTOMAPS",
    Page.ARCHIVES: "ARCHIVES",
}

# Sub-section keys. Pages match on these, so they are the contract
# between this module and the section renderers.
STATUS_CHARACTER: str = "CHARACTER"
STATUS_INVENTORY: str = "INVENTORY"

AUTOMAPS_LOCAL: str = "LOCAL"
AUTOMAPS_WORLD: str = "WORLD"
AUTOMAPS_ATLAS: str = "ATLAS"

ARCHIVES_QUESTS: str = "QUESTS"
# Holodisks (text documents) and transmissions (replayable cutscenes) are
# DIFFERENT things and are deliberately separate sub-sections. In-game
# they are on different screens entirely -- `PipStatus` lists holodisks
# beside the quests, `PipArchives` lists movies -- and conflating them is
# exactly the mistake TASK-024 was built on before the correction.
ARCHIVES_HOLODISKS: str = "HOLODISKS"
ARCHIVES_TRANSMISSIONS: str = "TRANSMISSIONS"


@dataclass(frozen=True)
class SectionsUiState:
    """Every section's sub-header state, held together immutably.

    Three named fields rather than a ``dict`` field: a dict inside a
    frozen dataclass would still be mutable in place and would silently
    defeat the immutability the rest of the UI state relies on.

    ``activated`` is a single flag rather than one per section on purpose:
    activation must not survive a section switch, so storing it per
    section would encode the opposite of the rule and then need clearing
    anyway.
    """

    status: SegmentedHeaderState
    automaps: SegmentedHeaderState
    archives: SegmentedHeaderState
    activated: bool = False
    inventory_cursor: ListCursor = ListCursor()
    quest_cursor: ListCursor = ListCursor()
    transmission_cursor: ListCursor = ListCursor()
    # Drill-down depth, as the level-1 row key being viewed. ``""`` means
    # level 1. A key rather than an index — see the module docstring.
    #
    # ONE FIELD PER DRILLABLE SUB-SECTION, for the same reason there is one
    # cursor each: a shared anchor lets one sub-section's depth be read as
    # the other's. Not theoretical — TASK-017's
    # ``test_transmissions_gets_no_depth_even_while_quests_is_drilled`` caught
    # exactly that leak when TASK-024 first tried a single shared field.
    # Guarding on ``is_drillable`` is too weak once *both* ARCHIVES
    # sub-sections drill, because then it is true for both.
    # (``quest_drill_key`` was ``quest_location_key`` before TASK-024.)
    quest_drill_key: str = ""
    transmission_drill_key: str = ""


@dataclass(frozen=True)
class SubSectionFocus:
    """What a section renderer needs to draw its content's focus state.

    Passed instead of loose parameters so later consumers (per-type item
    detail, QUESTS, TRANSMISSIONS) extend one dataclass rather than every
    section's signature again.

    ``location_key`` is the drill-down depth for a drillable sub-section
    (``""`` for level 1, or a level-1 row key). It is always empty for a
    sub-section that cannot drill, so a renderer that ignores it behaves
    exactly as before.
    """

    activated: bool
    cursor: ListCursor
    location_key: str = ""


# Sub-sections whose content can take the encoder. Everything absent here
# is why ``Confirm`` is inert on CHARACTER.
ACTIVATABLE: frozenset[tuple[Page, str]] = frozenset(
    {
        (Page.STATUS, STATUS_INVENTORY),
        (Page.ARCHIVES, ARCHIVES_QUESTS),
        (Page.ARCHIVES, ARCHIVES_TRANSMISSIONS),
    }
)

# Activatable sub-sections whose content has a *second* level, reached
# with ``Confirm`` and left with ``Back``. An allow-list rather than a
# per-section flag: the two-step ``Back`` must stay confined to the
# sub-sections that actually have somewhere to go up to, or ``Back`` would
# become unpredictable across the device.
DRILLABLE: frozenset[tuple[Page, str]] = frozenset(
    {
        (Page.ARCHIVES, ARCHIVES_QUESTS),
        # TRANSMISSIONS drills from the disk list into one disk's player.
        # Its level 2 has no list, so the encoder finds no rows to move
        # through and is state-inert there by construction -- the playback
        # controller in `app.py` reads that gesture as a seek instead.
        (Page.ARCHIVES, ARCHIVES_TRANSMISSIONS),
    }
)


def default_sections_ui() -> SectionsUiState:
    """Initial state: each section's first sub-section selected."""
    return SectionsUiState(
        status=segmented_header.create(
            (
                Segment(STATUS_CHARACTER, STATUS_CHARACTER),
                Segment(STATUS_INVENTORY, STATUS_INVENTORY),
            )
        ),
        automaps=segmented_header.create(
            (
                Segment(AUTOMAPS_LOCAL, AUTOMAPS_LOCAL),
                Segment(AUTOMAPS_WORLD, AUTOMAPS_WORLD),
                Segment(AUTOMAPS_ATLAS, AUTOMAPS_ATLAS),
            )
        ),
        archives=segmented_header.create(
            (
                Segment(ARCHIVES_QUESTS, ARCHIVES_QUESTS),
                Segment(ARCHIVES_HOLODISKS, ARCHIVES_HOLODISKS),
                Segment(ARCHIVES_TRANSMISSIONS, ARCHIVES_TRANSMISSIONS),
            )
        ),
    )


_FIELD_BY_PAGE: dict[Page, str] = {
    Page.STATUS: "status",
    Page.AUTOMAPS: "automaps",
    Page.ARCHIVES: "archives",
}

# Which ``SectionsUiState`` cursor field each activatable sub-section owns.
# Same style as ``_FIELD_BY_PAGE``. One cursor per sub-section rather than
# one shared cursor, because two lists sharing an anchor would each clobber
# the other's position on every switch.
_CURSOR_FIELD_BY_SUBSECTION: dict[tuple[Page, str], str] = {
    (Page.STATUS, STATUS_INVENTORY): "inventory_cursor",
    (Page.ARCHIVES, ARCHIVES_QUESTS): "quest_cursor",
    (Page.ARCHIVES, ARCHIVES_TRANSMISSIONS): "transmission_cursor",
}

# Fallback for a sub-section with no list of its own. Nothing reads the
# cursor in that case (``handle_input`` only consults it while activated,
# and only activatable sub-sections activate), but returning a real field
# keeps every path total rather than optional.
_DEFAULT_CURSOR_FIELD: str = "inventory_cursor"

# Which ``SectionsUiState`` drill-depth field each drillable sub-section
# owns. Same shape and same rationale as ``_CURSOR_FIELD_BY_SUBSECTION``.
_DRILL_FIELD_BY_SUBSECTION: dict[tuple[Page, str], str] = {
    (Page.ARCHIVES, ARCHIVES_QUESTS): "quest_drill_key",
    (Page.ARCHIVES, ARCHIVES_TRANSMISSIONS): "transmission_drill_key",
}


def _cursor_field(page: Page, selected_key: str) -> str:
    return _CURSOR_FIELD_BY_SUBSECTION.get(
        (page, selected_key), _DEFAULT_CURSOR_FIELD
    )


def cursor_for(ui: SectionsUiState, page: Page, selected_key: str) -> ListCursor:
    """The cursor belonging to the given sub-section."""
    return getattr(ui, _cursor_field(page, selected_key))


def is_drillable(page: Page, selected_key: str) -> bool:
    return (page, selected_key) in DRILLABLE


def _drill_field(page: Page, selected_key: str) -> str | None:
    """The drill-depth field this sub-section owns, or ``None``."""
    return _DRILL_FIELD_BY_SUBSECTION.get((page, selected_key))


def drill_key_for(ui: SectionsUiState, page: Page, selected_key: str) -> str:
    """This sub-section's own depth, never another's."""
    field = _drill_field(page, selected_key)
    if field is None:
        return ""
    return getattr(ui, field)


def for_page(ui: SectionsUiState, page: Page) -> SegmentedHeaderState:
    """The sub-header state belonging to ``page``."""
    return getattr(ui, _FIELD_BY_PAGE[page])


def with_page(
    ui: SectionsUiState,
    page: Page,
    seg: SegmentedHeaderState,
) -> SectionsUiState:
    """Copy of ``ui`` with ``page``'s sub-header state replaced."""
    return replace(ui, **{_FIELD_BY_PAGE[page]: seg})


def focus_for(
    ui: SectionsUiState,
    page: Page,
    selected_key: str,
) -> SubSectionFocus:
    """The focus state to hand a section renderer this frame.

    Takes the sub-section now, not just the state: which cursor is in play
    depends on which sub-section is showing. ``location_key`` is only ever
    non-empty for a drillable sub-section.
    """
    return SubSectionFocus(
        activated=ui.activated,
        cursor=cursor_for(ui, page, selected_key),
        location_key=drill_key_for(ui, page, selected_key),
    )


def deactivated(ui: SectionsUiState) -> SectionsUiState:
    """Copy of ``ui`` with the content handed back to the sub-section row.

    Used by the section-button path: activation never survives leaving a
    section. Drill-down depth is part of activation and goes with it;
    sub-section selections and every content cursor survive, so the list
    resumes on the row it was outlining.
    """
    return replace(ui, activated=False, quest_drill_key="", transmission_drill_key="")


def is_activatable(page: Page, selected_key: str) -> bool:
    return (page, selected_key) in ACTIVATABLE


def handle_input(
    ui: SectionsUiState,
    page: Page,
    input_event: InputEvent,
    *,
    rows: Sequence[ListRow] = (),
) -> SectionsUiState:
    """Apply one input event to the active section's sub-section state.

    The single place these events are interpreted. ``rows`` is the active
    sub-section's content rows — empty for a sub-section with no list —
    and is only consulted while activated or when deciding whether
    ``Confirm`` has anything to activate into.
    """
    seg = for_page(ui, page)
    cursor_field = _cursor_field(page, seg.selected_key)
    cursor = getattr(ui, cursor_field)
    drillable = is_drillable(page, seg.selected_key)
    # Only meaningful for a drillable sub-section; guarded so a stale key
    # can never make a non-drillable list look drilled.
    drill_field = _drill_field(page, seg.selected_key)
    drilled = drillable and drill_field is not None and getattr(ui, drill_field) != ""

    if isinstance(input_event, (EncoderLeftEvent, EncoderRightEvent)):
        if ui.activated:
            resolved = scroll_list.resolve_cursor(rows, cursor)
            move = (
                scroll_list.move_prev
                if isinstance(input_event, EncoderLeftEvent)
                else scroll_list.move_next
            )
            return replace(ui, **{cursor_field: move(rows, resolved)})
        if isinstance(input_event, EncoderLeftEvent):
            return with_page(ui, page, cycle_prev(seg))
        return with_page(ui, page, cycle_next(seg))

    if isinstance(input_event, ConfirmEvent):
        if not is_activatable(page, seg.selected_key):
            return ui

        if ui.activated:
            # Drill in: only from level 1 of a drillable sub-section.
            # Everywhere else ``Confirm`` while activated stays inert, as
            # it has been since TASK-018.
            if not drillable or drilled:
                return ui
            resolved = scroll_list.resolve_cursor(rows, cursor)
            if resolved.selected_key == scroll_list.NO_SELECTION:
                return ui
            # The cursor is reset, not carried down. One cursor field
            # serves both levels, and a level-1 key left in it would
            # resolve against level 2's rows by *index* — landing on an
            # arbitrary quest. A fresh cursor resolves to the location's
            # first quest, which is both predictable and what the in-game
            # screen does on entry.
            assert drill_field is not None  # implied by `drillable`
            return replace(
                ui,
                **{drill_field: resolved.selected_key, cursor_field: ListCursor()},
            )

        if scroll_list.first_selectable(rows) == scroll_list.NO_SELECTION:
            # Nothing to select — activating would trap the encoder in an
            # empty list. Stay at the sub-section row instead.
            return ui
        # Resolve rather than reset: re-entering resumes on the row the
        # deactivated list was already outlining.
        return replace(
            ui,
            activated=True,
            **{cursor_field: scroll_list.resolve_cursor(rows, cursor)},
        )

    if isinstance(input_event, BackEvent):
        if ui.activated:
            if drilled:
                # Up one level, not out — and land back on the location we
                # came from. The depth key *is* that location's level-1 row
                # key, so restoring the cursor from it is exact; letting
                # the level-2 key fall back to an index clamp would put the
                # cursor on whichever location happened to share the
                # position.
                assert drill_field is not None  # implied by `drilled`
                previous = getattr(ui, drill_field)
                return replace(
                    ui,
                    **{
                        drill_field: "",
                        cursor_field: ListCursor(selected_key=previous),
                    },
                )
            # Cursor deliberately left intact.
            return replace(ui, activated=False, quest_drill_key="", transmission_drill_key="")
        # Inert at the sub-section row, by decision, not by omission: the
        # device's fourth button already owns close/shutdown.
        return ui

    return ui
