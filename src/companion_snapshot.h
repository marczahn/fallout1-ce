#ifndef FALLOUT_COMPANION_SNAPSHOT_H_
#define FALLOUT_COMPANION_SNAPSHOT_H_

namespace fallout {

struct CompanionPlayerSnapshot {
    int hp;
    int maxHp;
};

struct CompanionSnapshot {
    bool hasPlayer;
    CompanionPlayerSnapshot player;
};

CompanionSnapshot companionCollectSnapshot();

} // namespace fallout

#endif /* FALLOUT_COMPANION_SNAPSHOT_H_ */
