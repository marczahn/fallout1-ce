#ifndef FALLOUT_COMPANION_PROTOCOL_H_
#define FALLOUT_COMPANION_PROTOCOL_H_

#include <stddef.h>

#include <string>

#include "companion_snapshot.h"

namespace fallout {

enum class CompanionClientMessage {
    Hello,
    GetSnapshot,
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

} // namespace fallout

#endif /* FALLOUT_COMPANION_PROTOCOL_H_ */
