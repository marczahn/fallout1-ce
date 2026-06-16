// Wire format: one JSON object per line (newline-delimited JSON, UTF-8).
// All field names use camelCase; type identifiers and kind strings are
// lowercase or dot-namespaced.
//
// Client -> server (TCP):
//   {"type":"auth","password":"<string>"}   handshake; must be the first message
//   {"type":"hello"}              post-auth handshake; second message
//   {"type":"getSnapshot"}       request a full snapshot
//   {"type":"cmd","id":N,"name":"X","args":{...}}
//                                          step-2 command channel (T6)
//
// Client -> server (UDP, autodiscovery, T7):
//   {"type":"discover"}           sent to the configured discovery port
//                                 (28080); the server replies with one
//                                 `announce` datagram to the sender. The
//                                 client uses the announce's host/port
//                                 to open the TCP session, then runs the
//                                 normal auth/hello handshake.
//
// Server -> client:
//   {"type":"world","schemaVersion":4,"game":"fallout1-ce","playerAvailable":bool}
//
//   {"type":"snapshot","seq":N,"playerAvailable":bool,"payload":{
//      "player.vitals":          {"hp":H,"maxHp":M},
//      "player.status":          {"armorClass":A,"carryWeight":W,
//                                 "currentCarryWeight":CW,
//                                 "meleeDamage":MD,
//                                 "damageResistance":DR,
//                                 "poisonResistance":P,
//                                 "radiationResistance":R,
//                                 "healingRate":HR,
//                                 "radiation":RAD,"poison":PSN},
//      "player.special":         {"strength":S,"perception":P,
//                                 "endurance":E,"charisma":C,
//                                 "intelligence":I,"agility":A,
//                                 "luck":L},
//      "player.progression":     {"level":L,"experience":X,
//                                 "nextLevelExp":N},
//      "player.localLocation":  {"tile":T,"elevation":E,"map":M,
//                                 "location":"<name>","locationId":"<id>"},
//      "player.worldLocation":  {"x":X,"y":Y},
//      "player.inventory":       [{"pid":P,"protoId":"<id>","name":"<name>",
//                                   "type":"<type>","count":N,"slot":"<slot>"}]
//   }}
//   The `payload` of `snapshot` is a kind->object map. Only kinds valid
//   in the current state are present. `player.localLocation` and
//   `player.worldLocation` are mutually exclusive (driven by
//   `CompanionPlayerSurface`).
//
//   {"type":"update","seq":N,"playerAvailable":true,
//      "kind":"<kind>",
//      "payload":{<complete per-kind object>}}
//   `kind` is the discriminator; `payload` is the *complete* per-kind
//   object (all schema fields present, not a field-level diff). The
//   current kinds are:
//     "player.vitals":          payload fields are {hp, maxHp}
//     "player.status":          payload fields are {armorClass,
//                               currentCarryWeight, carryWeight,
//                               meleeDamage, damageResistance,
//                               poisonResistance, radiationResistance,
//                               healingRate, radiation, poison}
//     "player.special":         payload fields are {strength,
//                               perception, endurance, charisma,
//                               intelligence, agility, luck}
//     "player.progression":     payload fields are {level,
//                               experience, nextLevelExp}
//     "player.localLocation":  payload fields are {tile, elevation,
//                               map, location, locationId}
//     "player.worldLocation":  payload fields are {x, y}
//     "player.inventory":       payload is the complete inventory array
//   `playerAvailable` in the envelope is always `true` for an `update`:
//   the server only emits `update` while the player is loaded. When
//   the player is not loaded, the server emits `onPlayerUnavailable`
//   instead.
//
//   {"type":"onPlayerUnavailable","seq":N,"playerAvailable":false}
//
//   {"type":"onPlayerAvailable","seq":N,"playerAvailable":true}
//   One-shot on the absent -> present transition while a steady-state
//   `Ready` connection has been idle. The client is expected to send
//   `getSnapshot` in response; the server does not push the snapshot
//   itself. This closes the no-signal window that would otherwise only
//   open on the next field-level `update`.
//
//   {"type":"cmdAck","id":N,"ok":bool,"error":"<string>"?,"data":{...}?}
//
// `world` has no `seq`, no `payload`. `snapshot` has no `kind`; the
// `payload` *is* the kind dispatch. `update` always has `kind` and
// `payload`. `onPlayerUnavailable` and `onPlayerAvailable` have
// neither.
//
// T0 changes from step 1/2:
//   - `world.schemaVersion` is now `4` (was `1`, then `2`, then `3`).
//   - `update` no longer carries `entity`; the entity is encoded in
//     the `kind` namespace (e.g. `player.vitals`).
//   - `update.data` is renamed to `update.payload`. The payload is
//     always the complete per-kind object (not a field-level diff).
//   - `snapshot.data` is renamed to `snapshot.payload`. The payload
//     shape changed from a single flat object to a kind->object map.
// A step-1/step-2 client is intentionally broken by these changes; the
// `schemaVersion` bump makes the break visible.

