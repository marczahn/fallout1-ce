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
class LocalMapState:
    """Pip-Boy local-map (automap) image cache and fetch bookkeeping.

    Analogous to ``WorldMapState`` (and reuses ``WorldMapStatus``), but the
    local map is per-(map, elevation) and is re-fetched as the player moves
    to a new map/elevation and periodically to pick up newly explored tiles.
    ``map_index``/``elevation`` identify the cached image; ``fetch_map``/
    ``fetch_elevation`` identify the in-flight fetch so a mid-fetch target
    change can be detected and the fetch restarted. Pure data: the rendered
    green ``pygame.Surface`` is built and cached by the UI layer.
    """

    status: WorldMapStatus = WorldMapStatus.IDLE
    # Identity of the cached (READY) image.
    map_index: int = -1
    elevation: int = -1
    width: int = 0
    height: int = 0
    palette: bytes = b""
    pixels: bytes = b""
    explored: bool = False
    # The (map, elevation) the in-flight fetch is for (matches header echo).
    fetch_map: int = -1
    fetch_elevation: int = -1
    fetch_explored: bool = False
    # Fetch bookkeeping (client-only).
    chunk_count: int = 0
    next_index: int = 0
    chunk_bytes: int = 0
    accumulator: bytearray = field(default_factory=bytearray)
    last_request_at: float = 0.0
    retries: int = 0
    # When the current READY image was captured (for throttled refresh) and
    # the player tile at that time (only refresh after movement).
    last_ready_at: float = 0.0
    image_tile: int = -1


@dataclass
class WorldInfo:
    schema_version: int = 0
    game: str = ""
    player_available: bool = False


@dataclass
class InventoryItem:
    object_id: int = 0
    pid: int = 0
    proto_id: str = ""
    name: str = ""
    item_type: str = ""
    count: int = 0
    slot: str = "none"
    two_handed: bool = False

    # Common block (schemaVersion 10).
    weight: int = 0
    value: int = 0

    # Per-type detail (schemaVersion 10). `-1` means "does not apply to this
    # item", mirroring the server's sentinel — 0 cannot serve, since an empty
    # gun really does hold 0 rounds and 0 armor class is a real value. A
    # schemaVersion 9 server sends none of these, so they all stay absent.
    dmg_min: int = -1
    dmg_max: int = -1
    min_st: int = -1
    weapon_range: int = -1  # not `range`, which is a builtin
    ammo_current: int = -1
    ammo_max: int = -1
    ammo_name: str = ""
    caliber: int = -1
    total_rounds: int = -1
    armor_class: int = -1
    charges_current: int = -1
    charges_max: int = -1
    caps_amount: int = -1


@dataclass
class Quest:
    """One row of the in-game Pip-Boy quest screen (schemaVersion 12).

    Identity is ``(location_index, slot)`` — the server's coordinates in
    the engine's fixed quest table. No GVAR index crosses the wire, so the
    app never learns anything about engine internals.

    ``location`` is the engine's own Pip-Boy location name, which is *not*
    the automap short name ``PlayerState.location`` carries. Grouping runs
    on ``location_index`` so it never depends on a localized string.

    ``text`` may legitimately be empty: the server emits the row anyway
    when its message file could not resolve the line, so the list can never
    silently disagree with the in-game screen. The renderer shows that as a
    visible failure rather than hiding the row.
    """

    location_index: int = 0
    slot: int = 0
    location: str = ""
    text: str = ""
    completed: bool = False
    water_chip: bool = False


@dataclass
class WaterStatus:
    """The Vault 13 water countdown (schemaVersion 12).

    ``days_remaining`` is days of water left; the engine decrements it once
    per in-game midnight. ``countdown_active`` is the engine's own guard on
    that decrement, which is deliberately *not* the same rule as a quest's
    ``completed`` — the two disagree once the water-chip variable exceeds 2,
    and the server reports both as-is rather than merging them.
    ``ui.quest_list.water_state`` is the single place that turns the pair
    into a label.
    """

    days_remaining: int = 0
    countdown_active: bool = False


