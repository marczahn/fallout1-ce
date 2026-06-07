// Wire format: one JSON object per line (newline-delimited JSON, UTF-8).
// All field names use camelCase; type identifiers are lowercase.
//
// Client -> server:
//   {"type":"auth","password":"<string>"}   handshake; must be the first message
//   {"type":"hello"}              post-auth handshake; second message
//   {"type":"get_snapshot"}       request a full snapshot
//
// Server -> client:
//   {"type":"world","schemaVersion":2,"game":"fallout1-ce","playerAvailable":bool}
//   {"type":"snapshot","seq":N,"playerAvailable":bool,
//      "data":{"player":{"hp":H,"maxHp":M,"surface":"local|world",
//                         <local fields: tile,elevation,map,location,locationId>
//                         <world fields: x,y>}}}
//   {"type":"update","entity":"player","seq":N,"playerAvailable":bool,
//      "data":{<union of changed fields>}}
//   {"type":"player_unavailable","seq":N,"playerAvailable":false}
//
// `world` has no `seq`. `snapshot` has no `entity`. `update` always
// has `entity` and a partial `data` covering only the fields that
// changed since the last send. `player_unavailable` is emitted
// one-shot on the present -> absent transition.
//
// Step 2 adds `auth` as the new first message and bumps `world.schemaVersion`
// from 1 to 2. A step-1 client that does not know `auth` is dropped at the
// auth step (the "unknown first message" path).
//
// Step 3 adds surface-typed position and a localized location string.
// The player is on exactly one of two engine surfaces:
//   - "local": a real in-city / dungeon / vault map. Position is the
//     engine's 1D hex-grid tile number plus elevation and map index.
//     `location` is the localized display name from the engine's
//     `map_get_short_name` (or JSON null when the engine has no name
//     loaded). `locationId` is a stable, locale-independent identifier
//     from a static table, e.g. "VAULT13" / "HUBWATER".
//   - "world": the overland world map (including the in-world-map town
//     picker). Position is the engine's pixel coordinates at the
//     50-pixel-per-area scale (world_xpos, world_ypos).
// The `data.player` object in `snapshot` includes the surface-typed
// position fields. The `data` object in `update` is a field-level diff:
// a surface transition emits `surface` plus the new surface's full
// position fields; otherwise only the position fields that actually
// changed are included. `map`, `location`, and `locationId` are
// co-emitted on a single map transition. A step-1 / step-2 client that
// ignores `surface`, `tile`, `elevation`, `map`, `location`,
// `locationId`, `x`, `y` continues to work.

#include "companion_protocol.h"

#include <stdarg.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>