#include "companion_protocol.h"

#include <stdarg.h>
#include <limits.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

#include "game/proto_types.h"

namespace fallout {

namespace {

constexpr char kHello[] = R"({"type":"hello"})";
constexpr char kGetSnapshot[] = R"({"type":"getSnapshot"})";
constexpr char kAuthPrefix[] = R"({"type":"auth")";
constexpr char kCmdPrefix[] = R"({"type":"cmd")";
constexpr size_t kHelloLen = sizeof(kHello) - 1;
constexpr size_t kGetSnapshotLen = sizeof(kGetSnapshot) - 1;
constexpr size_t kAuthPrefixLen = sizeof(kAuthPrefix) - 1;
constexpr size_t kCmdPrefixLen = sizeof(kCmdPrefix) - 1;

constexpr char kVitalsKind[] = "player.vitals";
constexpr char kStatusKind[] = "player.status";
constexpr char kSpecialKind[] = "player.special";
constexpr char kProgressionKind[] = "player.progression";
constexpr char kLocalLocationKind[] = "player.localLocation";
constexpr char kWorldLocationKind[] = "player.worldLocation";
constexpr char kInventoryKind[] = "player.inventory";

const char* inventoryTypeName(int type)
{
    switch (type) {
    case ITEM_TYPE_ARMOR:
        return "armor";
    case ITEM_TYPE_CONTAINER:
        return "container";
    case ITEM_TYPE_DRUG:
        return "drug";
    case ITEM_TYPE_WEAPON:
        return "weapon";
    case ITEM_TYPE_AMMO:
        return "ammo";
    case ITEM_TYPE_MISC:
        return "misc";
    case ITEM_TYPE_KEY:
        return "key";
    default:
        return "unknown";
    }
}

const char* inventorySlotName(CompanionInventorySlot slot)
{
    switch (slot) {
    case CompanionInventorySlot::Worn:
        return "worn";
    case CompanionInventorySlot::RightHand:
        return "rightHand";
    case CompanionInventorySlot::LeftHand:
        return "leftHand";
    case CompanionInventorySlot::None:
    default:
        return "none";
    }
}

std::string buildVitalsBody(const CompanionPlayerVitals& vitals)
{
    char body[64];
    int n = snprintf(body,
        sizeof(body),
        R"({"hp":%d,"maxHp":%d})",
        vitals.hp,
        vitals.maxHp);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildStatusBody(const CompanionPlayerStatus& status)
{
    char body[256];
    int n = snprintf(body,
        sizeof(body),
        R"({"armorClass":%d,"currentCarryWeight":%d,"carryWeight":%d,"meleeDamage":%d,"damageResistance":%d,"poisonResistance":%d,"radiationResistance":%d,"healingRate":%d,"radiation":%d,"poison":%d})",
        status.armorClass,
        status.currentCarryWeight,
        status.carryWeight,
        status.meleeDamage,
        status.damageResistance,
        status.poisonResistance,
        status.radiationResistance,
        status.healingRate,
        status.radiation,
        status.poison);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildSpecialBody(const CompanionPlayerSpecial& special)
{
    char body[160];
    int n = snprintf(body,
        sizeof(body),
        R"({"strength":%d,"perception":%d,"endurance":%d,"charisma":%d,"intelligence":%d,"agility":%d,"luck":%d})",
        special.strength,
        special.perception,
        special.endurance,
        special.charisma,
        special.intelligence,
        special.agility,
        special.luck);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildProgressionBody(const CompanionPlayerProgression& progression)
{
    char body[96];
    int n = snprintf(body,
        sizeof(body),
        R"({"level":%d,"experience":%d,"nextLevelExp":%d})",
        progression.level,
        progression.experience,
        progression.nextLevelExp);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildLocalLocationBody(const CompanionPlayerLocalLocation& loc)
{
    char body[256];
    int n;
    if (loc.location[0] == '\0') {
        n = snprintf(body,
            sizeof(body),
            R"({"tile":%d,"elevation":%d,"map":%d,"location":null,"locationId":"%s"})",
            loc.tile,
            loc.elevation,
            loc.map,
            loc.locationId);
    } else {
        n = snprintf(body,
            sizeof(body),
            R"({"tile":%d,"elevation":%d,"map":%d,"location":"%s","locationId":"%s"})",
            loc.tile,
            loc.elevation,
            loc.map,
            loc.location,
            loc.locationId);
    }
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildWorldLocationBody(const CompanionPlayerWorldLocation& loc)
{
    char body[64];
    int n = snprintf(body,
        sizeof(body),
        R"({"x":%d,"y":%d})",
        loc.x,
        loc.y);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(body)) {
        return std::string();
    }
    return std::string(body, static_cast<size_t>(n));
}

std::string buildInventoryPayload(const CompanionInventorySnapshot& inventory)
{
    std::string body;
    body.reserve(2 + inventory.items.size() * 128);
    body.push_back('[');

    for (size_t index = 0; index < inventory.items.size(); ++index) {
        const CompanionInventoryItem& item = inventory.items[index];
        if (index != 0) {
            body.push_back(',');
        }

        char entry[320];
        int n = snprintf(entry,
            sizeof(entry),
            R"({"pid":%d,"protoId":"%s","name":"%s","type":"%s","count":%d,"slot":"%s"})",
            item.pid,
            item.protoId,
            item.name,
            inventoryTypeName(item.type),
            item.count,
            inventorySlotName(item.slot));
        if (n < 0 || static_cast<size_t>(n) >= sizeof(entry)) {
            return std::string();
        }

        body.append(entry, static_cast<size_t>(n));
    }

    body.push_back(']');
    return body;
}

void skipWhitespace(const char*& p, const char* end)
{
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) {
        ++p;
    }
}

bool parseJsonStringView(const char*& p, const char* end, std::string_view& out)
{
    skipWhitespace(p, end);
    if (p >= end || *p != '"') {
        return false;
    }

    const char* valueStart = ++p;
    while (p < end) {
        if (*p == '\\') {
            return false;
        }
        if (*p == '"') {
            out = std::string_view(valueStart, static_cast<size_t>(p - valueStart));
            ++p;
            return true;
        }
        ++p;
    }

    return false;
}

bool parseJsonInt32(const char*& p, const char* end, int& out)
{
    skipWhitespace(p, end);
    if (p >= end) {
        return false;
    }

    bool negative = false;
    if (*p == '-') {
        negative = true;
        ++p;
    }

    if (p >= end || *p < '0' || *p > '9') {
        return false;
    }

    long long value = 0;
    while (p < end && *p >= '0' && *p <= '9') {
        value = value * 10 + (*p - '0');
        long long signedValue = negative ? -value : value;
        if (signedValue < INT_MIN || signedValue > INT_MAX) {
            return false;
        }
        ++p;
    }

    out = negative ? -static_cast<int>(value) : static_cast<int>(value);
    return true;
}

bool skipJsonValue(const char*& p, const char* end)
{
    skipWhitespace(p, end);
    if (p >= end) {
        return false;
    }

    if (*p == '"') {
        std::string_view ignored;
        return parseJsonStringView(p, end, ignored);
    }

    if (*p == '{' || *p == '[') {
        char open = *p;
        char close = open == '{' ? '}' : ']';
        int depth = 0;

        while (p < end) {
            if (*p == '"') {
                std::string_view ignored;
                if (!parseJsonStringView(p, end, ignored)) {
                    return false;
                }
                continue;
            }

            if (*p == open) {
                ++depth;
            } else if (*p == close) {
                --depth;
                ++p;
                if (depth == 0) {
                    return true;
                }
                continue;
            }

            ++p;
        }

        return false;
    }

    if ((*p >= '0' && *p <= '9') || *p == '-') {
        int ignored;
        return parseJsonInt32(p, end, ignored);
    }

    static constexpr char kTrue[] = "true";
    static constexpr char kFalse[] = "false";
    static constexpr char kNull[] = "null";
    if (static_cast<size_t>(end - p) >= sizeof(kTrue) - 1
        && memcmp(p, kTrue, sizeof(kTrue) - 1) == 0) {
        p += sizeof(kTrue) - 1;
        return true;
    }
    if (static_cast<size_t>(end - p) >= sizeof(kFalse) - 1
        && memcmp(p, kFalse, sizeof(kFalse) - 1) == 0) {
        p += sizeof(kFalse) - 1;
        return true;
    }
    if (static_cast<size_t>(end - p) >= sizeof(kNull) - 1
        && memcmp(p, kNull, sizeof(kNull) - 1) == 0) {
        p += sizeof(kNull) - 1;
        return true;
    }

    return false;
}

} // namespace

std::string companionBuildWorld(bool playerAvailable)
{
    const char* flag = playerAvailable ? "true" : "false";
    char buffer[96];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"world","schemaVersion":4,"game":"fallout1-ce","playerAvailable":%s})"
        "\n",
        flag);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildSnapshotPayload(const CompanionSnapshot& snapshot)
{
    std::string inner;
    inner.reserve(1024);
    bool first = true;

    auto appendKind = [&](const char* kind, const char* body) -> bool {
        if (body == nullptr) {
            return false;
        }

        if (!first) {
            inner.push_back(',');
        }
        inner.push_back('"');
        inner.append(kind);
        inner.append("\":");
        inner.append(body);
        first = false;
        return true;
    };

    // Vitals are always present when the player is loaded (real map or
    // world map).
    if (snapshot.hasPlayer) {
        std::string body = buildVitalsBody(snapshot.vitals);
        if (body.empty() || !appendKind(kVitalsKind, body.c_str())) {
            return std::string();
        }

        body = buildStatusBody(snapshot.status);
        if (body.empty() || !appendKind(kStatusKind, body.c_str())) {
            return std::string();
        }

        body = buildSpecialBody(snapshot.special);
        if (body.empty() || !appendKind(kSpecialKind, body.c_str())) {
            return std::string();
        }

        body = buildProgressionBody(snapshot.progression);
        if (body.empty() || !appendKind(kProgressionKind, body.c_str())) {
            return std::string();
        }
    }

    if (snapshot.hasPlayer && snapshot.surface == CompanionPlayerSurface::Local) {
        std::string body = buildLocalLocationBody(snapshot.localLocation);
        if (body.empty() || !appendKind(kLocalLocationKind, body.c_str())) {
            return std::string();
        }
    }

    if (snapshot.hasPlayer && snapshot.surface == CompanionPlayerSurface::World) {
        std::string body = buildWorldLocationBody(snapshot.worldLocation);
        if (body.empty() || !appendKind(kWorldLocationKind, body.c_str())) {
            return std::string();
        }
    }

    if (snapshot.hasPlayer) {
        std::string inventoryBody = buildInventoryPayload(snapshot.inventory);
        if (inventoryBody.empty() && !snapshot.inventory.items.empty()) {
            return std::string();
        }
        if (!appendKind(kInventoryKind, inventoryBody.c_str())) {
            return std::string();
        }
    }

    std::string payload;
    payload.reserve(inner.size() + 2);
    payload.push_back('{');
    payload.append(inner);
    payload.push_back('}');
    return payload;
}

std::string companionBuildSnapshot(unsigned int seq, const CompanionSnapshot& snapshot)
{
    const char* flag = snapshot.hasPlayer ? "true" : "false";
    std::string payload = companionBuildSnapshotPayload(snapshot);
    if (payload.empty()) {
        return std::string();
    }

    char prefix[96];
    int prefixLen = snprintf(prefix,
        sizeof(prefix),
        R"({"type":"snapshot","seq":%u,"playerAvailable":%s,"payload":{)",
        seq,
        flag);
    if (prefixLen < 0 || static_cast<size_t>(prefixLen) >= sizeof(prefix)) {
        return std::string();
    }

    std::string message;
    message.reserve(static_cast<size_t>(prefixLen) + payload.size() + 3);
    message.append(prefix, static_cast<size_t>(prefixLen));
    message.append(payload.data() + 1, payload.size() - 2);
    message.append("}}\n");
    return message;
}

namespace {

// Shared emitter for the per-kind `update` builders. Wraps the
// per-kind `payload` literal `body` in the standard envelope:
//
//   {"type":"update","seq":S,"playerAvailable":true,"kind":"K","payload":B}
//
// `playerAvailable` is hardcoded to `true` in the envelope: the server
// only invokes an update builder while the player is loaded. When the
// player is not loaded, the server emits `onPlayerUnavailable`
// instead.
//
// Returns an empty string on any formatting failure.
std::string wrapUpdate(unsigned int seq,
    const char* kind,
    const char* body)
{
    if (body == nullptr) {
        return std::string();
    }

    char prefix[128];
    int prefixLen = snprintf(prefix,
        sizeof(prefix),
        R"({"type":"update","seq":%u,"playerAvailable":true,"kind":"%s","payload":)",
        seq,
        kind);
    if (prefixLen < 0 || static_cast<size_t>(prefixLen) >= sizeof(prefix)) {
        return std::string();
    }

    std::string message;
    message.reserve(static_cast<size_t>(prefixLen) + strlen(body) + 3);
    message.append(prefix, static_cast<size_t>(prefixLen));
    message.append(body);
    message.append("}\n");
    return message;
}

} // namespace

std::string companionBuildVitalsUpdate(unsigned int seq,
    const CompanionPlayerVitals& current)
{
    std::string body = buildVitalsBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kVitalsKind, body.c_str());
}

std::string companionBuildStatusUpdate(unsigned int seq,
    const CompanionPlayerStatus& current)
{
    std::string body = buildStatusBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kStatusKind, body.c_str());
}

