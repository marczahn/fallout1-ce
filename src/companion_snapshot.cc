#include "companion_snapshot.h"

#include <string.h>

#include "companion_item_catalog.h"
#include "companion_json_util.h"
#include "companion_player_state.h"
#include "game/critter.h"
#include "game/inventry.h"
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

void collectInventorySnapshot(CompanionInventorySnapshot& inventory)
{
    inventory.items.clear();

    Inventory* source = &(obj_dude->data.inventory);
    inventory.items.reserve(source->length);

    for (int index = 0; index < source->length; ++index) {
        InventoryItem* sourceItem = &(source->items[index]);
        Object* item = sourceItem->item;

        CompanionItemMetadata metadata = {};
        companionLookupItemMetadata(item->pid, metadata);

        CompanionInventoryItem snapshotItem = {};
        snapshotItem.pid = item->pid;
        snapshotItem.type = metadata.type;
        snapshotItem.count = sourceItem->quantity;
        snapshotItem.slot = companionInventorySlotForObject(item);
        strncpy(snapshotItem.protoId, metadata.protoId, sizeof(snapshotItem.protoId) - 1);
        strncpy(snapshotItem.name, metadata.name, sizeof(snapshotItem.name) - 1);

        inventory.items.push_back(snapshotItem);
    }
}

} // namespace

CompanionSnapshot companionCollectSnapshot()
{
    CompanionSnapshot snapshot;
    snapshot.hasPlayer = false;
    snapshot.surface = CompanionPlayerSurface::Local;
    snapshot.vitals = CompanionPlayerVitals{ 0, 0 };
    snapshot.localLocation = CompanionPlayerLocalLocation{};
    snapshot.localLocation.location[0] = '\0';
    snapshot.localLocation.locationId[0] = '\0';
    snapshot.worldLocation = CompanionPlayerWorldLocation{ 0, 0 };
    snapshot.inventory.items.clear();

    if (!companionIsPlayerReallyPlaying()) {
        return snapshot;
    }

    snapshot.hasPlayer = true;
    snapshot.vitals.hp = critter_get_hits(obj_dude);
    snapshot.vitals.maxHp = stat_level(obj_dude, STAT_MAXIMUM_HIT_POINTS);
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

        // Localized display name. The engine returns a `char*` owned by
        // the message list; copy into our own buffer so the snapshot
        // outlives any subsequent message-list activity.
        char* shortName = map_get_short_name(snapshot.localLocation.map);
        if (companionIsSafeJsonString(shortName)) {
            strncpy(snapshot.localLocation.location, shortName, kCompanionLocationSize - 1);
            snapshot.localLocation.location[kCompanionLocationSize - 1] = '\0';
        }

        // Stable identifier from our static table. Out-of-range indices
        // (defensive) leave the field empty.
        int m = snapshot.localLocation.map;
        if (m >= 0 && m < MAP_COUNT) {
            strncpy(snapshot.localLocation.locationId, kMapLocationIds[m], kCompanionLocationIdSize - 1);
            snapshot.localLocation.locationId[kCompanionLocationIdSize - 1] = '\0';
        }
    }

    return snapshot;
}

} // namespace fallout
