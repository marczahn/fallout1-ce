#ifndef FALLOUT_COMPANION_SNAPSHOT_H_
#define FALLOUT_COMPANION_SNAPSHOT_H_

#include <cstddef>

namespace fallout {

// Which engine surface the player is currently on. Drives which position
// fields are meaningful in `CompanionPlayerSnapshot` and which appear on
// the wire in `snapshot.data.player` / `update.data`.
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

struct CompanionPlayerSnapshot {
    int hp;
    int maxHp;
    CompanionPlayerSurface surface;

    // Local-map fields. Meaningful when `surface == Local`.
    int tile;
    int elevation;
    int map;
    char location[kCompanionLocationSize];
    char locationId[kCompanionLocationIdSize];

    // World-map fields. Meaningful when `surface == World`.
    int worldX;
    int worldY;
};

struct CompanionSnapshot {
    bool hasPlayer;
    CompanionPlayerSnapshot player;
};

// Field-level equality across the synced player state. The protocol's
// per-field diff uses the same definition; this helper exists so the
// server can short-circuit the per-tick "did anything change?" check
// without re-implementing the comparison inline.
bool companionPlayerSnapshotEquals(const CompanionPlayerSnapshot& a, const CompanionPlayerSnapshot& b);

CompanionSnapshot companionCollectSnapshot();

} // namespace fallout

#endif /* FALLOUT_COMPANION_SNAPSHOT_H_ */