namespace fallout {

namespace {

constexpr char kHello[] = R"({"type":"hello"})";
constexpr char kGetSnapshot[] = R"({"type":"get_snapshot"})";
constexpr char kAuthPrefix[] = R"({"type":"auth")";
constexpr size_t kHelloLen = sizeof(kHello) - 1;
constexpr size_t kGetSnapshotLen = sizeof(kGetSnapshot) - 1;
constexpr size_t kAuthPrefixLen = sizeof(kAuthPrefix) - 1;

} // namespace

std::string companionBuildWorld(bool playerAvailable)
{
    const char* flag = playerAvailable ? "true" : "false";
    char buffer[96];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"world","schemaVersion":2,"game":"fallout1-ce","playerAvailable":%s})"
        "\n",
        flag);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildSnapshot(unsigned int seq, const CompanionSnapshot& snapshot)
{
    const char* flag = snapshot.hasPlayer ? "true" : "false";
    const CompanionPlayerSnapshot& p = snapshot.player;
    char buffer[320];
    int n;
    if (snapshot.hasPlayer && p.surface == CompanionPlayerSurface::World) {
        n = snprintf(buffer,
            sizeof(buffer),
            R"({"type":"snapshot","seq":%u,"playerAvailable":%s,"data":{"player":{"hp":%d,"maxHp":%d,"surface":"world","x":%d,"y":%d}}})"
            "\n",
            seq,
            flag,
            p.hp,
            p.maxHp,
            p.worldX,
            p.worldY);
    } else if (p.location[0] == '\0') {
        // Local surface, no localized name available. `location` is JSON
        // null. `locationId` is empty (no player loaded) or the stable
        // identifier (player loaded, just no name string).
        n = snprintf(buffer,
            sizeof(buffer),
            R"({"type":"snapshot","seq":%u,"playerAvailable":%s,"data":{"player":{"hp":%d,"maxHp":%d,"surface":"local","tile":%d,"elevation":%d,"map":%d,"location":null,"locationId":"%s"}}})"
            "\n",
            seq,
            flag,
            p.hp,
            p.maxHp,
            p.tile,
            p.elevation,
            p.map,
            p.locationId);
    } else {
        // Local surface with a localized name.
        n = snprintf(buffer,
            sizeof(buffer),
            R"({"type":"snapshot","seq":%u,"playerAvailable":%s,"data":{"player":{"hp":%d,"maxHp":%d,"surface":"local","tile":%d,"elevation":%d,"map":%d,"location":"%s","locationId":"%s"}}})"
            "\n",
            seq,
            flag,
            p.hp,
            p.maxHp,
            p.tile,
            p.elevation,
            p.map,
            p.location,
            p.locationId);
    }
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildPlayerUpdate(unsigned int seq,
    bool playerAvailable,
    const CompanionPlayerSnapshot& current,
    const CompanionPlayerSnapshot& lastSent)
{
    const char* flag = playerAvailable ? "true" : "false";

    // Build the inner `data` object as a flat field-level diff. The buffer
    // is sized for the worst case (surface transition plus HP plus both
    // maxHp plus both world coords, plus a couple of commas).
    char dataBuf[256];
    int dataLen = 0;
    bool first = true;

    auto appendField = [&](const char* fmt, ...) -> bool {
        char tmp[96];
        va_list args;
        va_start(args, fmt);
        int n = vsnprintf(tmp, sizeof(tmp), fmt, args);
        va_end(args);
        if (n < 0) {
            return false;
        }
        if (dataLen + n + 2 >= static_cast<int>(sizeof(dataBuf))) {
            return false;
        }
        if (!first) {
            dataBuf[dataLen++] = ',';
        }
        memcpy(dataBuf + dataLen, tmp, static_cast<size_t>(n));
        dataLen += n;
        first = false;
        return true;
    };

    // HP / maxHp diff. Match the step-1 rule: emit both only when maxHp
    // changed; emit hp alone otherwise.
    if (current.maxHp != lastSent.maxHp) {
        if (!appendField(R"("hp":%d,"maxHp":%d)", current.hp, current.maxHp)) {
            return std::string();
        }
    } else if (current.hp != lastSent.hp) {
        if (!appendField(R"("hp":%d)", current.hp)) {
            return std::string();
        }
    }

    if (current.surface != lastSent.surface) {
        // Surface transition: emit `surface` and the new surface's full
        // position fields. The old surface's fields are no longer
        // meaningful on the wire.
        if (current.surface == CompanionPlayerSurface::World) {
            if (!appendField(R"("surface":"world","x":%d,"y":%d)",
                    current.worldX, current.worldY)) {
                return std::string();
            }
        } else {
            if (!appendField(R"("surface":"local","tile":%d,"elevation":%d,"map":%d)",
                    current.tile, current.elevation, current.map)) {
                return std::string();
            }
        }
    } else if (current.surface == CompanionPlayerSurface::Local) {
        if (current.tile != lastSent.tile) {
            if (!appendField(R"("tile":%d)", current.tile)) {
                return std::string();
            }
        }
        if (current.elevation != lastSent.elevation) {
            if (!appendField(R"("elevation":%d)", current.elevation)) {
                return std::string();
            }
        }
        if (current.map != lastSent.map) {
            // `map` only changes on map transitions. Co-emit `location`
            // and `locationId` because they are derived from the same
            // transition. `location` is JSON null when the engine has no
            // name (e.g. map.msg not loaded); `locationId` is always a
            // quoted string from our static table.
            if (current.location[0] == '\0') {
                if (!appendField(R"("map":%d,"location":null,"locationId":"%s")",
                        current.map, current.locationId)) {
                    return std::string();
                }
            } else {
                if (!appendField(R"("map":%d,"location":"%s","locationId":"%s")",
                        current.map, current.location, current.locationId)) {
                    return std::string();
                }
            }
        }
    } else {
        if (current.worldX != lastSent.worldX) {
            if (!appendField(R"("x":%d)", current.worldX)) {
                return std::string();
            }
        }
        if (current.worldY != lastSent.worldY) {
            if (!appendField(R"("y":%d)", current.worldY)) {
                return std::string();
            }
        }
    }

    if (first) {
        return std::string();
    }

    char buffer[320];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"update","entity":"player","seq":%u,"playerAvailable":%s,"data":{%.*s}})"
        "\n",
        seq,
        flag,
        dataLen,
        dataBuf);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

