#ifndef FALLOUT_COMPANION_QUEST_CATALOG_H_
#define FALLOUT_COMPANION_QUEST_CATALOG_H_

#include <cstddef>

namespace fallout {

// Resolved `pipboy.msg` text for the quest screen.
//
// The engine's own `pipboy_message_file` is `message_init`'d at
// `pipboy.cc:624-633` and `message_exit`'d at `:821`, so it exists *only*
// while the Pip-Boy screen is open - and the companion server samples
// during ordinary gameplay, when it does not. This module therefore owns
// an independent `MessageList` loaded from `msg_path + "pipboy.msg"` (the
// same path `pipboy.cc` builds) and caches the strings it resolves.
//
// Contrast `companion_item_catalog`, which leans on `proto_name` and its
// session-long `proto_msg_files`. No such persistent source exists for
// `pipboy.msg`, which is why this module has a lifecycle of its own.
//
// Text is copied out verbatim. Making it wire-safe belongs to
// `companionAppendEscapedJsonString`, not here: the companion must show
// the same quest lines the in-game Pip-Boy shows.

// Location name, message id `700 + 10 * location` (`pipboy.cc:1225`).
// Returns false and leaves `out` empty-terminated if the catalog could
// not be loaded or the id is absent.
bool companionQuestLocationName(int location, char* out, size_t outSize);

// Quest line, message id `701 + 10 * location + slot` (`pipboy.cc:1250`).
// The 10-wide stride is why there are only 9 slots per location.
bool companionQuestText(int location, int slot, char* out, size_t outSize);

// Loads the message list now, off the sampling path. Called from the
// session-lifecycle sites in `companion_server.cc` that already reset the
// item catalog, so the one `message_load` happens at a session boundary
// rather than inside a sample. Safe to call repeatedly; a no-op once the
// catalog is loaded or has permanently failed.
void companionWarmQuestCatalog();

// Unloads the message list and drops the cache, returning the module to
// its not-yet-loaded state. Must be called at every site that resets the
// item catalog, or a stale message list leaks across a game restart.
void companionResetQuestCatalog();

} // namespace fallout

#endif /* FALLOUT_COMPANION_QUEST_CATALOG_H_ */
