#include "companion_quest_catalog.h"

#include <stdio.h>
#include <string.h>

#include <string>
#include <unordered_map>

#include "game/game.h"
#include "game/message.h"
#include "platform_compat.h"
#include "plib/gnw/debug.h"

namespace fallout {

namespace {

// Tri-state, not a bool: `Failed` is sticky. A broken or missing
// `pipboy.msg` must cost exactly one `message_load` attempt per session,
// not one per sample - the companion server samples on the engine's frame
// loop, so a retry-on-every-miss would be file I/O at frame rate.
enum class QuestCatalogState {
    NotLoaded,
    Loaded,
    Failed,
};

QuestCatalogState gQuestCatalogState = QuestCatalogState::NotLoaded;
MessageList gQuestMessageList;

// Keyed by `pipboy.msg` message id. Misses are cached as empty strings so
// an absent id is not re-searched on every sample. Bounded by the tables
// it serves (12 locations + 12*9 quest slots, 18 holodisk titles, 14
// transmission titles, and the 18 holodisk bodies at ~1030 lines
// including their `**END-PAR**` and `**END-DISK**` markers), so it never
// grows large - about 1.2k entries and ~37 KiB of text at the absolute
// maximum, reached only if the player finds every disk.
std::unordered_map<int, std::string> gQuestTextCache;

bool ensureLoaded()
{
    switch (gQuestCatalogState) {
    case QuestCatalogState::Loaded:
        return true;
    case QuestCatalogState::Failed:
        return false;
    case QuestCatalogState::NotLoaded:
        break;
    }

    if (!message_init(&gQuestMessageList)) {
        gQuestCatalogState = QuestCatalogState::Failed;
        debug_printf("companion: quest catalog message_init failed\n");
        return false;
    }

    // The same path `pipboy.cc:628-629` builds.
    char path[COMPAT_MAX_PATH];
    snprintf(path, sizeof(path), "%s%s", msg_path, "pipboy.msg");

    if (!message_load(&gQuestMessageList, path)) {
        message_exit(&gQuestMessageList);
        gQuestCatalogState = QuestCatalogState::Failed;
        debug_printf("companion: quest catalog failed to load %s\n", path);
        return false;
    }

    gQuestCatalogState = QuestCatalogState::Loaded;
    return true;
}

// Resolves one message id, caching the result. Uses `message_search`
// rather than `getmsg` deliberately: `getmsg` substitutes the literal
// string "Error" for a missing id and returns it as if it were real text
// (`message.cc`), which would put "Error" on the wire as a quest line.
// `message_search` reports the miss, letting the caller emit an empty
// string the client can render as a visible failure instead.
const std::string* resolveMessage(int messageId)
{
    auto it = gQuestTextCache.find(messageId);
    if (it != gQuestTextCache.end()) {
        return &it->second;
    }

    if (!ensureLoaded()) {
        return nullptr;
    }

    MessageListItem entry = {};
    entry.num = messageId;

    std::string text;
    if (message_search(&gQuestMessageList, &entry) && entry.text != nullptr) {
        // `entry.text` points into the message list's own storage, which
        // `companionResetQuestCatalog` frees. Copy immediately - the same
        // rule `companion_snapshot.cc` documents for `map_get_short_name`.
        text = entry.text;
    }

    auto inserted = gQuestTextCache.emplace(messageId, std::move(text));
    return &inserted.first->second;
}

bool copyMessage(int messageId, char* out, size_t outSize)
{
    if (out == nullptr || outSize == 0) {
        return false;
    }

    out[0] = '\0';

    const std::string* text = resolveMessage(messageId);
    if (text == nullptr || text->empty()) {
        return false;
    }

    strncpy(out, text->c_str(), outSize - 1);
    out[outSize - 1] = '\0';
    return true;
}

} // namespace

bool companionQuestLocationName(int location, char* out, size_t outSize)
{
    return copyMessage(700 + 10 * location, out, outSize);
}

bool companionQuestText(int location, int slot, char* out, size_t outSize)
{
    return copyMessage(701 + 10 * location + slot, out, outSize);
}

bool companionHolodiskTitle(int index, char* out, size_t outSize)
{
    return copyMessage(400 + index, out, outSize);
}

bool companionHolodiskBody(int index, std::vector<std::string>& out)
{
    out.clear();

    // The engine's own bounds and sentinels (`ShowHoloDisk`,
    // `pipboy.cc:1355-1363`). Kept as the same arithmetic rather than
    // pulled into a constant, so the two walks stay visibly identical.
    const int first = 1000 * index + 1000;
    const int last = 1000 * index + 1500;

    for (int messageId = first; messageId < last; ++messageId) {
        const std::string* line = resolveMessage(messageId);
        if (line == nullptr) {
            // Catalog unavailable. Distinct from a resolvable-but-absent
            // id only in cause, not in consequence.
            out.clear();
            return false;
        }

        if (line->empty()) {
            // `resolveMessage` caches a miss as an empty string, and no
            // real holodisk line is empty - a blank line is spelled
            // `**END-PAR**`. So this is a gap in the message file, and a
            // body with a hole in it is not a body.
            debug_printf("companion: holodisk %d missing message %d\n", index, messageId);
            out.clear();
            return false;
        }

        if (*line == "**END-DISK**") {
            return true;
        }

        if (*line == "**END-PAR**") {
            out.emplace_back();
            continue;
        }

        out.push_back(*line);
    }

    // Mirrors the engine's own `"Holodisk text end not found!"`.
    debug_printf("companion: holodisk %d text end not found\n", index);
    out.clear();
    return false;
}

bool companionTransmissionTitle(int movie, char* out, size_t outSize)
{
    return copyMessage(500 + movie, out, outSize);
}

void companionWarmQuestCatalog()
{
    if (ensureLoaded()) {
        return;
    }

    // A failed *warm* does not stick. The warm runs at server init, which
    // is early: if the message database is not ready yet the load fails
    // for a reason that has nothing to do with the install being broken,
    // and a sticky `Failed` there would leave every quest line empty for
    // the whole session with no way back. Dropping to `NotLoaded` gives
    // the sampling path exactly one more attempt, and *that* one sticks -
    // so the worst case is two `message_load` calls per session, never
    // one per sample.
    gQuestCatalogState = QuestCatalogState::NotLoaded;
}

void companionResetQuestCatalog()
{
    if (gQuestCatalogState == QuestCatalogState::Loaded) {
        message_exit(&gQuestMessageList);
    }

    gQuestTextCache.clear();
    gQuestCatalogState = QuestCatalogState::NotLoaded;
}

} // namespace fallout
