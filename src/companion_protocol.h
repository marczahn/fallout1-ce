#ifndef FALLOUT_COMPANION_PROTOCOL_H_
#define FALLOUT_COMPANION_PROTOCOL_H_

#include <stddef.h>

#include <string>
#include <vector>
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
constexpr char kCompanionKindPlayerQuests[] = "player.quests";
// THE wire schema version. Single definition site on purpose: this number is
// emitted by both the `world` handshake and the UDP `announce` datagram, and
// when they were two independent string literals they drifted - TASK-024's
// reviewer gate found `announce` still saying 12 while the code emitted 13.
//
// 15 (TASK-026) is the protocol's first NON-additive change: the transmission
// manifest lost `bytes` and `envelopeBytes`. Safe because their only consumer
// reads `index` alone, but that is a fact about today's client, so the bump
// is what records it for any other.
constexpr int kCompanionSchemaVersion = 15;

constexpr char kCompanionKindPlayerHolodisks[] = "player.holodisks";
constexpr char kCompanionKindPlayerTransmissions[] = "player.transmissions";

enum class CompanionClientMessage {
    Hello,
    GetSnapshot,
    Auth,
    Cmd,
    GetMap,
    GetMapChunk,
    GetLocalMap,
    GetLocalMapChunk,
    GetTransmissionManifest,
    GetTransmissionAudio,
    GetTransmissionAudioChunk,
    Invalid,
};

struct CompanionCommandRequest {
    int id;
    std::string_view name;
    int objectId;
    bool hasObjectId;
};

// `world` (handshake response). `schemaVersion` is `15` after the
// transmission manifest became index-only, with audio decoded and degraded
// from `MASTER.DAT` in-process (`14` for holodisk `body` text on
// `player.holodisks` plus pure-ASCII strings on the wire, `13` for the
// `player.holodisks` /
// `player.transmissions` kinds and the transmission manifest/audio fetch, `12`
// for the `player.quests` kind, `11` for live item identity and the two-handed
// marker on `player.inventory`, `10` for the additive per-type detail
// blocks, `9` for `player.localLocation.mapName`, `8` for
// `localMapHeader.explored`, `7` for `player.localLocation.worldX/worldY`,
// `6` for the local-map image fetch, `5` for the world-map image fetch).
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

// `player.quests`. Payload is an object -- `{"quests":[...],"water":{...}}`
// -- rather than a bare array like `player.inventory`, because the Vault 13
// water countdown belongs to the vault, not to any one quest row. Quest
// text is emitted verbatim through `companionAppendEscapedJsonString`.
std::string companionBuildQuestsUpdate(unsigned int seq,
    const CompanionQuestSnapshot& current);

// `player.holodisks`. Payload is an object -- `{"holodisks":[...]}` -- not
// a bare array, so a later archive-level field can be added without
// changing the kind's shape. Rows carry `index`, `title` and, since
// schemaVersion 14, `body`: the disk's document as an array of authored
// lines. An empty `body` means the text could not be resolved, never that
// the disk has none. See `CompanionHolodisk`.
std::string companionBuildHolodisksUpdate(unsigned int seq,
    const CompanionHolodiskSnapshot& current);

// `player.transmissions`. Same object-not-array shape as the holodisk
// kind, but index+title only: a transmission's content is a recording,
// not a document, so it carries no `body`.
std::string companionBuildTransmissionsUpdate(unsigned int seq,
    const CompanionTransmissionSnapshot& current);

// One row of the transmission manifest: a listable movie that exists in the
// DAT and carries an audio track. Deliberately says nothing about whether the
// player has found it - playability and availability are separate sources,
// intersected only at render time on the client.
//
// INDEX ONLY, since schemaVersion 15. `bytes` and `envelopeBytes` were
// removed because under in-engine generation they are properties of a buffer
// that does not exist until the transmission is actually requested - a
// manifest reporting them would either be lying or would force a
// generate-everything burst on connect. They live on the per-transmission
// audio header, which is where they are genuinely known.
struct CompanionTransmissionManifestEntry {
    int index;
};

std::string companionBuildTransmissionManifest(
    const std::vector<CompanionTransmissionManifestEntry>& entries);

// The envelope rides inside this header rather than arriving as chunks:
// the client needs it before the first audio byte, to size the equalizer,
// clamp seeks, and know the track length.
std::string companionBuildTransmissionAudioHeader(int index,
    size_t bytes,
    size_t chunkBytes,
    const unsigned char* envelope,
    size_t envelopeLength);

std::string companionBuildTransmissionAudioChunk(int index,
    int chunk,
    const unsigned char* data,
    size_t length);

// Non-fatal. Reasons: `index` (out of range), `noRecord` (no readable
// asset), `noTransfer` (chunk with no matching header), `tooLarge`,
// `chunk` (formatting). The connection always survives these.
std::string companionBuildTransmissionAudioError(int index, const char* reason);

bool companionExtractTransmissionIndex(const char* line,
    size_t length,
    const char* expectedType,
    int& outIndex);

bool companionExtractTransmissionChunkRequest(const char* line,
    size_t length,
    int& outIndex,
    int& outChunk);

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
// version (`14` after adding holodisk body text), so discovery and TCP
// advertise the same wire contract. Bump it here *and* in
// `companionBuildWorld` -- the smoke test only sees the TCP handshake, so
// an un-bumped broadcast would pass unnoticed.
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

// Local-map (automap) image fetch builders. Mirror the world-map builders
// but carry the engine's automap wall/scenery classes (one byte per tile:
// 0=empty, 1=wall, 2=scenery) for the *current* map+elevation, which both
// the header and each chunk echo so the client can detect a mid-fetch
// map/elevation change. `localMapHeader` also carries `explored`, which is
// true when the current local map has seen data even if the rendered image is
// still all-zero because there are no drawable walls/scenery. `palette` is
// exactly 768 bytes (256 entries x RGB, 8-bit; only indices 0/1/2 are
// meaningful). Each ends with "\n" and returns "" only on a formatting
// failure.
std::string companionBuildLocalMapHeader(int map,
    int elevation,
    int width,
    int height,
    bool explored,
    const unsigned char* palette,
    size_t chunkBytes);

std::string companionBuildLocalMapChunk(int index,
    int map,
    int elevation,
    const unsigned char* data,
    size_t length);

std::string companionBuildLocalMapError(const char* reason);

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

// As `companionExtractMapChunkIndex`, but for a line already known to be a
// `getLocalMapChunk` message (requires `type` == "getLocalMapChunk").
bool companionExtractLocalMapChunkIndex(const char* line, size_t length, int& outIndex);

} // namespace fallout

#endif /* FALLOUT_COMPANION_PROTOCOL_H_ */
