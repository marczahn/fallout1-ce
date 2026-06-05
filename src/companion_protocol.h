#ifndef FALLOUT_COMPANION_PROTOCOL_H_
#define FALLOUT_COMPANION_PROTOCOL_H_

#include <stddef.h>

#include <string>
#include <string_view>

#include "companion_snapshot.h"

namespace fallout {

enum class CompanionClientMessage {
    Hello,
    GetSnapshot,
    Auth,
    Invalid,
};

std::string companionBuildWorld(bool playerAvailable);
std::string companionBuildSnapshot(unsigned int seq, const CompanionSnapshot& snapshot);

std::string companionBuildPlayerUpdate(unsigned int seq,
    bool playerAvailable,
    const CompanionPlayerSnapshot& current,
    const CompanionPlayerSnapshot& lastSent);

std::string companionBuildPlayerUnavailable(unsigned int seq);

CompanionClientMessage companionParseClientMessage(const char* line, size_t length);

// Extracts the `password` field from a line already known to be an
// `{"type":"auth"...}` message. The `password` field is required by the
// step-2 contract; the parser rejects the message if the field is not
// present. On success returns true and sets `outPassword` to a view into
// `line`; the view is valid for the lifetime of `line`.
bool companionExtractAuthPassword(const char* line, size_t length, std::string_view& outPassword);

} // namespace fallout

#endif /* FALLOUT_COMPANION_PROTOCOL_H_ */
