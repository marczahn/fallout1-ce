#ifndef FALLOUT_COMPANION_PROTOCOL_H_
#define FALLOUT_COMPANION_PROTOCOL_H_

#include <stddef.h>

#include <string>
#include <string_view>

#include "companion_snapshot.h"

namespace fallout {

// `kind` values for `update` messages and for the keys of
// `snapshot.payload`. Namespaced as `player.<aspect>`. New aspects land
// as new `kind` values plus a new builder in this header.
constexpr char kCompanionKindPlayerVitals[] = "player.vitals";
constexpr char kCompanionKindPlayerLocalLocation[] = "player.local_location";
constexpr char kCompanionKindPlayerWorldLocation[] = "player.world_location";

enum class CompanionClientMessage {
    Hello,
    GetSnapshot,
    Auth,
    Invalid,
};

// `world` (handshake response). `schemaVersion` is `3` as of T0.
std::string companionBuildWorld(bool playerAvailable);

// `snapshot` (full state). `payload` is a kind->object map. Only kinds
// valid in the current state are included.
std::string companionBuildSnapshot(unsigned int seq, const CompanionSnapshot& snapshot);

// `update` builders, one per kind. Each emits a `kind`-tagged `update`
// whose `payload` is the *complete* per-kind object (all schema fields
// present). The server decides whether to call a builder by comparing
// the current sample to its last-sent state; the protocol layer does
// no diffing. Returns an empty string only on a formatting failure,
// which is a bug -- the server must not call a builder for a kind
// that is not meaningful in the current surface.
std::string companionBuildVitalsUpdate(unsigned int seq,
    const CompanionPlayerVitals& current);

std::string companionBuildLocalLocationUpdate(unsigned int seq,
    const CompanionPlayerLocalLocation& current);

std::string companionBuildWorldLocationUpdate(unsigned int seq,
    const CompanionPlayerWorldLocation& current);

// `player_unavailable`. One-shot on the present -> absent transition.
// No `kind`, no `payload`.
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
