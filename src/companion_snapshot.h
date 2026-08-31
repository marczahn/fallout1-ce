#ifndef FALLOUT_COMPANION_SNAPSHOT_H_
#define FALLOUT_COMPANION_SNAPSHOT_H_

#include <cstddef>
#include <vector>

#include "companion_item_catalog.h"

namespace fallout {

// Which engine surface the player is currently on. Drives which position
// kinds are meaningful in `CompanionSnapshot` and which appear on the wire
// in `snapshot.payload` / `update.payload`.
//
// `Local` is a real in-city / dungeon / vault map. The engine stores
// position as a 1D hex-grid tile number plus elevation, indexed into the
// global `objectTable[HEX_GRID_SIZE]`. The same tile value can refer to
// different cells on different elevations, so elevation is required to
// fully specify position on multi-elevation maps.
//
// `World` is the overland world map. The engine stores position as pixel
// coordinates (`world_xpos`, `world_ypos`) at a 50-pixel-per-area scale.
// The in-world-map town picker is treated as `World` (per T2's
// `worldMapIsActive()` semantics, `wwin_flag` is true for the whole
// `world_map()` call, picker included).
enum class CompanionPlayerSurface {
    Local,
    World,
};

// Backing storage for `location`. Sized to fit the longest localized
// short name the engine's automap displays (e.g. "Brotherhood of Steel
// Entrance"). 64 bytes is a defensive ceiling; actual strings are
// shorter.
static constexpr size_t kCompanionLocationSize = 64;

// Backing storage for `locationId`. Sized to fit the longest stable
// identifier (e.g. "HUBWATER"). 32 bytes is a defensive ceiling; actual
// strings are 8 chars or fewer.
static constexpr size_t kCompanionLocationIdSize = 32;

// `player.vitals` payload. HP and max HP. Always meaningful when the
// player is loaded (real or world map). Wire keys: `hp`, `maxHp`.
struct CompanionPlayerVitals {
    int hp;
    int maxHp;
};

// `player.status` payload. Derived defensive and survivability values
// sampled directly from engine state. Wire keys: `armorClass`,
// `currentCarryWeight`, `carryWeight`, `meleeDamage`,
// `damageResistance`, `poisonResistance`, `radiationResistance`,
// `healingRate`, `radiation`, `poison`.
struct CompanionPlayerStatus {
    int armorClass;
    int currentCarryWeight;
    int carryWeight;
    int meleeDamage;
    int damageResistance;
    int poisonResistance;
    int radiationResistance;
    int healingRate;
    int radiation;
    int poison;
};

// `player.special` payload. Current SPECIAL attribute levels. Wire
// keys: `strength`, `perception`, `endurance`, `charisma`,
// `intelligence`, `agility`, `luck`.
struct CompanionPlayerSpecial {
    int strength;
    int perception;
    int endurance;
    int charisma;
    int intelligence;
    int agility;
    int luck;
};

// `player.progression` payload. Current player progression values.
// `nextLevelExp` is the engine's total XP threshold for the next level,
// not the remaining delta. Wire keys: `level`, `experience`,
// `nextLevelExp`.
struct CompanionPlayerProgression {
    int level;
    int experience;
    int nextLevelExp;
};

// `player.localLocation` payload. Meaningful when
// `surface == CompanionPlayerSurface::Local`. Wire keys: `tile`,
// `elevation`, `map`, `location`, `mapName`, `locationId`, `worldX`,
// `worldY`. `location` is the engine's localized short name; `mapName`
// is the elevation-specific automap label shown beneath it; `locationId`
// is a stable identifier from the `kMapLocationIds` table in
// `companion_snapshot.cc`. `worldX`/`worldY` are the player's overworld
// position (same scale as `worldLocation`); the engine always knows it,
// so it is reported even on a local surface so the companion can show a
// world-map fix immediately.
struct CompanionPlayerLocalLocation {
    int tile;
    int elevation;
    int map;
    char location[kCompanionLocationSize];
    char mapName[kCompanionLocationSize];
    char locationId[kCompanionLocationIdSize];
    int worldX;
    int worldY;
};

// `player.worldLocation` payload. Meaningful when
// `surface == CompanionPlayerSurface::World`. Wire keys: `x`, `y` (the
// engine's 50-pixel-per-area world coordinates).
struct CompanionPlayerWorldLocation {
    int x;
    int y;
};

enum class CompanionInventorySlot {
    None,
    Worn,
    RightHand,
    LeftHand,
};

// Backing storage for a weapon's ammo name. Sized like the item name it is
// copied from, since it *is* an item name resolved through the same catalog.
static constexpr size_t kCompanionItemAmmoNameSize = kCompanionItemNameSize;

// Sentinel for "this field does not apply to this item" (TASK-019). Zero
// cannot serve: an empty gun really does have 0 loaded rounds, and 0 armor
// class is a legitimate value. The protocol writer emits only the fields that
// are not this value.
constexpr int kCompanionItemFieldAbsent = -1;

struct CompanionInventoryItem {
    // Live engine identity used by companion commands. This is intentionally
    // separate from pid: several non-stackable items can share a prototype.
    int objectId;
    int pid;
    bool twoHanded;
    int type;
    int count;
    CompanionInventorySlot slot;
    char protoId[kCompanionItemProtoIdSize];
    char name[kCompanionItemNameSize];

