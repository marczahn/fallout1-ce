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
// The output is **always pure ASCII**, and that is the load-bearing part
// of this function's contract. Bytes >= 0x80 are transcoded from cp1252
// (the encoding the game's `.msg` files are authored in) to `\uXXXX`
// escapes rather than passed through.
//
// This used to pass high bytes through unchanged, which was a silent
// trap. The client frames on newlines and parses with
// `json.loads(line.decode("utf-8"))`, catching `UnicodeDecodeError` and
// dropping the **entire message** (`companion_app/net/framing.py:38-41`).
// One non-UTF-8 byte anywhere in a `snapshot` therefore costs the client
// every kind that snapshot carried - vitals, inventory, quests - with
// nothing logged. It never fired only because everything on the wire was
// ASCII until holodisk body text arrived carrying `0x95` bullets
// (TASK-025). Emitting escapes makes the output valid UTF-8 by
// construction, for every caller, forever.
void companionAppendEscapedJsonString(std::string& out, const char* s);

} // namespace fallout

#endif /* FALLOUT_COMPANION_JSON_UTIL_H_ */