std::string companionBuildPlayerUnavailable(unsigned int seq)
{
    char buffer[80];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"player_unavailable","seq":%u,"playerAvailable":false})"
        "\n",
        seq);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(buffer)) {
        return std::string();
    }
    return std::string(buffer, static_cast<size_t>(n));
}

CompanionClientMessage companionParseClientMessage(const char* line, size_t length)
{
    if (line == nullptr || length == 0) {
        return CompanionClientMessage::Invalid;
    }

    // Skip leading whitespace; the auth prefix match tolerates any amount
    // of leading whitespace, while hello and get_snapshot are exact-shape
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
    if (length - start >= kAuthPrefixLen
        && memcmp(line + start, kAuthPrefix, kAuthPrefixLen) == 0) {
        return CompanionClientMessage::Auth;
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
    // Hand-rolled extraction for the exact shape:
    //   {"type":"auth","password":"<value>"}
    // with whitespace tolerance around `:` and after `,`. The caller has
    // already identified the line as an `auth` message via the prefix
    // match. We do not handle escape sequences in the password value; the
    // expected password is opaque UTF-8 without `\"` or `\\`.
    if (line == nullptr || length == 0) {
        return false;
    }

    const char* p = line;
    const char* end = line + length;

    // Skip past `{"type":"auth"`.
    static constexpr char kPrefix[] = R"({"type":"auth")";
    constexpr size_t kPrefixLen = sizeof(kPrefix) - 1;
    if (static_cast<size_t>(end - p) < kPrefixLen) {
        return false;
    }
    if (memcmp(p, kPrefix, kPrefixLen) != 0) {
        return false;
    }
    p += kPrefixLen;

    // Allow whitespace, then expect `,`.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    if (p >= end || *p != ',') {
        return false;
    }
    ++p;

    // Allow whitespace, then expect `"password"`.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    static constexpr char kPasswordKey[] = R"("password")";
    constexpr size_t kPasswordKeyLen = sizeof(kPasswordKey) - 1;
    if (static_cast<size_t>(end - p) < kPasswordKeyLen) {
        return false;
    }
    if (memcmp(p, kPasswordKey, kPasswordKeyLen) != 0) {
        return false;
    }
    p += kPasswordKeyLen;

    // Allow whitespace, then expect `:`.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    if (p >= end || *p != ':') {
        return false;
    }
    ++p;

    // Allow whitespace, then expect opening `"`.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    if (p >= end || *p != '"') {
        return false;
    }
    const char* valueStart = ++p;

    // Scan to the closing `"`. The password is opaque; we do not handle
    // `\"` escapes. A literal `"` in the value terminates early, which
    // matches the engine's intent of "the password is what is between
    // the quotes."
    while (p < end && *p != '"') {
        ++p;
    }
    if (p >= end) {
        return false;
    }
    outPassword = std::string_view(valueStart, static_cast<size_t>(p - valueStart));
    ++p;

    // Allow whitespace, then expect `}`.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    if (p >= end || *p != '}') {
        return false;
    }
    ++p;

    // Reject trailing garbage.
    while (p < end && (*p == ' ' || *p == '\t' || *p == '\r' || *p == '\n')) {
        ++p;
    }
    if (p != end) {
        return false;
    }

    return true;
}

} // namespace fallout
