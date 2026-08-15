#include "companion_snapshot.h"

#include <string.h>

#include "companion_item_catalog.h"
#include "companion_json_util.h"
#include "companion_player_state.h"
#include "game/critter.h"
#include "game/inventry.h"
#include "game/item.h"
#include "game/combat_defs.h"
#include "game/map.h"
#include "game/object.h"
#include "game/object_types.h"
#include "game/proto_types.h"
#include "game/stat.h"
#include "game/stat_defs.h"
#include "game/worldmap.h"

namespace fallout {

namespace {

// Stable, locale-independent identifiers for each engine map. Indexed by
// the engine's `Map` enum (declared in `game/worldmap.h`). Clients use
// these for logic; the localized `location` string is for display. The
// strings mirror the `Map` enum names with the `MAP_` prefix stripped, so
// they are recognizable to anyone who has read the engine headers.
const char* const kMapLocationIds[MAP_COUNT] = {
    /* DESERT1   */ "DESERT1",
    /* DESERT2   */ "DESERT2",
    /* DESERT3   */ "DESERT3",
    /* HALLDED   */ "HALLDED",
    /* HOTEL     */ "HOTEL",
    /* WATRSHD   */ "WATRSHD",
    /* VAULT13   */ "VAULT13",
    /* VAULTENT  */ "VAULTENT",
    /* VAULTBUR  */ "VAULTBUR",
    /* VAULTNEC  */ "VAULTNEC",
    /* JUNKENT   */ "JUNKENT",
    /* JUNKCSNO  */ "JUNKCSNO",
    /* JUNKKILL  */ "JUNKKILL",
    /* BROHDENT  */ "BROHDENT",
    /* BROHD12   */ "BROHD12",
    /* BROHD34   */ "BROHD34",
    /* CAVES     */ "CAVES",
    /* CHILDRN1  */ "CHILDRN1",
    /* CHILDRN2  */ "CHILDRN2",
    /* CITY1     */ "CITY1",
    /* COAST1    */ "COAST1",
    /* COAST2    */ "COAST2",
    /* COLATRUK  */ "COLATRUK",
    /* FSAUSER   */ "FSAUSER",
    /* RAIDERS   */ "RAIDERS",
    /* SHADYE    */ "SHADYE",
    /* SHADYW    */ "SHADYW",
    /* GLOWENT   */ "GLOWENT",
    /* LAADYTUM  */ "LAADYTUM",
    /* LAFOLLWR  */ "LAFOLLWR",
    /* MBENT     */ "MBENT",
    /* MBSTRG12  */ "MBSTRG12",
    /* MBVATS12  */ "MBVATS12",
    /* MSTRLR12  */ "MSTRLR12",
    /* MSTRLR34  */ "MSTRLR34",
    /* V13ENT    */ "V13ENT",
    /* HUBENT    */ "HUBENT",
    /* DETHCLAW  */ "DETHCLAW",
    /* HUBDWNTN  */ "HUBDWNTN",
    /* HUBHEIGT  */ "HUBHEIGT",
    /* HUBOLDTN  */ "HUBOLDTN",
    /* HUBWATER  */ "HUBWATER",
    /* GLOW1     */ "GLOW1",
    /* GLOW2     */ "GLOW2",
    /* LABLADES  */ "LABLADES",
    /* LARIPPER  */ "LARIPPER",
    /* LAGUNRUN  */ "LAGUNRUN",
    /* CHILDEAD  */ "CHILDEAD",
    /* MBDEAD    */ "MBDEAD",
    /* MOUNTN1   */ "MOUNTN1",
    /* MOUNTN2   */ "MOUNTN2",
    /* FOOT      */ "FOOT",
    /* TARDIS    */ "TARDIS",
    /* TALKCOW   */ "TALKCOW",
    /* USEDCAR   */ "USEDCAR",
    /* BRODEAD   */ "BRODEAD",
    /* DESCRVN1  */ "DESCRVN1",
    /* DESCRVN2  */ "DESCRVN2",
    /* MNTCRVN1  */ "MNTCRVN1",
    /* MNTCRVN2  */ "MNTCRVN2",
    /* VIPERS    */ "VIPERS",
    /* DESCRVN3  */ "DESCRVN3",
    /* MNTCRVN3  */ "MNTCRVN3",
    /* DESCRVN4  */ "DESCRVN4",
    /* MNTCRVN4  */ "MNTCRVN4",
    /* HUBMIS1   */ "HUBMIS1",
};

CompanionInventorySlot companionInventorySlotForObject(const Object* item)
{
    if ((item->flags & OBJECT_WORN) != 0) {
        return CompanionInventorySlot::Worn;
    }

    if ((item->flags & OBJECT_IN_RIGHT_HAND) != 0) {
        return CompanionInventorySlot::RightHand;
    }

    if ((item->flags & OBJECT_IN_LEFT_HAND) != 0) {
        return CompanionInventorySlot::LeftHand;
    }

    return CompanionInventorySlot::None;
}

// Every per-type field starts absent; each branch below fills only what its
// type supplies. `= {}` on the struct is not enough -- it zeroes, and zero is
// a legitimate value for an empty gun's load and for a 0-AC armor.
void clearItemDetail(CompanionInventoryItem& snapshotItem)
{
    snapshotItem.dmgMin = kCompanionItemFieldAbsent;
    snapshotItem.dmgMax = kCompanionItemFieldAbsent;
    snapshotItem.minSt = kCompanionItemFieldAbsent;
    snapshotItem.range = kCompanionItemFieldAbsent;
    snapshotItem.ammoCurrent = kCompanionItemFieldAbsent;
    snapshotItem.ammoMax = kCompanionItemFieldAbsent;
    snapshotItem.ammoName[0] = '\0';
    snapshotItem.caliber = kCompanionItemFieldAbsent;
    snapshotItem.totalRounds = kCompanionItemFieldAbsent;
    snapshotItem.armorClass = kCompanionItemFieldAbsent;
    snapshotItem.chargesCurrent = kCompanionItemFieldAbsent;
    snapshotItem.chargesMax = kCompanionItemFieldAbsent;
    snapshotItem.capsAmount = kCompanionItemFieldAbsent;
}

// Per-type detail, read entirely through the read-only `Object*` accessors in
// `game/item.h`. Mirrors what the in-game inventory shows for the same item,
// so the two can be checked side by side.
void collectItemDetail(Object* item, int count, CompanionInventoryItem& snapshotItem)
{
    snapshotItem.weight = item_weight(item);
    snapshotItem.value = item_cost(item);

    // Caps are special-cased engine-wide and carry their amount in
    // `ammo.quantity` rather than the stack count, so they must not fall
    // through either the charges path or the plain-count path.
    if (item->pid == PROTO_ID_MONEY) {
        snapshotItem.capsAmount = item_caps_get_amount(item);
        return;
    }

    switch (item_get_type(item)) {
    case ITEM_TYPE_WEAPON: {
        int damageMin = 0;
        int damageMax = 0;
        item_w_damage_min_max(item, &damageMin, &damageMax);

        // The game's own readout adds the critter's melee damage for melee and
        // unarmed attack types, so the companion reports the number the player
        // sees rather than the raw proto range. `item_w_subtype` takes the
        // item, so this is correct for a stowed weapon too.
        int attackType = item_w_subtype(item, HIT_MODE_RIGHT_WEAPON_PRIMARY);
        int meleeDamage = attackType == ATTACK_TYPE_MELEE || attackType == ATTACK_TYPE_UNARMED
            ? stat_level(obj_dude, STAT_MELEE_DAMAGE)
            : 0;

        snapshotItem.dmgMin = damageMin;
        snapshotItem.dmgMax = damageMax + meleeDamage;
        snapshotItem.minSt = item_w_min_st(item);

        // `item_w_range` would answer for whatever is in the dude's hand, not
        // for this item -- it resolves the weapon itself through
        // `item_hit_with`. `item_w_range_of` takes the weapon explicitly.
        snapshotItem.range = item_w_range_of(obj_dude, item, HIT_MODE_RIGHT_WEAPON_PRIMARY);

        int maxAmmo = item_w_max_ammo(item);
        if (maxAmmo > 0) {
            snapshotItem.ammoCurrent = item_w_curr_ammo(item);
            snapshotItem.ammoMax = maxAmmo;

            // The engine names the ammo only when the weapon declares a type;
            // an unresolvable type leaves the name empty rather than showing a
            // generated `PID_<n>`.
            int ammoPid = item_w_ammo_pid(item);
            if (ammoPid > 0) {
                CompanionItemMetadata ammoMetadata = {};
                if (companionLookupItemMetadata(ammoPid, ammoMetadata)) {
                    strncpy(snapshotItem.ammoName, ammoMetadata.name, sizeof(snapshotItem.ammoName) - 1);
                }
            }
        }
        break;
    }
    case ITEM_TYPE_AMMO:
        snapshotItem.caliber = item_w_caliber(item);

        // `item_identical` deliberately merges boxes holding different numbers
        // of rounds, so the representative object reports only its own load.
        // This is the engine's own display formula: assume every other box in
        // the stack is full.
        snapshotItem.totalRounds = item_w_max_ammo(item) * (count - 1) + item_w_curr_ammo(item);
        break;
    case ITEM_TYPE_ARMOR:
        snapshotItem.armorClass = item_ar_ac(item);
        break;
    case ITEM_TYPE_MISC:
        if (item_m_uses_charges(item)) {
            snapshotItem.chargesCurrent = item_m_curr_charges(item);
            snapshotItem.chargesMax = item_m_max_charges(item);
        }
        break;
    default:
        break;
    }
}

// Single construction path for a payload item, so the items collected from
// the inventory list and the equipped items appended after it cannot drift
// apart in their metadata lookup or their string bounds.
CompanionInventoryItem makeInventoryItem(Object* item, int count, CompanionInventorySlot slot)
{
    CompanionItemMetadata metadata = {};
    companionLookupItemMetadata(item->pid, metadata);

    CompanionInventoryItem snapshotItem = {};
    snapshotItem.pid = item->pid;
    snapshotItem.type = metadata.type;
    snapshotItem.count = count;
    snapshotItem.slot = slot;
    strncpy(snapshotItem.protoId, metadata.protoId, sizeof(snapshotItem.protoId) - 1);
    strncpy(snapshotItem.name, metadata.name, sizeof(snapshotItem.name) - 1);

    clearItemDetail(snapshotItem);
    collectItemDetail(item, count, snapshotItem);

    return snapshotItem;
}

bool containsObject(const std::vector<Object*>& objects, const Object* item)
{
    for (Object* candidate : objects) {
        if (candidate == item) {
            return true;
        }
    }

    return false;
}

void collectInventorySnapshot(CompanionInventorySnapshot& inventory)
{
    inventory.items.clear();

    Inventory* source = &(obj_dude->data.inventory);
    inventory.items.reserve(source->length);

    // Object identities already emitted. The equipped items appended below are
    // reachable through the UI's slot pointers *and* present in the list
    // whenever the inventory screen is closed, so they are deduped by identity
    // -- not by pid, which would wrongly collapse an equipped and a stashed
    // copy of the same weapon.
    std::vector<Object*> collected;
    collected.reserve(source->length);

    for (int index = 0; index < source->length; ++index) {
        InventoryItem* sourceItem = &(source->items[index]);
        Object* item = sourceItem->item;

        inventory.items.push_back(makeInventoryItem(item, sourceItem->quantity, companionInventorySlotForObject(item)));
        collected.push_back(item);
    }

    // While the in-game inventory screen is open the engine lifts the equipped
    // items out of `data.inventory` and holds them in the UI's slot pointers,
    // so the loop above cannot see them at all. Append them here, taking the
    // slot from *which pointer the object arrived in* rather than from its
    // flags: the screen's drag/drop flow does not set `OBJECT_IN_*_HAND` /
    // `OBJECT_WORN` until `exit_inventory` runs, so classifying an item the
    // player just dragged into a slot by flag would report `None` for it.
    Object* heldOwner = nullptr;
    Object* heldRightHand = nullptr;
    Object* heldLeftHand = nullptr;
    Object* heldWorn = nullptr;
    inven_ui_held_slots(&heldOwner, &heldRightHand, &heldLeftHand, &heldWorn);

    // Owner guard. Loot, barter and container sessions lift the player's own
    // equipped items the same way, and those belong on the wire; a steal
    // session's *target* items must never be attributed to the player.
    if (heldOwner != obj_dude) {
        return;
    }

    // A two-handed weapon aliases both hand pointers (`setup_inventory`), and
    // must be listed once. Right hand wins, matching the precedence
    // `companionInventorySlotForObject` already uses.
    if (heldLeftHand == heldRightHand) {
        heldLeftHand = nullptr;
    }

    const struct {
        Object* item;
        CompanionInventorySlot slot;
    } heldSlots[] = {
        { heldRightHand, CompanionInventorySlot::RightHand },
        { heldLeftHand, CompanionInventorySlot::LeftHand },
        { heldWorn, CompanionInventorySlot::Worn },
    };

    for (const auto& heldSlot : heldSlots) {
        if (heldSlot.item == nullptr || containsObject(collected, heldSlot.item)) {
            continue;
        }

        // Equipped items never stack, and every removal path removes exactly
        // one, so the count is 1.
        inventory.items.push_back(makeInventoryItem(heldSlot.item, 1, heldSlot.slot));
        collected.push_back(heldSlot.item);
    }
}

} // namespace

CompanionSnapshot companionCollectSnapshot()
{
    CompanionSnapshot snapshot;
    snapshot.hasPlayer = false;
    snapshot.surface = CompanionPlayerSurface::Local;
    snapshot.vitals = CompanionPlayerVitals{ 0, 0 };
    snapshot.status = CompanionPlayerStatus{ 0, 0, 0, 0, 0, 0, 0, 0, 0 };
    snapshot.special = CompanionPlayerSpecial{ 0, 0, 0, 0, 0, 0, 0 };
    snapshot.progression = CompanionPlayerProgression{ 0, 0, 0 };
    snapshot.localLocation = CompanionPlayerLocalLocation{};
    snapshot.localLocation.location[0] = '\0';
    snapshot.localLocation.mapName[0] = '\0';
    snapshot.localLocation.locationId[0] = '\0';
    snapshot.worldLocation = CompanionPlayerWorldLocation{ 0, 0 };
    snapshot.inventory.items.clear();

    if (!companionIsPlayerReallyPlaying()) {
        return snapshot;
    }

    snapshot.hasPlayer = true;
    snapshot.vitals.hp = critter_get_hits(obj_dude);
    snapshot.vitals.maxHp = stat_level(obj_dude, STAT_MAXIMUM_HIT_POINTS);
    snapshot.status.armorClass = stat_level(obj_dude, STAT_ARMOR_CLASS);
    snapshot.status.currentCarryWeight = item_total_weight(obj_dude);
    snapshot.status.carryWeight = stat_level(obj_dude, STAT_CARRY_WEIGHT);
    snapshot.status.meleeDamage = stat_level(obj_dude, STAT_MELEE_DAMAGE);
    snapshot.status.damageResistance = stat_level(obj_dude, STAT_DAMAGE_RESISTANCE);
    snapshot.status.poisonResistance = stat_level(obj_dude, STAT_POISON_RESISTANCE);
    snapshot.status.radiationResistance = stat_level(obj_dude, STAT_RADIATION_RESISTANCE);
    snapshot.status.healingRate = stat_level(obj_dude, STAT_HEALING_RATE);
    snapshot.status.radiation = critter_get_rads(obj_dude);
    snapshot.status.poison = critter_get_poison(obj_dude);
    snapshot.special.strength = stat_level(obj_dude, STAT_STRENGTH);
    snapshot.special.perception = stat_level(obj_dude, STAT_PERCEPTION);
    snapshot.special.endurance = stat_level(obj_dude, STAT_ENDURANCE);
    snapshot.special.charisma = stat_level(obj_dude, STAT_CHARISMA);
    snapshot.special.intelligence = stat_level(obj_dude, STAT_INTELLIGENCE);
    snapshot.special.agility = stat_level(obj_dude, STAT_AGILITY);
    snapshot.special.luck = stat_level(obj_dude, STAT_LUCK);
    snapshot.progression.level = stat_pc_get(PC_STAT_LEVEL);
    snapshot.progression.experience = stat_pc_get(PC_STAT_EXPERIENCE);
    snapshot.progression.nextLevelExp = stat_pc_min_exp();
    collectInventorySnapshot(snapshot.inventory);

    if (worldMapIsActive()) {
        snapshot.surface = CompanionPlayerSurface::World;
        int x;
        int y;
        if (worldMapGetPlayerPosition(&x, &y)) {
            snapshot.worldLocation.x = x;
            snapshot.worldLocation.y = y;
        }
    } else {
        snapshot.surface = CompanionPlayerSurface::Local;
        snapshot.localLocation.tile = obj_dude->tile;
        snapshot.localLocation.elevation = obj_dude->elevation;
        snapshot.localLocation.map = map_get_index_number();

        int m = snapshot.localLocation.map;
        if (m >= 0 && m < MAP_COUNT) {
            // Localized display names. The engine returns `char*`s owned
            // by the message list; copy them into our own buffers so the
            // snapshot outlives any subsequent message-list activity.
            char* shortName = map_get_short_name(m);
            if (companionIsSafeJsonString(shortName)) {
                strncpy(snapshot.localLocation.location, shortName, kCompanionLocationSize - 1);
                snapshot.localLocation.location[kCompanionLocationSize - 1] = '\0';
            }

            char* mapName = map_get_elev_idx(m, snapshot.localLocation.elevation);
            if (mapName != nullptr && companionIsSafeJsonString(mapName)) {
                strncpy(snapshot.localLocation.mapName, mapName, kCompanionLocationSize - 1);
                snapshot.localLocation.mapName[kCompanionLocationSize - 1] = '\0';
            }

            // Stable identifier from our static table. Out-of-range indices
            // (defensive) leave the field empty.
            strncpy(snapshot.localLocation.locationId, kMapLocationIds[m], kCompanionLocationIdSize - 1);
            snapshot.localLocation.locationId[kCompanionLocationIdSize - 1] = '\0';
        }

        // The engine always knows the player's overworld position (the town's
        // location on the world map), even on a local surface. Report it so
        // the companion can show a world-map fix immediately on connect.
        int wx;
        int wy;
        if (worldMapGetPlayerPosition(&wx, &wy)) {
            snapshot.localLocation.worldX = wx;
            snapshot.localLocation.worldY = wy;
        }
    }

    return snapshot;
}

} // namespace fallout