    // Common block (TASK-019). Always meaningful.
    int weight;
    int value;

    // Per-type detail (TASK-019). Every field is `kCompanionItemFieldAbsent`
    // unless the item's type supplies it; `ammoName` is empty unless the
    // weapon has an ammo type the catalog could resolve.
    int dmgMin;
    int dmgMax;
    int minSt;
    int range;
    int ammoCurrent;
    int ammoMax;
    char ammoName[kCompanionItemAmmoNameSize];
    int caliber;
    int totalRounds;
    int armorClass;
    int chargesCurrent;
    int chargesMax;
    int capsAmount;
};

struct CompanionInventorySnapshot {
    std::vector<CompanionInventoryItem> items;
};

// Backing storage for a quest line. The engine word-wraps quest text at
// 350px (`pipboy.cc:1253`) and imposes no length cap of its own, so this
// is a defensive ceiling rather than a mirrored engine constant. The
// client wraps rather than truncates, so an unexpectedly long line
// degrades into an extra row instead of losing text.
static constexpr size_t kCompanionQuestTextSize = 256;

// One row of the in-game Pip-Boy quest screen. Identity is
// `(locationIndex, slot)` - both compile-time-stable coordinates in the
// engine's fixed 12x9 `sthreads` table, which is all a client-side row key
// needs. The backing `GVAR_*` index is deliberately not carried: it is an
// engine internal with no meaning to the companion.
struct CompanionQuest {
    int locationIndex; // 0..companionQuestLocationCount()-1
    int slot; // 0..companionQuestSlotCount()-1

    // `PipStatus`'s own rule: the quest's global var is > 1
    // (`pipboy.cc:1266-1272`, where such a quest prints with
    // `PIPBOY_TEXT_STYLE_STRIKE_THROUGH`).
    bool completed;

    // True for the quest backed by `GVAR_FIND_WATER_CHIP`. A semantic
    // flag, not a GVAR leak: it tells the client which row the Vault 13
    // water countdown belongs to without the client having to know
    // anything about the engine's quest table.
    bool waterChip;

    // The engine's own Pip-Boy location name, message id
    // `700 + 10 * locationIndex` - the same string the in-game quest
    // screen prints, not the automap short name `localLocation` reports.
    char location[kCompanionLocationSize];

    // Message id `701 + 10 * locationIndex + slot`, verbatim. Empty when
    // the quest catalog could not resolve it; the client renders that as a
    // visible failure rather than dropping the row, so the list can never
    // silently disagree with the in-game screen.
    char text[kCompanionQuestTextSize];
};

// `player.quests` payload. `quests` is the complete visible set in engine
// order (location index ascending, then slot) - a full replacement on
// every change, like `player.inventory`.
//
// The water fields mirror the Vault 13 countdown the engine runs in
// `gtime_q_process` (`scripts.cc:306-339`), which decrements
// `GVAR_VAULT_WATER` by one per in-game midnight while
// `GVAR_FIND_WATER_CHIP != 2`.
//
// `waterCountdownActive` uses that `!= 2` guard, while `CompanionQuest`'s
// `completed` uses `PipStatus`'s `> 1`. The two engine rules disagree
// above value 2, and both are reported as-is rather than merged: a modded
// or unexpected value then produces two honest signals instead of one
// invented one. Do not "simplify" them into a single flag.
struct CompanionQuestSnapshot {
    std::vector<CompanionQuest> quests;
    int waterDaysRemaining;
    bool waterCountdownActive;
};

// Title of one holodisk the player has found. Defensive ceiling, like
// `kCompanionQuestTextSize`; the client wraps rather than truncates.
static constexpr size_t kCompanionHolodiskTitleSize = 128;

// One row of the in-game Pip-Boy STATUS screen's holodisk column - NOT
// the ARCHIVES screen, which lists movies (see `CompanionTransmission`
// below). Identity is `index`:
// the position in the engine's fixed 18-entry `holodisks` table, which is
// compile-time-stable and is all a client-side row key needs. As with
// `CompanionQuest`, the backing `GVAR_*` index is deliberately not
// carried - it is an engine internal with no meaning to the companion.
//
// Body text is deliberately absent *for now*. The engine has it (message
// ids `1000 * index + 1000`, terminated by `**END-DISK**`); TASK-025 adds
// it when holodisks become a readable screen. It is not carried yet
// because nothing renders it.
struct CompanionHolodisk {
    int index; // 0..companionHolodiskCount()-1

