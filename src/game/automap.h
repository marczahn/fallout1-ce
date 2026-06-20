#ifndef FALLOUT_GAME_AUTOMAP_H_
#define FALLOUT_GAME_AUTOMAP_H_

#include "game/map_defs.h"
#include "plib/db/db.h"

namespace fallout {

#define AUTOMAP_DB "AUTOMAP.DB"
#define AUTOMAP_TMP "AUTOMAP.TMP"

// The number of map entries that is stored in automap.db.
#define AUTOMAP_MAP_COUNT 66

typedef struct AutomapHeader {
    unsigned char version;

    // The size of entire automap database (including header itself).
    int dataSize;

    // Offsets from the beginning of the automap database file into
    // entries data.
    //
    // These offsets are specified for every map/elevation combination. A value
    // of 0 specifies that there is no data for appropriate map/elevation
    // combination.
    int offsets[AUTOMAP_MAP_COUNT][ELEVATION_COUNT];
} AutomapHeader;

typedef struct AutomapEntry {
    int dataSize;
    unsigned char isCompressed;
} AutomapEntry;

int automap_init();
int automap_reset();
void automap_exit();
int automap_load(DB_FILE* stream);
int automap_save(DB_FILE* stream);
void automap(bool isInGame, bool isUsingScanner);
int draw_top_down_map_pipboy(int win, int map, int elevation);
int automap_pip_save();
int YesWriteIndex(int mapIndex, int elevation);
int ReadAMList(AutomapHeader** automapHeaderPtr);

// Companion local-map image accessor (read-only). Builds a top-down
// automap image of the *currently loaded* map at `elevation` as a
// row-major `width`*`height` (HEX_GRID_WIDTH x HEX_GRID_HEIGHT) buffer
// with one byte per hex tile: 0 = empty, 1 = wall, 2 = scenery. The pixel
// order matches the in-game Pip-Boy automap (`draw_top_down_map_pipboy`)
// so orientation is consistent. Reads objects' already-set `OBJECT_SEEN`
// flags and does NOT call `obj_process_seen()` (which would consume the
// game's shared seen state). Uses its own buffers (does not touch the
// in-game automap globals).
//
// On success returns true, sets `*outPixels` to a freshly allocated buffer
// the caller must release via `companionFreeLocalMapImage`, and sets
// `*outWidth`/`*outHeight`. The caller is responsible for gating on real
// local gameplay before calling (a map must be loaded; pass the current
// `map_elevation`). Returns false (allocating nothing) on bad args or
// allocation failure.
bool companionBuildLocalMapImage(int elevation,
    unsigned char** outPixels,
    int* outWidth,
    int* outHeight);

// Releases a buffer returned by `companionBuildLocalMapImage`. Safe with null.
void companionFreeLocalMapImage(unsigned char* pixels);

} // namespace fallout

#endif /* FALLOUT_GAME_AUTOMAP_H_ */