std::string companionBuildSpecialUpdate(unsigned int seq,
    const CompanionPlayerSpecial& current)
{
    std::string body = buildSpecialBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kSpecialKind, body.c_str());
}

std::string companionBuildProgressionUpdate(unsigned int seq,
    const CompanionPlayerProgression& current)
{
    std::string body = buildProgressionBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kProgressionKind, body.c_str());
}

std::string companionBuildLocalLocationUpdate(unsigned int seq,
    const CompanionPlayerLocalLocation& current)
{
    std::string body = buildLocalLocationBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kLocalLocationKind, body.c_str());
}

std::string companionBuildWorldLocationUpdate(unsigned int seq,
    const CompanionPlayerWorldLocation& current)
{
    std::string body = buildWorldLocationBody(current);
    if (body.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kWorldLocationKind, body.c_str());
}

std::string companionBuildInventoryUpdate(unsigned int seq,
    const CompanionInventorySnapshot& current)
{
    std::string body = buildInventoryPayload(current);
    if (body.empty() && !current.items.empty()) {
        return std::string();
    }
    return wrapUpdate(seq, kInventoryKind, body.c_str());
}

std::string companionBuildOnPlayerUnavailable(unsigned int seq)
{
    char buffer[80];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"onPlayerUnavailable","seq":%u,"playerAvailable":false})"
        "\n",
        seq);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildOnPlayerAvailable(unsigned int seq)
{
    char buffer[80];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"onPlayerAvailable","seq":%u,"playerAvailable":true})"
        "\n",
        seq);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildCmdAck(int id,
    bool ok,
    const char* error,
    std::string_view data)
{
    char prefix[96];
    int prefixLen = snprintf(prefix,
        sizeof(prefix),
        R"({"type":"cmdAck","id":%d,"ok":%s)",
        id,
        ok ? "true" : "false");
    if (prefixLen < 0 || static_cast<size_t>(prefixLen) >= sizeof(prefix)) {
        return std::string();
    }

    std::string message;
    message.reserve(static_cast<size_t>(prefixLen) + data.size() + 64);
    message.append(prefix, static_cast<size_t>(prefixLen));
    if (error != nullptr) {
        message.append(R"(,"error":")");
        message.append(error);
        message.push_back('"');
    }
    if (!data.empty()) {
        message.append(R"(,"data":)");
        message.append(data);
    }
    message.append("}\n");
    return message;
}