    // Message id `400 + index`, verbatim. Empty when the catalog could
    // not resolve it; the client renders that as a visible failure rather
    // than dropping the row - the same rule `CompanionQuest::text` follows.
    char title[kCompanionHolodiskTitleSize];
};

// `player.holodisks` payload: the complete set of *found* holodisks in
// engine table order - a full replacement on every change, like
// `player.quests`.
//
// Found-ness is `game_global_vars[holodisks[i]] != 0`, which is
// `PipStatus`'s own rule (`pipboy.cc:980-983`, where it computes
// `holocount`). Note this is `!= 0`, not the `> 0` quest visibility uses:
// the two screens genuinely differ upstream and are not merged here.
//
// Holodisks have no audio at all - they are documents. Recordings belong
// to `CompanionTransmission` below.
struct CompanionHolodiskSnapshot {
    std::vector<CompanionHolodisk> holodisks;
};

// Title of one transmission (a replayable cutscene). Same ceiling and
// same "empty means the catalog failed" rule as the holodisk title.
static constexpr size_t kCompanionTransmissionTitleSize = 128;

// One row of the in-game Pip-Boy ARCHIVES screen. Identity is `index`:
// the `GameMovie` enum value, which is compile-time stable.
//
// This is a DIFFERENT screen from the holodisks above, which the vault
// conflated for a while. `PipArchives` (`pipboy.cc:1730`) lists movies;
// `PipStatus` (`:960`) lists holodisks beside the quests.
//
// Two entries legitimately share a title -- `MOVIE_WALKM` and
// `MOVIE_WALKW` are both "Leaving Vault" -- so `index` is the only safe
// identity and the title must never be used as a key.
struct CompanionTransmission {
    int index; // a `GameMovie` value, `MOVIE_VEXPLD`..`MOVIE_COUNT-1`

    // Message id `500 + index`, verbatim; empty when unresolvable.
    char title[kCompanionTransmissionTitleSize];
};

// `player.transmissions` payload: the cutscenes the player has actually
// seen, in enum order -- a full replacement on every change.
//
// Seen-ness is `gmovie_has_been_played(movie)`, which the engine persists
// across saves (`gmovie_load`/`gmovie_save`).
//
// **Only 11 of the 14 movies are listable.** `ListArchive` starts at
// `MOVIE_VEXPLD`, deliberately skipping `MOVIE_IPLOGO`, `MOVIE_MPLOGO`,
// and `MOVIE_INTRO` -- the logos and the intro are not archive material.
// The companion applies the same rule, or it would offer the Interplay
// logo as a transmission.
struct CompanionTransmissionSnapshot {
    std::vector<CompanionTransmission> transmissions;
};

// Aggregator over the three per-kind player payloads. The `surface`
// field drives which of `localLocation` and `worldLocation` are
// meaningful at any given sample; `vitals` is always meaningful when
// `hasPlayer` is true. The protocol emits only the valid kinds on the
// wire.
struct CompanionSnapshot {
    bool hasPlayer;
    CompanionPlayerSurface surface;
    CompanionPlayerVitals vitals;
    CompanionPlayerStatus status;
    CompanionPlayerSpecial special;
    CompanionPlayerProgression progression;
    CompanionPlayerLocalLocation localLocation;
    CompanionPlayerWorldLocation worldLocation;
    CompanionInventorySnapshot inventory;
    CompanionQuestSnapshot quests;
    CompanionHolodiskSnapshot holodisks;
    CompanionTransmissionSnapshot transmissions;
};

CompanionSnapshot companionCollectSnapshot();

} // namespace fallout

#endif /* FALLOUT_COMPANION_SNAPSHOT_H_ */
