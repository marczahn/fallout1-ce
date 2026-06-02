#include "companion_protocol.h"

#include <stddef.h>
#include <stdio.h>
#include <string.h>

namespace fallout {

namespace {

constexpr char kHello[] = R"({"type":"hello"})";
constexpr char kGetSnapshot[] = R"({"type":"get_snapshot"})";
constexpr size_t kHelloLen = sizeof(kHello) - 1;
constexpr size_t kGetSnapshotLen = sizeof(kGetSnapshot) - 1;

} // namespace

std::string companionBuildWorld(bool playerAvailable)
{
    const char* flag = playerAvailable ? "true" : "false";
    char buffer[96];
    int n = snprintf(buffer,
        sizeof(buffer),
        R"({"type":"world","schemaVersion":1,"game":"fallout1-ce","playerAvailable":%s})"
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

} // namespace fallout
