#include "companion_snapshot.h"

#include "companion_player_state.h"
#include "game/critter.h"
#include "game/object.h"
#include "game/stat.h"
#include "game/stat_defs.h"

namespace fallout {

CompanionSnapshot companionCollectSnapshot()
{
    CompanionSnapshot snapshot;
    snapshot.hasPlayer = false;
    snapshot.player.hp = 0;
    snapshot.player.maxHp = 0;

    if (!companionIsPlayerReallyPlaying()) {
        return snapshot;
    }

    snapshot.hasPlayer = true;
    snapshot.player.hp = critter_get_hits(obj_dude);
    snapshot.player.maxHp = stat_level(obj_dude, STAT_MAXIMUM_HIT_POINTS);
    return snapshot;
}

} // namespace fallout
