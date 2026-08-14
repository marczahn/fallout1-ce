#include "companion_snapshot.h"

#include <string.h>

#include "companion_item_catalog.h"
#include "companion_json_util.h"
#include "companion_player_state.h"
#include "game/critter.h"
#include "game/inventry.h"
#include "game/item.h"
#include "game/map.h"
#include "game/object.h"
#include "game/object_types.h"
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
