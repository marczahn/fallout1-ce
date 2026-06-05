#include "companion_player_state.h"

#include "game/mainmenu.h"
#include "game/map.h"
#include "game/object.h"
#include "game/object_types.h"
#include "game/worldmap.h"
#include "int/movie.h"

namespace fallout {

bool companionIsPlayerReallyPlaying()
{
    if (obj_dude == nullptr) {
        return false;
    }

    if (in_main_menu) {
        return false;
    }

    // MVE movies include the opening IPLOGO + INTRO, the in-game OVRINTRO,
    // and the death scene. They run before, between, and after real maps.
    if (moviePlaying()) {
        return false;
    }

    // `map_data.name[0] == '\0'` is the engine's "no real map is currently
    // loaded" signal. `map_new_map()` and `map_save_in_game(true)` both
    // clear it. `map_load`/`map_load_file` set it to the loaded map's name.
    // The world map also calls `map_save_in_game(true)` at entry, which
    // clears the name, so the bare name check would mistakenly report the
    // world map as "not playing" even though the player is actively on it
    // with real HP, real inventory, and a real party. `worldMapIsActive()`
    // exposes `wwin_flag` from `worldmap.cc`, which is true for the entire
    // duration of a `world_map()` invocation (and the in-world-map town
    // map picker). The combined check accepts the world map as gameplay
    // and rejects the other "no real map" states (cold startup, MVE
    // playback, post-`main_unload_new`, character creation) which never
    // have the world map window up.
    if (map_data.name[0] == '\0' && !worldMapIsActive()) {
        return false;
    }

    // `OBJECT_HIDDEN` is set by `obj_turn_off`, which `main_unload_new`
    // calls when leaving real gameplay (e.g. on death, on returning to
    // the main menu). It is cleared by `obj_turn_on`, which `main_load_new`
    // calls when starting real gameplay. The check is what disambiguates
    // "previously-loaded map is still named, but the player is in
    // character creation" from "the player is in a real map". Without
    // this check, the leftover map name from a previous session would
    // let a fresh new-game character editor report real gameplay.
    if ((obj_dude->flags & OBJECT_HIDDEN) != 0) {
        return false;
    }

    return true;
}

} // namespace fallout
