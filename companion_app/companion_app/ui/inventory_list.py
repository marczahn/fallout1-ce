"""STATUS/INVENTORY list projection (TASK-018).

Turns ``player.inventory`` into display rows and owns the selection
anchor. Pure data work: no pygame, no ``AppState``, so both the input
router and the renderer can call it and unit tests need no display.

**Grouping and ordering run app-side.** Both ``name`` and ``type`` already
cross the wire, so this needs no protocol change — and the server's diff
is positional (``inventoryDiffer``), which means an unstable server-side
sort would resend the whole inventory every tick. Ordering here has no
such failure mode.

**The anchor is ``(pid, slot, occurrence)``, not the engine's object id.**
``Object::id`` looks ideal — unique among live objects, stable for an
object's lifetime — but ``item_remove_mult`` replaces a stack's
representative object via ``obj_copy`` on a *partial* removal, and
``obj_copy`` assigns a fresh id. So consuming one stimpak from a stack of
five re-ids the remaining stack: the most common inventory mutation there
is, and exactly the case the anchor exists to survive. ``pid`` and the
flags behind ``slot`` are memcpy'd through that path untouched.
``occurrence`` disambiguates the entries ``(pid, slot)`` alone cannot,
since containers and anything holding a nested inventory never stack.
"""
from __future__ import annotations

from typing import Sequence

from companion_app.state import InventoryItem
from companion_app.ui import scroll_list
from companion_app.ui.scroll_list import ListCursor, ListRow

# Wire ``type`` -> group heading, in display order. AID rather than HEALTH
# by explicit choice; stimpaks are ITEM_TYPE_DRUG engine-side.
GROUP_ORDER: tuple[tuple[str, str], ...] = (
    ("weapon", "WEAPONS"),
    ("ammo", "AMMO"),
    ("armor", "ARMOR"),
    ("drug", "AID"),
    ("misc", "MISC"),
    ("key", "KEYS"),
    ("container", "CONTAINERS"),
)

# Unknown or empty wire types land here rather than being dropped — the
# list must never silently hide something the player is carrying.
FALLBACK_GROUP: str = "misc"

_GROUP_LABELS: dict[str, str] = dict(GROUP_ORDER)

# Heading keys are prefixed so they cannot collide with an item key,
# which is always "<int>:<slot>:<int>".
_HEADING_PREFIX: str = "#"

EQUIPPED_SLOTS: frozenset[str] = frozenset({"worn", "rightHand", "leftHand"})


def group_for(item_type: str) -> str:
    """Wire type this item groups under, falling back to MISC."""
    return item_type if item_type in _GROUP_LABELS else FALLBACK_GROUP


def group_label(item_type: str) -> str:
    """Display heading for an item's group."""
    return _GROUP_LABELS[group_for(item_type)]


def row_key(pid: int, slot: str, occurrence: int) -> str:
    """The ``(pid, slot, occurrence)`` anchor, flattened to a row key."""
    return f"{pid}:{slot}:{occurrence}"


def heading_key(label: str) -> str:
    return f"{_HEADING_PREFIX}{label}"


def is_equipped(item: InventoryItem) -> bool:
    return item.slot in EQUIPPED_SLOTS


def _grouped(
    items: Sequence[InventoryItem],
) -> tuple[tuple[str, tuple[tuple[str, InventoryItem], ...]], ...]:
    """``((heading, ((row_key, item), ...)), ...)`` in display order.

    The single definition of the display order: ``build_rows`` and
    ``item_for_key`` both derive from it so they cannot disagree.
    """
    buckets: dict[str, list[InventoryItem]] = {
        wire_type: [] for wire_type, _label in GROUP_ORDER
    }
    for item in items:
        buckets[group_for(item.item_type)].append(item)

    occurrences: dict[tuple[int, str], int] = {}
    grouped: list[tuple[str, tuple[tuple[str, InventoryItem], ...]]] = []
    for wire_type, label in GROUP_ORDER:
        bucket = buckets[wire_type]
        if not bucket:
            continue
        entries: list[tuple[str, InventoryItem]] = []
        # casefold first so ordering is case-insensitive, then pid so two
        # same-named items always land in the same order.
        for item in sorted(bucket, key=lambda i: (i.name.casefold(), i.pid)):
            seen = occurrences.get((item.pid, item.slot), 0)
            occurrences[(item.pid, item.slot)] = seen + 1
            entries.append((row_key(item.pid, item.slot, seen), item))
        grouped.append((label, tuple(entries)))
    return tuple(grouped)


def build_rows(items: Sequence[InventoryItem]) -> tuple[ListRow, ...]:
    """Heading + item rows for the whole inventory, empty groups omitted."""
    rows: list[ListRow] = []
    for label, entries in _grouped(items):
        rows.append(
            ListRow(key=heading_key(label), label=label, selectable=False)
        )
        for key, item in entries:
            rows.append(ListRow(key=key, label=item.name, selectable=True))
    return tuple(rows)


def item_for_key(
    items: Sequence[InventoryItem],
    key: str,
) -> InventoryItem | None:
    """The item a row key points at, or ``None``."""
    if not key or key.startswith(_HEADING_PREFIX):
        return None
    for _label, entries in _grouped(items):
        for entry_key, item in entries:
            if entry_key == key:
                return item
    return None


# Re-anchoring itself is generic over (rows, cursor) and lives in
# ``scroll_list.resolve_cursor``. What is inventory-specific is *why* the
# key is shaped ``(pid, slot, occurrence)`` — see the module docstring.
