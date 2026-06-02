#ifndef FALLOUT_COMPANION_SERVER_H_
#define FALLOUT_COMPANION_SERVER_H_

namespace fallout {

bool companionServerInit();
void companionServerExit();
void companionServerTick(unsigned int now);

} // namespace fallout

#endif /* FALLOUT_COMPANION_SERVER_H_ */