std::string companionBuildAnnounce(std::string_view host)
{
    std::string message;
    message.reserve(host.size() + 96);
    message.append(R"({"type":"announce","game":"fallout1-ce","schemaVersion":4,"host":")");
    message.append(host);
    message.append(R"(","port":28080,"authRequired":true})"
                   "\n");
    return message;
}

CompanionClientMessage companionParseClientMessage(const char* line, size_t length)
{
    if (line == nullptr || length == 0) {
        return CompanionClientMessage::Invalid;
    }

    // Skip leading whitespace; the auth prefix match tolerates any amount
    // of leading whitespace, while hello and getSnapshot are exact-shape
    // matches after full stripping. The prefix check is done on the
    // original line so that an auth message with a long password does
    // not have to fit in a small stripped buffer.
    size_t start = 0;
    while (start < length
        && (line[start] == ' ' || line[start] == '\t' || line[start] == '\n' || line[start] == '\r')) {
        ++start;
    }
    if (start == length) {
        return CompanionClientMessage::Invalid;
    }
    // Auth prefix match with whitespace tolerance around the `:`. The
    // canonical form is `{"type":"auth"`, but Python's `json.dumps` and
    // most other JSON emitters produce `{"type": "auth"` (with a space
    // after the colon) by default. Accept both. Other whitespace
    // patterns (e.g. tabs) are not currently exercised by any client
    // and are rejected; add them here if a real client needs them.
    if (length - start >= kAuthPrefixLen
        && memcmp(line + start, kAuthPrefix, kAuthPrefixLen) == 0) {
        return CompanionClientMessage::Auth;
    }
    static constexpr char kAuthPrefixSpaced[] = R"({"type": "auth")";
    constexpr size_t kAuthPrefixSpacedLen = sizeof(kAuthPrefixSpaced) - 1;
    if (length - start >= kAuthPrefixSpacedLen
        && memcmp(line + start, kAuthPrefixSpaced, kAuthPrefixSpacedLen) == 0) {
        return CompanionClientMessage::Auth;
    }
    if (length - start >= kCmdPrefixLen
        && memcmp(line + start, kCmdPrefix, kCmdPrefixLen) == 0) {
        return CompanionClientMessage::Cmd;
    }
    static constexpr char kCmdPrefixSpaced[] = R"({"type": "cmd")";
    constexpr size_t kCmdPrefixSpacedLen = sizeof(kCmdPrefixSpaced) - 1;
    if (length - start >= kCmdPrefixSpacedLen
        && memcmp(line + start, kCmdPrefixSpaced, kCmdPrefixSpacedLen) == 0) {
        return CompanionClientMessage::Cmd;
    }

    char stripped[64];
    size_t j = 0;
    for (size_t i = 0; i < length; ++i) {
        char c = line[i];
        if (c == ' ' || c == '\t' || c == '\n' || c == '\r') {
            continue;
        }
        if (j >= sizeof(stripped)) {
            return CompanionClientMessage::Invalid;
        }
        stripped[j++] = c;
    }

    if (j == kHelloLen && memcmp(stripped, kHello, kHelloLen) == 0) {
        return CompanionClientMessage::Hello;
    }
    if (j == kGetSnapshotLen && memcmp(stripped, kGetSnapshot, kGetSnapshotLen) == 0) {
        return CompanionClientMessage::GetSnapshot;
    }
    return CompanionClientMessage::Invalid;
}

