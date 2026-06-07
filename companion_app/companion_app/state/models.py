"""Pure-data models for the companion app state cache (M3-T1).

No dependency on networking, pygame, or any UI module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ConnectionState(Enum):
    DISCONNECTED = 0
    CONNECTING = 1
    AWAITING_AUTH = 2
    AWAITING_WORLD = 3
    AWAITING_SNAPSHOT = 4
    READY = 5
    RECONNECTING = 6


@dataclass
class WorldInfo:
    schema_version: int = 0
    game: str = ""
    player_available: bool = False


@dataclass
class PlayerState:
    available: bool = False
    hp: int = 0
    max_hp: int = 0


@dataclass
class AppState:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    world: WorldInfo | None = None
    player: PlayerState = field(default_factory=PlayerState)
