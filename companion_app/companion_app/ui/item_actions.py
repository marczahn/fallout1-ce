"""Inventory item-action modal and its small, device-first state model."""
from __future__ import annotations

from dataclasses import dataclass

import pygame

from companion_app.render import font, palette
from companion_app.state import InventoryItem


@dataclass(frozen=True)
class Action:
    label: str
    command: str


@dataclass(frozen=True)
class ModalState:
    open: bool = False
    index: int = 0
    pending: bool = False


def actions_for(item: InventoryItem | None) -> tuple[Action, ...]:
    if item is None:
        return ()
    if item.item_type == "drug":
        return (Action("USE", "useSelf"), Action("CANCEL", "cancel"))
    if item.item_type == "armor":
        return (Action("EQUIP", "equipArmor"), Action("CANCEL", "cancel"))
    if item.item_type in ("weapon", "misc"):
        if item.two_handed:
            return (
                Action("PUT IN BOTH HANDS", "equipBothHands"),
                Action("CANCEL", "cancel"),
            )
        return (
            Action("PUT IN LEFT HAND", "equipLeftHand"),
            Action("PUT IN RIGHT HAND", "equipRightHand"),
            Action("CANCEL", "cancel"),
        )
    return (Action("CANCEL", "cancel"),)


def move(state: ModalState, count: int, delta: int) -> ModalState:
    if count <= 0:
        return ModalState()
    return ModalState(True, (state.index + delta) % count)


def render(surface: pygame.Surface, bounds: pygame.Rect, item: InventoryItem, state: ModalState, error: str) -> None:
    """Draw a compact modal; input handling remains in the app router."""
    actions = actions_for(item)
    width = 380
    height = 78 + len(actions) * 30 + 14
    rect = pygame.Rect(0, 0, width, height)
    rect.center = bounds.center
    pygame.draw.rect(surface, palette.BACKGROUND, rect)
    pygame.draw.rect(surface, palette.FOREGROUND, rect, 1)
    font.draw_text_centered(surface, item.name.upper(), pygame.Rect(rect.left + 12, rect.top + 14, rect.width - 24, 18), 14, palette.FOREGROUND)
    for index, action in enumerate(actions):
        # Cancel is intentionally separated from destructive/state-changing
        # choices, matching the physical distance of a device's back action.
        gap = 14 if action.command == "cancel" else 0
        row = pygame.Rect(rect.left + 18, rect.top + 46 + index * 30 + gap, rect.width - 36, 24)
        selected = index == state.index
        if selected:
            pygame.draw.rect(surface, palette.FOREGROUND, row)
        font.draw_text_left(surface, f"> {action.label}", (row.left + 6, row.top + 5), 14, palette.BACKGROUND if selected else palette.FOREGROUND)
    if state.pending:
        font.draw_text_centered(surface, "WORKING…", pygame.Rect(rect.left + 12, rect.bottom - 20, rect.width - 24, 14), 11, palette.FOREGROUND)
    elif error:
        font.draw_text_centered(surface, _error_text(error), pygame.Rect(rect.left + 12, rect.bottom - 20, rect.width - 24, 14), 11, palette.FOREGROUND)


def _error_text(error: str) -> str:
    return {
        "notPlayersTurn": "NOT YOUR TURN",
        "notEnoughActionPoints": "NOT ENOUGH ACTION POINTS",
        "itemNotFound": "ITEM NO LONGER AVAILABLE",
        "actionNotAvailable": "ACTION NOT AVAILABLE",
        "itemIdentityUnavailable": "UPDATE THE GAME SERVER",
    }.get(error, "ACTION FAILED")
