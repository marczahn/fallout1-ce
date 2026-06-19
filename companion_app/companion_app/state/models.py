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


class PlayerSurface(Enum):
    UNKNOWN = 0
    LOCAL = 1
    WORLD = 2


class WorldMapStatus(Enum):
    """Lifecycle of the world-map image fetch.

    IDLE     -- no fetch started yet (initial / post-reconnect).
    FETCHING -- header/chunks in flight.
    READY    -- full indexed buffer reassembled and validated.
    UNAVAILABLE -- server too old, server error, or fetch gave up.
    """

    IDLE = 0
    FETCHING = 1
    READY = 2
    UNAVAILABLE = 3


@dataclass
class WorldMapState:
    """Pip-Boy world-map image cache and fetch bookkeeping.

    Pure data: holds the palette-indexed image and the state machine the
    network client drives. No pygame, no sockets. The rendered (green)
    ``pygame.Surface`` is built and cached by the UI layer, not here.
    """

    status: WorldMapStatus = WorldMapStatus.IDLE
    width: int = 0
    height: int = 0
    # 768 bytes RGB (256 entries * 3), 8-bit normalized.
    palette: bytes = b""
    # The reassembled width*height 8-bit palette-indexed buffer.
    pixels: bytes = b""
    # Fetch bookkeeping (client-only).
    chunk_count: int = 0
    next_index: int = 0
    chunk_bytes: int = 0
    accumulator: bytearray = field(default_factory=bytearray)
    last_request_at: float = 0.0
    retries: int = 0


@dataclass
class WorldInfo:
    schema_version: int = 0
    game: str = ""
    player_available: bool = False


@dataclass
class InventoryItem:
    pid: int = 0
    proto_id: str = ""
    name: str = ""
    item_type: str = ""
    count: int = 0
    slot: str = "none"


@dataclass
class PlayerState:
    available: bool = False
    hp: int = 0
    max_hp: int = 0
    surface: PlayerSurface = PlayerSurface.UNKNOWN
    location: str = ""
    location_id: str = ""
    world_x: int = 0
    world_y: int = 0
    armor_class: int = 0
    current_carry_weight: int = 0
    carry_weight: int = 0
    melee_damage: int = 0
    damage_resistance: int = 0
    radiation: int = 0
    poison: int = 0
    level: int = 0
    experience: int = 0
    next_level_exp: int = 0
    strength: int = 0
    perception: int = 0
    endurance: int = 0
    charisma: int = 0
    intelligence: int = 0
    agility: int = 0
    luck: int = 0
    inventory: list[InventoryItem] = field(default_factory=list)


@dataclass
class AppState:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    world: WorldInfo | None = None
    player: PlayerState = field(default_factory=PlayerState)
    world_map: WorldMapState = field(default_factory=WorldMapState)
    # Most recent world position ever seen, in image-pixel space. Persists
    # while the player is on a LOCAL surface so the map can show a
    # "LAST KNOWN" marker. ``has_world_fix`` gates whether it is meaningful.
    last_known_world_x: int = 0
    last_known_world_y: int = 0
    has_world_fix: bool = False
