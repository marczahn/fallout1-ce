#ifndef FALLOUT_COMPANION_JSON_UTIL_H_
#define FALLOUT_COMPANION_JSON_UTIL_H_

namespace fallout {

// Returns true if `s` is safe to emit as a JSON string literal (no
// unescaped `"` or `\\`, no control characters, non-null). Used to
// defend against engine strings that might contain characters which
// would break the wire format.
bool companionIsSafeJsonString(const char* s);

} // namespace fallout

#endif /* FALLOUT_COMPANION_JSON_UTIL_H_ */
