"""Per-section sub-navigation state (TASK-017).

One module owns every section's sub-section set and every transition
between them, so no page defines its own navigation model. This replaces
both of the models that existed before: the MAP page's segmented header
and the DATA page's bespoke root/detail state.

The navigation rule is uniform across all three sections: the encoder
cycles sub-sections and the content switches immediately — there is no
"activate" step. ``Confirm``/``Back`` are therefore inert here; giving a
sub-section's content focus is TASK-018's job.

Selection is preserved per section: switching sections and coming back
leaves the previously selected sub-section selected.

State is immutable and the transitions are pure, so they unit-test
without a display (same contract as ``segmented_header``).
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from companion_app.input.events import (
    EncoderLeftEvent,
    EncoderRightEvent,
    InputEvent,
)
from companion_app.ui import segmented_header
from companion_app.ui.pages import Page
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
    """

    status: SegmentedHeaderState
    automaps: SegmentedHeaderState
    archives: SegmentedHeaderState


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


def handle_encoder(
    ui: SectionsUiState,
    page: Page,
    input_event: InputEvent,
) -> SectionsUiState:
    """Apply an encoder event to the active section only.

    The single place encoder events are interpreted. Any other event —
    including ``Confirm`` and ``Back`` — leaves the state untouched.
    """
    seg = for_page(ui, page)
    if isinstance(input_event, EncoderLeftEvent):
        return with_page(ui, page, cycle_prev(seg))
    if isinstance(input_event, EncoderRightEvent):
        return with_page(ui, page, cycle_next(seg))
    return ui
