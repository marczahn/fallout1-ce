#ifndef FALLOUT_GAME_PIPBOY_H_
#define FALLOUT_GAME_PIPBOY_H_

#include "game/art.h"
#include "game/message.h"
#include "plib/db/db.h"
#include "plib/gnw/rect.h"

namespace fallout {

typedef enum PipboyOpenIntent {
    PIPBOY_OPEN_INTENT_UNSPECIFIED = 0,
    PIPBOY_OPEN_INTENT_REST = 1,
} PipboyOpenIntent;

typedef void(PipboyRenderProc)(int a1);

int pipboy(int intent);
void pip_init();
int save_pipboy(DB_FILE* stream);
int load_pipboy(DB_FILE* stream);

// Companion read-only accessors over the Pip-Boy quest table (`sthreads`
// in `pipboy.cc`) - the same table `PipStatus`/`ListStatLines` walk to
// build the in-game quest screen. Exposed so the companion server can
// project quests without duplicating the table, which would drift the
// moment upstream edits theirs. Pure reads of file-static const data; safe
// at any time, including while the Pip-Boy screen is closed and its
// `pipboy_message_file` is unloaded.
int companionQuestLocationCount();
int companionQuestSlotCount();

// The `GVAR_*` index at (location, slot), or 0 for an empty slot or any
// out-of-range coordinate. 0 is the table's own terminator value (see the
// `sthreads[location][quest] == 0` breaks in `PipStatus`), so out-of-range
// reads are indistinguishable from "no quest here" by design.
int companionQuestGlobalVar(int location, int slot);

} // namespace fallout

#endif /* FALLOUT_GAME_PIPBOY_H_ */