bool companionExtractAuthPassword(const char* line, size_t length, std::string_view& outPassword)
{
    // Walks the `{"type":"auth","password":"..."}` object as generic
    // JSON key/value pairs, reusing the same parsing primitives as the
    // `cmd` extractor. Whitespace around `:` and after `,` is tolerated
    // by `skipWhitespace`. Unknown top-level fields are ignored. We do
    // not handle escape sequences inside the password string; the
    // expected password is opaque UTF-8 without `\"` or `\\` and a
    // literal `"` terminates early. `password` is required.
    if (line == nullptr || length == 0) {
        return false;
    }

    const char* p = line;
    const char* end = line + length;
    skipWhitespace(p, end);
    if (p >= end || *p != '{') {
        return false;
    }
    ++p;

    bool sawType = false;
    bool sawPassword = false;

    while (true) {
        skipWhitespace(p, end);
        if (p >= end) {
            return false;
        }

        if (*p == '}') {
            ++p;
            break;
        }

        std::string_view key;
        if (!parseJsonStringView(p, end, key)) {
            return false;
        }

        skipWhitespace(p, end);
        if (p >= end || *p != ':') {
            return false;
        }
        ++p;

        if (key == "type") {
            std::string_view type;
            if (!parseJsonStringView(p, end, type) || type != "auth") {
                return false;
            }
            sawType = true;
        } else if (key == "password") {
            // The password value is treated as opaque bytes between the
            // opening and closing `"`. Backslashes are NOT escape
            // sequences here; a literal `"` terminates. This matches
            // the engine's intent (`fallout.cfg` stores the password
            // as a raw string) and the pre-refactor behavior.
            skipWhitespace(p, end);
            if (p >= end || *p != '"') {
                return false;
            }
            const char* valueStart = ++p;
            while (p < end && *p != '"') {
                ++p;
            }
            if (p >= end) {
                return false;
            }
            outPassword = std::string_view(valueStart, static_cast<size_t>(p - valueStart));
            ++p;
            sawPassword = true;
        } else {
            if (!skipJsonValue(p, end)) {
                return false;
            }
        }

        skipWhitespace(p, end);
        if (p >= end) {
            return false;
        }
        if (*p == ',') {
            ++p;
            continue;
        }
        if (*p == '}') {
            ++p;
            break;
        }
        return false;
    }

    skipWhitespace(p, end);
    if (p != end) {
        return false;
    }

    return sawType && sawPassword;
}

