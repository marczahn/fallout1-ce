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
ARCHIVES_HOLODISKS: str = "HOLODISKS"


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


@dataclass(frozen=True)
class SubSectionFocus:
    """What a section renderer needs to draw its content's focus state.

    Passed instead of loose parameters so later consumers (per-type item
    detail, QUESTS, HOLODISKS) extend one dataclass rather than every
    section's signature again.
    """

    activated: bool
    cursor: ListCursor


# Sub-sections whose content can take the encoder. Everything absent here
# is why ``Confirm`` is inert on CHARACTER, QUESTS and HOLODISKS.
ACTIVATABLE: frozenset[tuple[Page, str]] = frozenset(
    {(Page.STATUS, STATUS_INVENTORY)}
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
            )
        ),
    )


_FIELD_BY_PAGE: dict[Page, str] = {
    Page.STATUS: "status",
    Page.AUTOMAPS: "automaps",
    Page.ARCHIVES: "archives",
}


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


def focus_for(ui: SectionsUiState) -> SubSectionFocus:
    """The focus state to hand a section renderer this frame."""
    return SubSectionFocus(activated=ui.activated, cursor=ui.inventory_cursor)


def deactivated(ui: SectionsUiState) -> SectionsUiState:
    """Copy of ``ui`` with the content handed back to the sub-section row.

    Used by the section-button path: activation never survives leaving a
    section. Sub-section selections and the content cursor both survive.
    """
    return replace(ui, activated=False)


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

    if isinstance(input_event, (EncoderLeftEvent, EncoderRightEvent)):
        if ui.activated:
            cursor = scroll_list.resolve_cursor(rows, ui.inventory_cursor)
            move = (
                scroll_list.move_prev
                if isinstance(input_event, EncoderLeftEvent)
                else scroll_list.move_next
            )
            return replace(ui, inventory_cursor=move(rows, cursor))
        if isinstance(input_event, EncoderLeftEvent):
            return with_page(ui, page, cycle_prev(seg))
        return with_page(ui, page, cycle_next(seg))

    if isinstance(input_event, ConfirmEvent):
        if ui.activated or not is_activatable(page, seg.selected_key):
            return ui
        if scroll_list.first_selectable(rows) == scroll_list.NO_SELECTION:
            # Nothing to select — activating would trap the encoder in an
            # empty list. Stay at the sub-section row instead.
            return ui
        # Resolve rather than reset: re-entering resumes on the row the
        # deactivated list was already outlining.
        return replace(
            ui,
            activated=True,
            inventory_cursor=scroll_list.resolve_cursor(rows, ui.inventory_cursor),
        )

    if isinstance(input_event, BackEvent):
        if ui.activated:
            # Cursor deliberately left intact.
            return replace(ui, activated=False)
        # Inert at the sub-section row, by decision, not by omission: the
        # device's fourth button already owns close/shutdown.
        return ui

    return ui
