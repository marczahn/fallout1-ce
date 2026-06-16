"""Companion app state cache (M3).

Pure-data module with no dependency on networking or pygame. Owns the
in-memory state that the UI layer reads each frame.
"""
from companion_app.state.models import (
    AppState,
    ConnectionState,
    InventoryItem,
    PlayerState,
    PlayerSurface,
    WorldInfo,
)

__all__ = [
    "AppState",
    "ConnectionState",
    "InventoryItem",
    "PlayerState",
    "PlayerSurface",
    "WorldInfo",
]