bool companionExtractCommandRequest(const char* line,
    size_t length,
    CompanionCommandRequest& outRequest)
{
    if (line == nullptr || length == 0) {
        return false;
    }

    const char* p = line;
    const char* end = line + length;
    skipWhitespace(p, end);
    if (p >= end || *p != '{') {
        return false;
    }
    ++p;

    bool sawType = false;
    bool sawId = false;
    bool sawName = false;

    while (true) {
        skipWhitespace(p, end);
        if (p >= end) {
            return false;
        }

        if (*p == '}') {
            ++p;
            break;
        }

        std::string_view key;
        if (!parseJsonStringView(p, end, key)) {
            return false;
        }

        skipWhitespace(p, end);
        if (p >= end || *p != ':') {
            return false;
        }
        ++p;

        if (key == "type") {
            std::string_view type;
            if (!parseJsonStringView(p, end, type) || type != "cmd") {
                return false;
            }
            sawType = true;
        } else if (key == "id") {
            if (!parseJsonInt32(p, end, outRequest.id)) {
                return false;
            }
            sawId = true;
        } else if (key == "name") {
            if (!parseJsonStringView(p, end, outRequest.name)) {
                return false;
            }
            sawName = true;
        } else if (key == "args") {
            const char* valueStart = p;
            skipWhitespace(valueStart, end);
            if (valueStart >= end || *valueStart != '{') {
                return false;
            }
            p = valueStart;
            if (!skipJsonValue(p, end)) {
                return false;
            }
        } else {
            if (!skipJsonValue(p, end)) {
                return false;
            }
        }

        skipWhitespace(p, end);
        if (p >= end) {
            return false;
        }
        if (*p == ',') {
            ++p;
            continue;
        }
        if (*p == '}') {
            ++p;
            break;
        }
        return false;
    }

    skipWhitespace(p, end);
    if (p != end) {
        return false;
    }

    return sawType && sawId && sawName;
}

} // namespace fallout
