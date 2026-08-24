#include "companion_json_util.h"

#include <stdio.h>

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

void companionAppendEscapedJsonString(std::string& out, const char* s)
{
    if (s == nullptr) {
        return;
    }

    for (const char* p = s; *p != '\0'; ++p) {
        unsigned char c = static_cast<unsigned char>(*p);
        switch (c) {
        case '"':
            out += "\\\"";
            break;
        case '\\':
            out += "\\\\";
            break;
        case '\b':
            out += "\\b";
            break;
        case '\f':
            out += "\\f";
            break;
        case '\n':
            out += "\\n";
            break;
        case '\r':
            out += "\\r";
            break;
        case '\t':
            out += "\\t";
            break;
        default:
            if (c < 0x20) {
                char escape[7];
                snprintf(escape, sizeof(escape), "\\u%04x", c);
                out += escape;
            } else {
                out += static_cast<char>(c);
            }
            break;
        }
    }
}

} // namespace fallout
