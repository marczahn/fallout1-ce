#include "companion_item_catalog.h"

#include <stdio.h>
#include <string.h>

#include <unordered_map>

#include "game/proto.h"

namespace fallout {

namespace {

std::unordered_map<int, CompanionItemMetadata> gItemCatalog;

bool isSafeJsonString(const char* s)
{
    if (s == nullptr) {
        return false;
    }

    for (const char* p = s; *p != '\0'; ++p) {
        unsigned char c = static_cast<unsigned char>(*p);
        if (c == '"' || c == '\\' || c < 0x20) {
            return false;
        }
    }

    return true;
}

void copyOrFallback(char* dest, size_t destSize, const char* src, const char* fallbackPrefix, int pid)
{
    if (destSize == 0) {
        return;
    }

    if (isSafeJsonString(src) && src[0] != '\0') {
        strncpy(dest, src, destSize - 1);
        dest[destSize - 1] = '\0';
        return;
    }

    snprintf(dest, destSize, "%s%d", fallbackPrefix, pid);
}

} // namespace

bool companionLookupItemMetadata(int pid, CompanionItemMetadata& outMetadata)
{
    auto it = gItemCatalog.find(pid);
    if (it != gItemCatalog.end()) {
        outMetadata = it->second;
        return true;
    }

    CompanionItemMetadata metadata = {};
    metadata.pid = pid;
    metadata.type = -1;

    Proto* proto = nullptr;
    if (proto_ptr(pid, &proto) == 0) {
        metadata.type = proto->item.type;
    }

    char protoId[kCompanionItemProtoIdSize] = {};
    if (proto_list_str(pid, protoId) == 0) {
        copyOrFallback(metadata.protoId, sizeof(metadata.protoId), protoId, "PID_", pid);
    } else {
        snprintf(metadata.protoId, sizeof(metadata.protoId), "PID_%d", pid);
    }

    copyOrFallback(metadata.name, sizeof(metadata.name), proto_name(pid), "unknown_item_", pid);

    auto inserted = gItemCatalog.emplace(pid, metadata);
    outMetadata = inserted.first->second;
    return true;
}

void companionResetItemCatalog()
{
    gItemCatalog.clear();
}

} // namespace fallout
