#ifndef FALLOUT_COMPANION_QUEST_CATALOG_H_
#define FALLOUT_COMPANION_QUEST_CATALOG_H_

#include <cstddef>
#include <string>
#include <vector>

namespace fallout {

// Resolved `pipboy.msg` text for the quest screen, and for holodisk
// titles (TASK-024). The module keeps its `quest` name because it is one
// `MessageList` over one file with one lifecycle - splitting holodisks
// into a parallel catalog would mean a second `message_load` of the very
// same `pipboy.msg`, and a second warm/reset pair to keep in sync.
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

// Holodisk title, message id `400 + index` (`pipboy.cc:1485`), for the
// in-game STATUS screen's document list. A *different* range from the
// body text below.
bool companionHolodiskTitle(int index, char* out, size_t outSize);

// Holodisk body text: message ids `1000 * index + 1000` upward, one line
// per id, terminated by the `**END-DISK**` sentinel - the same walk
// `ShowHoloDisk` performs (`pipboy.cc:1355-1432`).
//
// Two markers live in this range and NEITHER is ever emitted:
//
//  * `**END-DISK**` ends the disk.
//  * `**END-PAR**` is a blank line. The engine prints nothing for it and
//    advances one line (`pipboy.cc:1425-1427`); it appears 122 times
//    across the 18 bodies. It is returned as an EMPTY STRING so the
//    client renders the same vertical gap without ever seeing a literal.
//
// **All or nothing.** On any failure - an id the catalog cannot resolve,
// or reaching the engine's own `+1500` bound with no sentinel - `out` is
// cleared and `false` is returned. A partial body is deliberately NOT
// forwarded: "empty body" is then the single unambiguous signal the
// client renders as a visible failure, instead of a truncated document
// that looks complete. All 18 disks are verified terminated, so this
// path means a modded or damaged `pipboy.msg`.
//
// Unlike the engine's loop, which uses `getmsg` and therefore silently
// substitutes the literal string "Error" for a missing id, this walks
// `message_search` - see `resolveMessage`. "Error" must never reach the
// wire as a line of a holodisk.
bool companionHolodiskBody(int index, std::vector<std::string>& out);

// Transmission (replayable cutscene) title, message id `500 + movie`
// (`ListArchive`, `pipboy.cc:1801`). A DIFFERENT range from the holodisk
// titles above, for a different screen: `PipArchives` lists movies, while
// `PipStatus` lists holodisks. Note two movies legitimately share a title
// ("Leaving Vault", `MOVIE_WALKM` and `MOVIE_WALKW`), so callers must key
// on the movie index and never on this string.
bool companionTransmissionTitle(int movie, char* out, size_t outSize);

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
