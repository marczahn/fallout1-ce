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
//   {"type":"snapshot","seq":N,"playerAvailable":bool,"data":{"player":{"hp":H,"maxHp":M}}}
//   {"type":"update","entity":"player","seq":N,"playerAvailable":bool,"data":{"hp":H} | {"hp":H,"maxHp":M}}
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

#include "companion_protocol.h"

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
    char buffer[160];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"snapshot","seq":%u,"playerAvailable":%s,"data":{"player":{"hp":%d,"maxHp":%d}}})"
        "\n",
        seq,
        flag,
        snapshot.player.hp,
        snapshot.player.maxHp);
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
    char buffer[160];
    int n = 0;
    if (current.maxHp != lastSent.maxHp) {
        n = snprintf(buffer,
            sizeof(buffer),
            R"({"type":"update","entity":"player","seq":%u,"playerAvailable":%s,"data":{"hp":%d,"maxHp":%d}})"
            "\n",
            seq,
            flag,
            current.hp,
            current.maxHp);
    } else if (current.hp != lastSent.hp) {
        n = snprintf(buffer,
            sizeof(buffer),
            R"({"type":"update","entity":"player","seq":%u,"playerAvailable":%s,"data":{"hp":%d}})"
            "\n",
            seq,
            flag,
            current.hp);
    } else {
        return std::string();
    }
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
