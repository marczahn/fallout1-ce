#ifndef FALLOUT_COMPANION_SERVER_H_
#define FALLOUT_COMPANION_SERVER_H_

namespace fallout {

bool companionServerInit();
void companionServerExit();
void companionServerTick(unsigned int now);

// True when the server is listening for connections. False when it is
// disabled by configuration (no `companion_bind` or no `companion_password`
// in `fallout.cfg`, or `fallout.cfg` missing or unreadable). The result
// is decided at `companionServerInit` and is immutable for the lifetime
// of the process. The main menu uses this to decide whether to draw the
// disabled-state hint.
bool companionServerIsActive();

} // namespace fallout

#endif /* FALLOUT_COMPANION_SERVER_H_ */
