#ifndef FALLOUT_COMPANION_SNAPSHOT_H_
#define FALLOUT_COMPANION_SNAPSHOT_H_

#include <cstddef>

namespace fallout {

// Which engine surface the player is currently on. Drives which position
// kinds are meaningful in `CompanionSnapshot` and which appear on the wire
// in `snapshot.payload` / `update.payload`.
//
// `Local` is a real in-city / dungeon / vault map. The engine stores
// position as a 1D hex-grid tile number plus elevation, indexed into the
// global `objectTable[HEX_GRID_SIZE]`. The same tile value can refer to
// different cells on different elevations, so elevation is required to
// fully specify position on multi-elevation maps.
//
// `World` is the overland world map. The engine stores position as pixel
// coordinates (`world_xpos`, `world_ypos`) at a 50-pixel-per-area scale.
// The in-world-map town picker is treated as `World` (per T2's
// `worldMapIsActive()` semantics, `wwin_flag` is true for the whole
// `world_map()` call, picker included).
enum class CompanionPlayerSurface {
    Local,
    World,
};

// Backing storage for `location`. Sized to fit the longest localized
// short name the engine's automap displays (e.g. "Brotherhood of Steel
// Entrance"). 64 bytes is a defensive ceiling; actual strings are
// shorter.
static constexpr size_t kCompanionLocationSize = 64;

// Backing storage for `locationId`. Sized to fit the longest stable
// identifier (e.g. "HUBWATER"). 32 bytes is a defensive ceiling; actual
// strings are 8 chars or fewer.
static constexpr size_t kCompanionLocationIdSize = 32;

// `player.vitals` payload. HP and max HP. Always meaningful when the
// player is loaded (real or world map). Wire keys: `hp`, `maxHp`.
struct CompanionPlayerVitals {
    int hp;
    int maxHp;
};

// `player.local_location` payload. Meaningful when
// `surface == CompanionPlayerSurface::Local`. Wire keys: `tile`,
// `elevation`, `map`, `location`, `locationId`. `location` is the engine's
// localized short name; `locationId` is a stable identifier from the
// `kMapLocationIds` table in `companion_snapshot.cc`.
struct CompanionPlayerLocalLocation {
    int tile;
    int elevation;
    int map;
    char location[kCompanionLocationSize];
    char locationId[kCompanionLocationIdSize];
};

// `player.world_location` payload. Meaningful when
// `surface == CompanionPlayerSurface::World`. Wire keys: `x`, `y` (the
// engine's 50-pixel-per-area world coordinates).
struct CompanionPlayerWorldLocation {
    int x;
    int y;
};

// Aggregator over the three per-kind player payloads. The `surface`
// field drives which of `localLocation` and `worldLocation` are
// meaningful at any given sample; `vitals` is always meaningful when
// `hasPlayer` is true. The protocol emits only the valid kinds on the
// wire.
struct CompanionSnapshot {
    bool hasPlayer;
    CompanionPlayerSurface surface;
    CompanionPlayerVitals vitals;
    CompanionPlayerLocalLocation localLocation;
    CompanionPlayerWorldLocation worldLocation;
};

CompanionSnapshot companionCollectSnapshot();

} // namespace fallout

#endif /* FALLOUT_COMPANION_SNAPSHOT_H_ */
