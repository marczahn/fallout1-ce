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
constexpr char kCompanionKindPlayerStatus[] = "player.status";
constexpr char kCompanionKindPlayerSpecial[] = "player.special";
constexpr char kCompanionKindPlayerProgression[] = "player.progression";
constexpr char kCompanionKindPlayerLocalLocation[] = "player.localLocation";
constexpr char kCompanionKindPlayerWorldLocation[] = "player.worldLocation";
constexpr char kCompanionKindPlayerInventory[] = "player.inventory";

enum class CompanionClientMessage {
    Hello,
    GetSnapshot,
    Auth,
    Cmd,
    GetMap,
    GetMapChunk,
    Invalid,
};

struct CompanionCommandRequest {
    int id;
    std::string_view name;
};

// `world` (handshake response). `schemaVersion` is `5` after adding the
// dedicated world-map image fetch messages.
std::string companionBuildWorld(bool playerAvailable);

// `snapshot` (full state). `payload` is a kind->object map. Only kinds
// valid in the current state are included.
std::string companionBuildSnapshotPayload(const CompanionSnapshot& snapshot);
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

std::string companionBuildStatusUpdate(unsigned int seq,
    const CompanionPlayerStatus& current);

std::string companionBuildSpecialUpdate(unsigned int seq,
    const CompanionPlayerSpecial& current);

std::string companionBuildProgressionUpdate(unsigned int seq,
    const CompanionPlayerProgression& current);

std::string companionBuildLocalLocationUpdate(unsigned int seq,
    const CompanionPlayerLocalLocation& current);

std::string companionBuildWorldLocationUpdate(unsigned int seq,
    const CompanionPlayerWorldLocation& current);

std::string companionBuildInventoryUpdate(unsigned int seq,
    const CompanionInventorySnapshot& current);

// `onPlayerUnavailable`. One-shot on the present -> absent transition.
// No `kind`, no `payload`.
std::string companionBuildOnPlayerUnavailable(unsigned int seq);

// `onPlayerAvailable`. One-shot on the absent -> present transition
// after a steady-state `Ready` connection has been idle. The client is
// expected to send `getSnapshot` in response; the server does not push
// the snapshot itself. No `kind`, no `payload`.
std::string companionBuildOnPlayerAvailable(unsigned int seq);

// `cmdAck`. `error` and `data` are optional; when `data` is present it
// must already be a valid JSON object or array fragment.
std::string companionBuildCmdAck(int id,
    bool ok,
    const char* error = nullptr,
    std::string_view data = {});

// `announce` UDP broadcast. `schemaVersion` follows the live protocol
// version (`5` after adding the world-map image fetch), so discovery and
// TCP advertise the same wire contract.
std::string companionBuildAnnounce(std::string_view host);

// World-map image fetch builders (pure; no worldmap dependency). They
// receive raw data and base64-encode it. Each ends with "\n" like the
// other builders and returns "" only on a formatting failure.
//
// `companionBuildMapHeader` emits the `mapHeader` reply to `getMap`.
// `palette` must point at exactly 768 bytes (256 entries x RGB, already
// normalized to 8-bit). `chunkBytes` is the fixed raw chunk size;
// `chunkCount` is computed as ceil(width*height / chunkBytes).
std::string companionBuildMapHeader(int width,
    int height,
    const unsigned char* palette,
    size_t chunkBytes);

// `companionBuildMapChunk` emits the `mapChunk` reply to `getMapChunk`,
// base64-encoding `data[0..length)`.
std::string companionBuildMapChunk(int index, const unsigned char* data, size_t length);

// `companionBuildMapError` emits the `mapError` line. The server must
// not disconnect the client on a map error.
std::string companionBuildMapError(const char* reason);

CompanionClientMessage companionParseClientMessage(const char* line, size_t length);

// Extracts the `password` field from a line already known to be an
// `{"type":"auth"...}` message. The `password` field is required by the
// step-2 contract; the parser rejects the message if the field is not
// present. On success returns true and sets `outPassword` to a view into
// `line`; the view is valid for the lifetime of `line`.
bool companionExtractAuthPassword(const char* line, size_t length, std::string_view& outPassword);

// Extracts the `id` and `name` fields from a line already known to be a
// `cmd` message. `id` must be a 32-bit integer and `name` must be a JSON
// string. Unknown top-level fields are ignored; malformed JSON returns
// false.
bool companionExtractCommandRequest(const char* line,
    size_t length,
    CompanionCommandRequest& outRequest);

// Extracts the integer `index` from a line already known to be a
// `getMapChunk` message. Walks the JSON object like the `cmd` extractor:
// requires `type` == "getMapChunk" and an int `index`, ignores unknown
// top-level fields, and returns false on malformed JSON.
bool companionExtractMapChunkIndex(const char* line, size_t length, int& outIndex);

} // namespace fallout

#endif /* FALLOUT_COMPANION_PROTOCOL_H_ */
