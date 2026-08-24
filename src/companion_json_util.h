#ifndef FALLOUT_COMPANION_JSON_UTIL_H_
#define FALLOUT_COMPANION_JSON_UTIL_H_

#include <string>

namespace fallout {

// Returns true if `s` is safe to emit as a JSON string literal (no
// unescaped `"` or `\\`, no control characters, non-null). Used to
// defend against engine strings that might contain characters which
// would break the wire format.
bool companionIsSafeJsonString(const char* s);

// Appends `s` to `out` as an escaped JSON string *body* (no surrounding
// quotes): `"` -> `\"`, `\` -> `\\`, and control characters -> `\uXXXX`.
// A null `s` appends nothing.
//
// Unlike `companionIsSafeJsonString`, which only reports whether a string
// can be emitted as-is, this makes any engine string emittable - needed
// for prose fields such as quest text, where discarding or rewriting the
// string is not an acceptable fallback (the companion must show the same
// quest lines the in-game Pip-Boy shows).
//
// Bytes >= 0x80 are passed through unchanged: the engine's message files
// are already emitted verbatim elsewhere on the wire, so this keeps the
// existing encoding behaviour rather than inventing a transcoding rule
// here.
void companionAppendEscapedJsonString(std::string& out, const char* s);

} // namespace fallout

#endif /* FALLOUT_COMPANION_JSON_UTIL_H_ */
