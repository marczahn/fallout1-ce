#include "companion_json_util.h"

#include <stdio.h>

namespace fallout {

namespace {

// cp1252 -> Unicode for the `0x80`-`0x9F` range, which is the only place
// cp1252 and Latin-1 disagree; `0xA0`-`0xFF` are identical in both and
// need no table. Standard Windows-1252 mapping, reproduced as-is.
//
// The five slots cp1252 leaves undefined - `0x81`, `0x8D`, `0x8F`,
// `0x90`, `0x9D` - hold their own byte value. That is deliberate: this
// function's job is to make every byte emittable, not to guess what an
// undefined byte meant, and preserving the value is more honest than
// rewriting it to U+FFFD. None of the five occurs in the game data.
//
// The only high byte the English game data actually uses is `0x95`
// (bullet, U+2022), on the holodisk bodies of disks 0, 5, 8 and 12.
constexpr unsigned short kCp1252HighMap[32] = {
    0x20AC, 0x0081, 0x201A, 0x0192, 0x201E, 0x2026, 0x2020, 0x2021,
    0x02C6, 0x2030, 0x0160, 0x2039, 0x0152, 0x008D, 0x017D, 0x008F,
    0x0090, 0x2018, 0x2019, 0x201C, 0x201D, 0x2022, 0x2013, 0x2014,
    0x02DC, 0x2122, 0x0161, 0x203A, 0x0153, 0x009D, 0x017E, 0x0178,
};

void appendUnicodeEscape(std::string& out, unsigned int codePoint)
{
    char escape[7];
    snprintf(escape, sizeof(escape), "\\u%04x", codePoint);
    out += escape;
}

} // namespace

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
                appendUnicodeEscape(out, c);
            } else if (c < 0x80) {
                out += static_cast<char>(c);
            } else if (c < 0xA0) {
                appendUnicodeEscape(out, kCp1252HighMap[c - 0x80]);
            } else {
                // cp1252 agrees with Latin-1 here, so the byte value is
                // the code point.
                appendUnicodeEscape(out, c);
            }
            break;
        }
    }
}

} // namespace fallout
