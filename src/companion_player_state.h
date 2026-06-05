#ifndef FALLOUT_COMPANION_PLAYER_STATE_H_
#define FALLOUT_COMPANION_PLAYER_STATE_H_

namespace fallout {

// Returns true only when the engine is in real in-map gameplay, i.e. the
// conditions under which `obj_dude` reflects the live player and not a
// placeholder. Returns false during the main menu, intro movie, character
// creation, world map, save/load screens, the death scene, and any other
// state where the player data is not authoritative.
//
// The signals checked, in short-circuit order:
//   1. `obj_dude != nullptr`            (object is allocated)
//   2. `!in_main_menu`                  (the main menu is not active)
//   3. `!moviePlaying()`                (no MVE/gmovie is on screen)
//   4. `map_data.name[0] != '\\0'`      (a real map is currently loaded)
//   5. `!(obj_dude->flags & OBJECT_HIDDEN)` (the player is not torn down)
//
// See `docs/plans/companion-server-step-2-tickets.md` T2 for the
// state-by-state mapping each check is responsible for.
bool companionIsPlayerReallyPlaying();

} // namespace fallout

#endif /* FALLOUT_COMPANION_PLAYER_STATE_H_ */