@dataclass
class Transmission:
    """One row of the in-game Pip-Boy Archives screen (schemaVersion 13).

    Identity is ``index`` — the engine's ``GameMovie`` enum value. The
    listable range is ``MOVIE_VEXPLD..MOVIE_COUNT-1``, i.e. **3..13**, which
    excludes the two logos and the intro exactly as the in-game screen does.
    (It is *not* the 18-entry holodisk table; that is a different subject on
    a different screen — see :class:`Holodisk`.) No GVAR crosses the wire,
    matching :class:`Quest`.

    ``title`` may legitimately be empty: the server emits the row anyway
    when its message file could not resolve it, so the list can never
    silently disagree with the in-game screen.

    There is deliberately **no body text**. The engine has it, but the
    transmission screen plays a recording rather than rendering a document —
    see the TASK-024 audio-over-video decision. Whether a recording
    actually exists is *not* a property of this row: that lives in
    :class:`TransmissionAudioState`, because bakedness and availability are
    independent and are only intersected when rendering.
    """

    index: int = 0
    title: str = ""


class TransmissionSyncStatus(Enum):
    """Lifecycle of the on-connect transmission audio sync.

    IDLE     -- not started (initial / post-reconnect).
    FETCHING -- manifest or chunks in flight.
    READY    -- every manifest entry landed.
    UNAVAILABLE -- server too old, or the fetch gave up.
    """

    IDLE = 0
    FETCHING = 1
    READY = 2
    UNAVAILABLE = 3


@dataclass
class TransmissionRecording:
    """A fully-transferred narration plus its equalizer envelope.

    ``duration_ms`` is derived, not sent: ``frames * frame_ms``. It is what
    the transport clamps seeks against, and clamping is mandatory rather
    than defensive — ``pygame.mixer.music.set_pos()`` raises
    ``pygame.error`` for a target past the end of the track, with the
    misleading message "Position not implemented for music type".
    """

    index: int = 0
    path: str = ""
    bands: int = 0
    frames: int = 0
    frame_ms: int = 0
    # bands * frames bytes, row-major by frame.
    envelope: bytes = b""

    @property
    def duration_ms(self) -> int:
        return self.frames * self.frame_ms


@dataclass
class TransmissionAudioState:
    """Sync bookkeeping plus the recordings that have landed.

    Deliberately keyed by transmission index and deliberately independent of
    which disks the player has found: the sync fetches every *baked* disk,
    so a disk discovered mid-session already has its audio. See the
    TASK-024 fetch-on-connect decision.
    """

    status: TransmissionSyncStatus = TransmissionSyncStatus.IDLE
    # Indices the server reports as baked, in manifest order.
    manifest: list[int] = field(default_factory=list)
    recordings: dict[int, TransmissionRecording] = field(default_factory=dict)
    # Indices that were attempted and failed (error, timeout, malformed
    # envelope, short transfer). Tracked separately from ``recordings``
    # because the sync advances by "not yet attempted", not by "not yet
    # succeeded" -- keying only on success makes an unfetchable disk
    # re-selected forever and the sync never converges.
    failed: set[int] = field(default_factory=set)
    # Fetch bookkeeping (client-only), mirroring WorldMapState's shape.
    current_index: int = -1
    chunk_count: int = 0
    next_chunk: int = 0
    chunk_bytes: int = 0
    expected_bytes: int = 0
    accumulator: bytearray = field(default_factory=bytearray)
    pending_envelope: bytes = b""
    last_request_at: float = 0.0
    retries: int = 0

    def has_recording(self, index: int) -> bool:
        return index in self.recordings


@dataclass
class PlayerState:
    available: bool = False
    hp: int = 0
    max_hp: int = 0
    surface: PlayerSurface = PlayerSurface.UNKNOWN
    location: str = ""
    map_name: str = ""
    location_id: str = ""
    world_x: int = 0
    world_y: int = 0
    # Local-surface position: hex-tile index, elevation, and map enum index.
    tile: int = 0
    elevation: int = 0
    local_map_index: int = -1
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
    quests: list[Quest] = field(default_factory=list)
    water: WaterStatus = field(default_factory=WaterStatus)
    transmissions: list[Transmission] = field(default_factory=list)


@dataclass
class AppState:
    connection: ConnectionState = ConnectionState.DISCONNECTED
    world: WorldInfo | None = None
    player: PlayerState = field(default_factory=PlayerState)
    world_map: WorldMapState = field(default_factory=WorldMapState)
    local_map: LocalMapState = field(default_factory=LocalMapState)
    transmission_audio: TransmissionAudioState = field(default_factory=TransmissionAudioState)
    # Most recent world position ever seen, in image-pixel space. Persists
    # while the player is on a LOCAL surface so the map can show a
    # "LAST KNOWN" marker. ``has_world_fix`` gates whether it is meaningful.
    last_known_world_x: int = 0
    last_known_world_y: int = 0
    has_world_fix: bool = False
    command_error: str = ""
    command_pending: bool = False
