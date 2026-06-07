#include "companion_json_util.h"

namespace fallout {

bool companionIsSafeJsonString(const char* s)
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

} // namespace fallout
