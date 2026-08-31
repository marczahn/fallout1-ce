#include "companion_server.h"

#include <stddef.h>
#include <string.h>

#if !defined(_WIN32)
#include <errno.h>
#include <fcntl.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

#include <stdio.h>

#include <string>
#include <string_view>
#include <vector>

#include "companion_item_catalog.h"
#include "companion_player_state.h"
#include "companion_protocol.h"
#include "companion_quest_catalog.h"
#include "companion_snapshot.h"
#include "game/automap.h"
#include "game/cache.h"
#include "game/combat.h"
#include "game/gconfig.h"
#include "game/gmovie.h"
#include "game/game.h"
#include "game/intface.h"
#include "game/inventry.h"
#include "game/item.h"
#include "game/map.h"
#include "game/object.h"
#include "game/perk.h"
#include "game/pipboy.h"
#include "game/protinst.h"
#include "game/worldmap.h"
#include "platform_compat.h"
#include "plib/color/color.h"
#include "plib/gnw/debug.h"

#if !defined(_WIN32)
#include "plib/gnw/input.h"
#endif

namespace fallout {

#if !defined(_WIN32)

namespace {

constexpr int kListenPort = 28080;
constexpr int kListenBacklog = 1;
constexpr size_t kDiscoveryRequestBufferSize = 256;

constexpr size_t kInboundBufferSize = 4096;
constexpr size_t kOutboundCap = 256 * 1024;
constexpr unsigned int kSampleIntervalMs = 500;

// Fixed raw chunk size for the world-map image fetch (144 KiB). Each
// chunk's base64 (~192 KiB) stays well under `kOutboundCap` (256 KiB).
constexpr size_t kMapChunkBytes = 147456;

enum class ClientState {
    AwaitingAuth,
    AwaitingHello,
    Ready,
};

struct CompanionConnection {
    int fd = -1;
    ClientState state = ClientState::AwaitingAuth;
    unsigned int nextSeq = 1;
    unsigned int lastSampleMs = 0;
    bool playerWasAvailable = false;

    // Last-sent snapshot. The server compares each tick's sample to
    // this and emits a `kind`-tagged `update` whose `payload` is the
    // *complete* per-kind object whenever the kind's fields (or, for
    // location kinds, the current surface) differ from `lastSent`.
    //
    // `lastSentPrimed` is the "we have a baseline to diff against" flag.
    // It is `true` from the first prime (`queueWorldMessage` after
    // `hello`, or the absent->present transition in `sampleReadyClient`)
    // and `false` only when the player is absent or on a fresh
    // connection. While `lastSentPrimed` is `false` the server does not
    // emit `update`s; it just records the current snapshot as the
    // baseline on the prime.
    CompanionSnapshot lastSent = {};
    bool lastSentPrimed = false;

    char inbound[kInboundBufferSize] = {};
    size_t inboundLen = 0;
    std::string outbound;
};

int gListenerFd = -1;
int gDiscoveryFd = -1;

// Server-owned copies of the bind host and password read from
// `fallout.cfg` at init time. The pointers returned by `config_get_string`
// are owned by `game_config`; we copy into our own buffers to keep the
// lifetime independent of the config subsystem.
std::string gBindHost;
std::string gPassword;

// Directory holding baked transmission audio, from `fallout.cfg`. Empty
// disables the whole transmission audio surface: the manifest comes back
// empty and every fetch answers `noRecord`, which the client renders as
// `NO RECORD AVAILABLE`. That is the graceful path, not an error path -
// a game with no baked audio is a supported configuration.
std::string gTransmissionAudioDir;

// Bounds from the TASK-024 asset contract. `kTransmissionAudioMax` is a
// sanity ceiling on a single narration; `kTransmissionEnvelopeMax` bounds the
// equalizer envelope, which rides *inside* the audio header and is
// therefore the thing that can push that header past `kOutboundCap`.
constexpr size_t kTransmissionAudioMax = 8u * 1024u * 1024u;
constexpr size_t kTransmissionEnvelopeMax = 64u * 1024u;

// Raw bytes per audio chunk. Same sizing rationale as `kMapChunkBytes`:
// base64 inflates by 4/3, so 144 KiB raw is ~192 KiB encoded, well under
// `kOutboundCap` (256 KiB).
constexpr size_t kTransmissionChunkBytes = 144u * 1024u;

// Per-connection audio transfer buffer.
//
// This DEPARTS from the world-map fetch deliberately. `handleGetMapChunk`
// re-acquires the map image on every chunk request because the image is
// already resident in the engine's cache - re-acquiring is free. Holodisk
// audio is a file, so re-reading per chunk would put disk I/O on the
// game's frame loop. The file is therefore read once, on the header
// request, and chunks are served as slices of this buffer.
//
// Being state, it needs rules, and they are enforced in the handlers:
//   - a header request for a different index REPLACES the buffer;
//   - a chunk request with no buffer, or a mismatched index, is answered
//     with `noTransfer` and never disconnects;
//   - every connection reset clears it (see `resetConnectionState`).
struct TransmissionTransfer {
    bool active = false;
    int index = -1;
    std::vector<unsigned char> bytes;

    void clear()
    {
        active = false;
        index = -1;
        bytes.clear();
        bytes.shrink_to_fit();
    }
};

TransmissionTransfer gTransmissionTransfer;

IdleFunc* gOriginalIdleFunc = nullptr;
bool gIdleHookInstalled = false;

void companionIdleHook()
{
    if (gOriginalIdleFunc != nullptr) {
        gOriginalIdleFunc();
    }
    companionServerTick(compat_timeGetTime());
}

CompanionConnection gConnection;

bool hasClient()
{
    return gConnection.fd >= 0;
}

bool setNonBlocking(int fd)
{
    int flags = fcntl(fd, F_GETFL, 0);
    if (flags == -1) {
        return false;
    }

    if (fcntl(fd, F_SETFL, flags | O_NONBLOCK) == -1) {
        return false;
    }

    return true;
}

void closeFd(int* fdPtr)
{
    if (*fdPtr >= 0) {
        close(*fdPtr);
        *fdPtr = -1;
    }
}

void clearConfigBuffers()
{
    gBindHost.clear();
    gPassword.clear();
    gTransmissionAudioDir.clear();
}

void resetConnectionState()
{
    gConnection.state = ClientState::AwaitingAuth;
    gConnection.nextSeq = 1;
    gConnection.lastSampleMs = 0;
    gConnection.playerWasAvailable = false;
    gConnection.lastSent = CompanionSnapshot{};
    gConnection.lastSentPrimed = false;
    gConnection.inboundLen = 0;
    gConnection.outbound.clear();
    gTransmissionTransfer.clear();
}

// Constant-time comparison of a candidate `std::string_view` against a
// configured `std::string`. The loop iterates over the longer of the two
// lengths; the missing bytes of the shorter side are XOR'd against zero.
// The accumulator is checked exactly once at the end; we never use
// `memcmp`, `strcmp`, or any other early-exit comparison.
//
// Threat model: this defends against LAN-local timing attacks on the
// password compare. The password itself is stored in cleartext in
// `fallout.cfg`; it does NOT defend against a same-host attacker with
// read access to the file. That ceiling is accepted per the milestone
// scope.
bool constantTimeEquals(std::string_view candidate, const std::string& configured)
{
    size_t n = candidate.size() > configured.size() ? candidate.size() : configured.size();
    unsigned int acc = 0;
    for (size_t i = 0; i < n; ++i) {
        unsigned char cb = i < configured.size() ? static_cast<unsigned char>(configured[i]) : 0;
        unsigned char xb = i < candidate.size() ? static_cast<unsigned char>(candidate[i]) : 0;
        acc |= static_cast<unsigned int>(cb ^ xb);
    }
    return acc == 0;
}

void closeConnection()
{
    closeFd(&(gConnection.fd));
    resetConnectionState();
}

void disableDiscoverySocket(const char* reason)
{
    if (gDiscoveryFd < 0) {
        return;
    }

    if (reason != nullptr) {
        debug_printf("companion: discovery disabled: %s\n", reason);
    }
    closeFd(&gDiscoveryFd);
}

void disconnectClient(const char* reason)
{
    if (reason != nullptr) {
        debug_printf("companion: client disconnected: %s\n", reason);
    }

    closeConnection();
}

unsigned int nextSequence()
{
    return gConnection.nextSeq++;
}

bool queueMessage(const std::string& message)
{
    if (message.empty()) {
        return true;
    }

    if (gConnection.outbound.size() + message.size() > kOutboundCap) {
        disconnectClient("outbound buffer overflow");
        return false;
    }

    gConnection.outbound.append(message);
    return true;
}

void primeLastSentState(const CompanionSnapshot& snapshot)
{
    gConnection.lastSent = snapshot;
    // `lastSentPrimed` is true only when the player is loaded. When the
    // player is absent, the next prime (on the absent->present
    // transition) will set it. This way the first post-hello tick does
    // not emit anything for a connection that starts at the main menu
    // or in a save-load transition.
    gConnection.lastSentPrimed = snapshot.hasPlayer;
}

void acceptClient(int fd)
{
    gConnection.fd = fd;
    resetConnectionState();
    debug_printf("companion: client accepted (fd=%d)\n", fd);
}

void rejectExtraClient(int fd)
{
    static constexpr char kAlreadyConnected[] = R"({"type":"alreadyConnected"})";
    send(fd, kAlreadyConnected, sizeof(kAlreadyConnected) - 1, 0);
    send(fd, "\n", 1, 0);
    // Shutdown the write half so the client receives the message before
    // the connection disappears.  The client will see EOF on read after
    // the message, not an RST.
    shutdown(fd, SHUT_WR);
    close(fd);
}

void acceptPendingClients()
{
    while (gListenerFd >= 0) {
        sockaddr_in addr;
        socklen_t addrLen = sizeof(addr);
        int fd = accept(gListenerFd, reinterpret_cast<sockaddr*>(&addr), &addrLen);
        if (fd < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                debug_printf("companion: accept error: %d\n", errno);
            }
            return;
        }

        if (!setNonBlocking(fd)) {
            debug_printf("companion: set non-blocking failed: %d\n", errno);
            close(fd);
            continue;
        }

        if (hasClient()) {
            rejectExtraClient(fd);
            continue;
        }

        acceptClient(fd);
    }
}

void queueWorldMessage()
{
    CompanionSnapshot snapshot = companionCollectSnapshot();
    if (!queueMessage(companionBuildWorld(snapshot.hasPlayer))) {
        return;
    }

    gConnection.state = ClientState::Ready;
    gConnection.lastSampleMs = 0;
    primeLastSentState(snapshot);
    debug_printf("companion: hello accepted\n");
}

void queueSnapshotMessage(const CompanionSnapshot& snapshot)
{
    if (!queueMessage(companionBuildSnapshot(nextSequence(), snapshot))) {
        return;
    }

    primeLastSentState(snapshot);
    debug_printf("companion: snapshot sent\n");
}

void queueSnapshotMessage()
{
    queueSnapshotMessage(companionCollectSnapshot());
}

void queueOnPlayerUnavailableMessage()
{
    if (!queueMessage(companionBuildOnPlayerUnavailable(nextSequence()))) {
        return;
    }

    debug_printf("companion: onPlayerUnavailable sent\n");
}

void queueOnPlayerAvailableMessage()
{
    if (!queueMessage(companionBuildOnPlayerAvailable(nextSequence()))) {
        return;
    }

    debug_printf("companion: onPlayerAvailable sent\n");
}

bool vitalsDiffer(const CompanionPlayerVitals& a, const CompanionPlayerVitals& b)
{
    return a.hp != b.hp || a.maxHp != b.maxHp;
}

bool statusDiffer(const CompanionPlayerStatus& a, const CompanionPlayerStatus& b)
{
    return a.armorClass != b.armorClass
        || a.currentCarryWeight != b.currentCarryWeight
        || a.carryWeight != b.carryWeight
        || a.meleeDamage != b.meleeDamage
        || a.damageResistance != b.damageResistance
        || a.poisonResistance != b.poisonResistance
        || a.radiationResistance != b.radiationResistance
        || a.healingRate != b.healingRate
        || a.radiation != b.radiation
        || a.poison != b.poison;
}

bool specialDiffer(const CompanionPlayerSpecial& a, const CompanionPlayerSpecial& b)
{
    return a.strength != b.strength
        || a.perception != b.perception
        || a.endurance != b.endurance
        || a.charisma != b.charisma
        || a.intelligence != b.intelligence
        || a.agility != b.agility
        || a.luck != b.luck;
}

bool progressionDiffer(const CompanionPlayerProgression& a, const CompanionPlayerProgression& b)
{
    return a.level != b.level
        || a.experience != b.experience
        || a.nextLevelExp != b.nextLevelExp;
}

bool localLocationDiffer(const CompanionPlayerLocalLocation& a, const CompanionPlayerLocalLocation& b)
{
    return a.tile != b.tile
        || a.elevation != b.elevation
        || a.map != b.map
        || strcmp(a.location, b.location) != 0
        || strcmp(a.mapName, b.mapName) != 0
        || strcmp(a.locationId, b.locationId) != 0
        || a.worldX != b.worldX
        || a.worldY != b.worldY;
}

bool worldLocationDiffer(const CompanionPlayerWorldLocation& a, const CompanionPlayerWorldLocation& b)
{
    return a.x != b.x || a.y != b.y;
}

bool inventoryItemDiffer(const CompanionInventoryItem& a, const CompanionInventoryItem& b)
{
    // Every field on the struct must be compared here. A field that is sent
    // but not diffed is silently stale forever: firing a weapon changes only
    // `ammoCurrent`, so if that field were missing from this comparison the
    // server would never resend, and the app would show the old load until
    // something else in the inventory happened to change.
    return a.pid != b.pid
        || a.type != b.type
        || a.count != b.count
        || a.slot != b.slot
        || strcmp(a.protoId, b.protoId) != 0
        || strcmp(a.name, b.name) != 0
        || a.weight != b.weight
        || a.value != b.value
        || a.dmgMin != b.dmgMin
        || a.dmgMax != b.dmgMax
        || a.minSt != b.minSt
        || a.range != b.range
        || a.ammoCurrent != b.ammoCurrent
        || a.ammoMax != b.ammoMax
        || strcmp(a.ammoName, b.ammoName) != 0
        || a.caliber != b.caliber
        || a.totalRounds != b.totalRounds
        || a.armorClass != b.armorClass
        || a.chargesCurrent != b.chargesCurrent
        || a.chargesMax != b.chargesMax
        || a.capsAmount != b.capsAmount;
}

bool inventoryDiffer(const CompanionInventorySnapshot& a, const CompanionInventorySnapshot& b)
{
    if (a.items.size() != b.items.size()) {
        return true;
    }

    for (size_t index = 0; index < a.items.size(); ++index) {
        if (inventoryItemDiffer(a.items[index], b.items[index])) {
            return true;
        }
    }

    return false;
}

bool questsDiffer(const CompanionQuestSnapshot& a, const CompanionQuestSnapshot& b)
{
    if (a.waterDaysRemaining != b.waterDaysRemaining
        || a.waterCountdownActive != b.waterCountdownActive) {
        return true;
    }

    if (a.quests.size() != b.quests.size()) {
        return true;
    }

    for (size_t index = 0; index < a.quests.size(); ++index) {
        const CompanionQuest& x = a.quests[index];
        const CompanionQuest& y = b.quests[index];

        if (x.locationIndex != y.locationIndex
            || x.slot != y.slot
            || x.completed != y.completed
            || x.waterChip != y.waterChip) {
            return true;
        }

        // Quest text is immutable per (location, slot), so comparing it is
        // redundant for detecting an actual quest change. Compared anyway
        // because it costs nothing and makes a catalog that resolved late
        // -- first sample before the message list loaded, second after --
        // self-correcting instead of leaving the client permanently stale.
        if (strcmp(x.location, y.location) != 0 || strcmp(x.text, y.text) != 0) {
            return true;
        }
    }

    return false;
}

bool transmissionsDiffer(const CompanionTransmissionSnapshot& a,
    const CompanionTransmissionSnapshot& b)
{
    if (a.transmissions.size() != b.transmissions.size()) {
        return true;
    }

    for (size_t index = 0; index < a.transmissions.size(); ++index) {
        const CompanionTransmission& x = a.transmissions[index];
        const CompanionTransmission& y = b.transmissions[index];

        if (x.index != y.index) {
            return true;
        }

        if (strcmp(x.title, y.title) != 0) {
            return true;
        }
    }

    return false;
}

bool holodisksDiffer(const CompanionHolodiskSnapshot& a, const CompanionHolodiskSnapshot& b)
{
    if (a.holodisks.size() != b.holodisks.size()) {
        return true;
    }

    for (size_t index = 0; index < a.holodisks.size(); ++index) {
        const CompanionHolodisk& x = a.holodisks[index];
        const CompanionHolodisk& y = b.holodisks[index];

        if (x.index != y.index) {
            return true;
        }

        // Same reasoning as the quest text compare above: a title is
        // immutable per index, but comparing it makes a late-resolving
        // catalog self-correcting rather than permanently stale.
        if (strcmp(x.title, y.title) != 0) {
            return true;
        }

        // And the body, for exactly that reason: a disk whose text failed
        // to resolve on one sample and succeeded on the next must send an
        // update, or it stays "unreadable" on the device for the rest of
        // the session. Cheap - this runs every 500 ms and compares
        // already-resident strings.
        if (x.body != y.body) {
            return true;
        }
    }

    return false;
}

void rejectCommand(int id, const std::string_view& name, const char* error)
{
    if (!queueMessage(companionBuildCmdAck(id, false, error))) {
        return;
    }

    debug_printf("companion: cmd rejected (%.*s id=%d error=%s)\n",
        static_cast<int>(name.size()),
        name.data(),
        id,
        error);
}

// The normal inventory screen charges 4 AP minus Quick Pockets when opened
// during the player's combat turn. A companion action is the equivalent of
// opening that screen and performing one inventory operation, so it uses the
// same cost and turn restriction without opening a second engine UI.
bool companionCanUseInventory(int id, std::string_view name, int& actionPoints)
{
    actionPoints = 0;
    if (!isInCombat()) {
        return true;
    }
    if (combat_whose_turn() != obj_dude) {
        rejectCommand(id, name, "notPlayersTurn");
        return false;
    }
    actionPoints = 4 - perk_level(PERK_QUICK_POCKETS);
    if (actionPoints > obj_dude->data.critter.combat.ap) {
        rejectCommand(id, name, "notEnoughActionPoints");
        return false;
    }
    return true;
}

void companionSpendInventoryActionPoints(int actionPoints)
{
    if (actionPoints <= 0) {
        return;
    }
    obj_dude->data.critter.combat.ap -= actionPoints;
    intface_update_move_points(obj_dude->data.critter.combat.ap, combat_free_move);
}

bool companionUseSelfDrug(Object* item)
{
    int uiResult = inven_companion_action(item, InventoryCompanionAction::UseSelf);
    if (uiResult != 0) {
        return uiResult > 0;
    }
    if (item_get_type(item) != ITEM_TYPE_DRUG) {
        return false;
    }
    if (item_d_take_drug(obj_dude, item) != 1) {
        return false;
    }
    if (item_remove_mult(obj_dude, item, 1) != 0) {
        return false;
    }
    obj_destroy(item);
    intface_update_hit_points(true);
    return true;
}

bool companionEquip(Object* item, std::string_view action)
{
    InventoryCompanionAction uiAction;
    if (action == "equipArmor") {
        uiAction = InventoryCompanionAction::EquipArmor;
    } else if (action == "equipLeftHand") {
        uiAction = InventoryCompanionAction::EquipLeftHand;
    } else if (action == "equipRightHand") {
        uiAction = InventoryCompanionAction::EquipRightHand;
    } else if (action == "equipBothHands") {
        uiAction = InventoryCompanionAction::EquipBothHands;
    } else {
        return false;
    }
    int uiResult = inven_companion_action(item, uiAction);
    if (uiResult != 0) {
        return uiResult > 0;
    }

    int itemType = item_get_type(item);
    if (action == "equipArmor") {
        if (itemType != ITEM_TYPE_ARMOR) {
            return false;
        }
        Object* oldArmor = inven_worn(obj_dude);
        if (inven_wield(obj_dude, item, HAND_RIGHT) == -1) {
            return false;
        }
        adjust_ac(obj_dude, oldArmor, item);
        return true;
    }

    if (itemType != ITEM_TYPE_WEAPON && itemType != ITEM_TYPE_MISC) {
        return false;
    }

    bool bothHands = action == "equipBothHands";
    if (bothHands != (itemType == ITEM_TYPE_WEAPON && item_w_is_2handed(item) != 0)) {
        return false;
    }
    if (!bothHands && action != "equipLeftHand" && action != "equipRightHand") {
        return false;
    }

    Object* left = inven_left_hand(obj_dude);
    Object* right = inven_right_hand(obj_dude);
    if (bothHands) {
        if (left != nullptr) left->flags &= ~OBJECT_IN_ANY_HAND;
        if (right != nullptr) right->flags &= ~OBJECT_IN_ANY_HAND;
        if (inven_wield(obj_dude, item, HAND_RIGHT) == -1) {
            return false;
        }
        item->flags |= OBJECT_IN_LEFT_HAND | OBJECT_IN_RIGHT_HAND;
    } else {
        // Replacing either side of a two-handed weapon releases both slots.
        if (left != nullptr && left == right) {
            left->flags &= ~OBJECT_IN_ANY_HAND;
        }
        // Moving an already-held one-handed item must not leave its old hand
        // bit set, which would accidentally turn it into a two-handed item.
        item->flags &= ~OBJECT_IN_ANY_HAND;
        if (inven_wield(obj_dude, item, action == "equipRightHand" ? HAND_RIGHT : HAND_LEFT) == -1) {
            return false;
        }
    }
    return true;
}

void handleCommandMessage(const char* line, size_t lineLength)
{
    CompanionCommandRequest request = {};
    if (!companionExtractCommandRequest(line, lineLength, request)) {
        disconnectClient("invalid cmd");
        return;
    }

    if (request.name == "ping") {
        if (!queueMessage(companionBuildCmdAck(request.id, true))) {
            return;
        }
        debug_printf("companion: cmd accepted (%.*s id=%d)\n",
            static_cast<int>(request.name.size()),
            request.name.data(),
            request.id);
        return;
    }

    if (request.name == "getSnapshot") {
        CompanionSnapshot snapshot = companionCollectSnapshot();
        std::string payload = companionBuildSnapshotPayload(snapshot);
        if (payload.empty()) {
            disconnectClient("snapshot formatting failure");
            return;
        }

        if (!queueMessage(companionBuildCmdAck(request.id, true, nullptr, payload))) {
            return;
        }

        debug_printf("companion: cmd accepted (%.*s id=%d)\n",
            static_cast<int>(request.name.size()),
            request.name.data(),
            request.id);

        queueSnapshotMessage(snapshot);
        return;
    }

    if (request.name == "useSelf" || request.name == "equipArmor"
        || request.name == "equipLeftHand" || request.name == "equipRightHand"
        || request.name == "equipBothHands") {
        if (!request.hasObjectId) {
            rejectCommand(request.id, request.name, "missingItem");
            return;
        }

        int actionPoints;
        if (!companionCanUseInventory(request.id, request.name, actionPoints)) {
            return;
        }

        Object* item = inven_find_id(obj_dude, request.objectId);
        if (item == nullptr) {
            Object* heldOwner = nullptr;
            Object* heldRight = nullptr;
            Object* heldLeft = nullptr;
            Object* heldWorn = nullptr;
            inven_ui_held_slots(&heldOwner, &heldRight, &heldLeft, &heldWorn);
            if (heldOwner == obj_dude) {
                Object* heldItems[] = { heldRight, heldLeft, heldWorn };
                for (Object* held : heldItems) {
                    if (held != nullptr && held->id == request.objectId) {
                        item = held;
                        break;
                    }
                }
            }
        }
        if (item == nullptr) {
            rejectCommand(request.id, request.name, "itemNotFound");
            return;
        }

        bool ok = request.name == "useSelf"
            ? companionUseSelfDrug(item)
            : companionEquip(item, request.name);
        if (!ok) {
            rejectCommand(request.id, request.name, "actionNotAvailable");
            return;
        }

        companionSpendInventoryActionPoints(actionPoints);
        intface_update_items(false);
        // An action from the app is reported exactly like an equip made
        // in-game: by the sampler noticing it. Pushing a snapshot here
        // instead would break the change detection it looks like it
        // helps -- `queueSnapshotMessage` also primes `lastSent`, so the
        // baseline would advance past state the client never applied
        // (the app only accepts a `snapshot` it asked for), and the
        // `player.inventory` update would then never be emitted. Leave
        // `lastSent` holding pre-action truth and let the diff fire.
        //
        // Zeroing the timer costs nothing: `companionServerTick` runs
        // `readFromClient` (this handler) -> `sampleReadyClient` ->
        // `flushOutbound`, so the resample happens later in this same
        // tick and the ack and the update leave together.
        //
        // An action that mutates nothing (`equipArmor` on the armor
        // already worn, an equip into the slot the item already holds)
        // emits no update, which is correct -- the ack is the
        // confirmation, and there is no change to report.
        gConnection.lastSampleMs = 0;
        queueMessage(companionBuildCmdAck(request.id, true));
        return;
    }

    rejectCommand(request.id, request.name, "unknownCommand");
}

// Reads the engine's active palette (`cmap`, 6-bit per channel) and
// normalizes each value to 8-bit (0-63 -> 0-255) into `out` (768 bytes).
void buildNormalizedPalette(unsigned char out[768])
{
    for (size_t i = 0; i < 768; ++i) {
        out[i] = static_cast<unsigned char>(cmap[i] * 255 / 63);
    }
}

// -- Transmission audio -----------------------------------------------

// Builds `<dir>/transmission_NN.<ext>` for a VALIDATED movie index.
//
// The index is the ONLY client-controlled input, and callers must have
// already range-checked it against `MOVIE_VEXPLD..MOVIE_COUNT`. No part of
// the path comes from the wire: the client cannot supply a directory, a
// filename, or a fragment of one. This is what keeps a file-read
// primitive inside the game engine from becoming a path-traversal hole.
std::string transmissionAssetPath(int index, const char* extension)
{
    char name[64];
    int n = snprintf(name, sizeof(name), "transmission_%02d.%s", index, extension);
    if (n < 0 || static_cast<size_t>(n) >= sizeof(name)) {
        return std::string();
    }

    std::string path = gTransmissionAudioDir;
    if (!path.empty() && path.back() != '/' && path.back() != '\\') {
        path.push_back('/');
    }
    path.append(name, static_cast<size_t>(n));
    return path;
}

// Reads a whole file under `limit`. Returns false for missing, unreadable,
// or oversized files - all of which are reported to the client as a
// non-fatal error, never as a disconnect.
bool readWholeFile(const std::string& path, size_t limit, std::vector<unsigned char>& out)
{
    out.clear();

    if (path.empty()) {
        return false;
    }

    FILE* stream = fopen(path.c_str(), "rb");
    if (stream == nullptr) {
        return false;
    }

    if (fseek(stream, 0, SEEK_END) != 0) {
        fclose(stream);
        return false;
    }

    long size = ftell(stream);
    if (size < 0 || static_cast<size_t>(size) > limit) {
        fclose(stream);
        return false;
    }

    if (fseek(stream, 0, SEEK_SET) != 0) {
        fclose(stream);
        return false;
    }

    out.resize(static_cast<size_t>(size));
    size_t read = size > 0 ? fread(out.data(), 1, static_cast<size_t>(size), stream) : 0;
    fclose(stream);

    if (read != static_cast<size_t>(size)) {
        out.clear();
        return false;
    }

    return true;
}

void handleGetTransmissionManifestMessage()
{
    std::vector<CompanionTransmissionManifestEntry> entries;

    for (int index = MOVIE_VEXPLD; index < MOVIE_COUNT; ++index) {
        std::vector<unsigned char> audio;
        if (!readWholeFile(transmissionAssetPath(index, "ogg"), kTransmissionAudioMax, audio)) {
            continue;
        }

        std::vector<unsigned char> envelope;
        if (!readWholeFile(transmissionAssetPath(index, "env"), kTransmissionEnvelopeMax, envelope)) {
            // Audio without a usable envelope is not offered: the screen
            // needs the envelope for the equalizer, for end-of-track, and
            // for clamping seeks. Half a record is not a record.
            continue;
        }

        CompanionTransmissionManifestEntry entry = {};
        entry.index = index;
        entry.bytes = audio.size();
        entry.envelopeBytes = envelope.size();
        entries.push_back(entry);
    }

    std::string message = companionBuildTransmissionManifest(entries);
    if (message.empty()) {
        debug_printf("companion: getTransmissionManifest failed (formatting)\n");
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: transmissionManifest sent (entries=%zu)\n", entries.size());
}

void handleGetTransmissionAudioMessage(const char* line, size_t lineLength)
{
    int index = 0;
    if (!companionExtractTransmissionIndex(line, lineLength, "getTransmissionAudio", index)) {
        disconnectClient("invalid getTransmissionAudio");
        return;
    }

    // Range check BEFORE any filesystem call. Bounds are the *listable*
    // movie range: `ListArchive` skips the two logos and the intro, so
    // offering them here would contradict the in-game screen.
    if (index < MOVIE_VEXPLD || index >= MOVIE_COUNT) {
        queueMessage(companionBuildTransmissionAudioError(index, "index"));
        return;
    }

    std::vector<unsigned char> audio;
    if (!readWholeFile(transmissionAssetPath(index, "ogg"), kTransmissionAudioMax, audio)) {
        queueMessage(companionBuildTransmissionAudioError(index, "noRecord"));
        return;
    }

    std::vector<unsigned char> envelope;
    if (!readWholeFile(transmissionAssetPath(index, "env"), kTransmissionEnvelopeMax, envelope)) {
        queueMessage(companionBuildTransmissionAudioError(index, "noRecord"));
        return;
    }

    std::string message = companionBuildTransmissionAudioHeader(
        index, audio.size(), kTransmissionChunkBytes, envelope.data(), envelope.size());
    if (message.empty()) {
        queueMessage(companionBuildTransmissionAudioError(index, "tooLarge"));
        return;
    }

    // The envelope rides inside this header, so the header is the one
    // message whose size is driven by asset content rather than by our own
    // chunking. Check it explicitly: overflowing `kOutboundCap` inside
    // `queueMessage` DISCONNECTS the client, which would turn an oversized
    // asset into a confusing dropped connection.
    if (message.size() > kOutboundCap) {
        queueMessage(companionBuildTransmissionAudioError(index, "tooLarge"));
        debug_printf("companion: transmissionAudioHeader too large (index=%d bytes=%zu)\n",
            index, message.size());
        return;
    }

    // Replace any previous transfer; a client may switch disks freely.
    gTransmissionTransfer.clear();
    gTransmissionTransfer.active = true;
    gTransmissionTransfer.index = index;
    gTransmissionTransfer.bytes = std::move(audio);

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: transmissionAudioHeader sent (index=%d bytes=%zu)\n",
        index, gTransmissionTransfer.bytes.size());
}

void handleGetTransmissionAudioChunkMessage(const char* line, size_t lineLength)
{
    int index = 0;
    int chunk = 0;
    if (!companionExtractTransmissionChunkRequest(line, lineLength, index, chunk)) {
        disconnectClient("invalid getTransmissionAudioChunk");
        return;
    }

    if (!gTransmissionTransfer.active || gTransmissionTransfer.index != index) {
        // Chunk before header, or for a disk the client has since switched
        // away from. Recoverable: the client re-requests the header.
        queueMessage(companionBuildTransmissionAudioError(index, "noTransfer"));
        return;
    }

    size_t total = gTransmissionTransfer.bytes.size();
    size_t start = static_cast<size_t>(chunk) * kTransmissionChunkBytes;
    if (chunk < 0 || start >= total) {
        queueMessage(companionBuildTransmissionAudioError(index, "index"));
        return;
    }

    size_t endOffset = start + kTransmissionChunkBytes;
    if (endOffset > total) {
        endOffset = total;
    }
    size_t length = endOffset - start;

    std::string message = companionBuildTransmissionAudioChunk(
        index, chunk, gTransmissionTransfer.bytes.data() + start, length);
    if (message.empty()) {
        queueMessage(companionBuildTransmissionAudioError(index, "chunk"));
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: transmissionAudioChunk sent (index=%d chunk=%d bytes=%zu)\n",
        index, chunk, length);
}

void handleGetMapMessage()
{
    const unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    CacheEntry* handle = nullptr;
    if (!companionLockWorldMapImage(&pixels, &width, &height, &handle)) {
        queueMessage(companionBuildMapError("mapUnavailable"));
        debug_printf("companion: getMap failed (mapUnavailable)\n");
        return;
    }

    unsigned char palette[768];
    buildNormalizedPalette(palette);

    std::string message = companionBuildMapHeader(width, height, palette, kMapChunkBytes);
    companionUnlockWorldMapImage(handle);

    if (message.empty()) {
        queueMessage(companionBuildMapError("mapUnavailable"));
        debug_printf("companion: getMap failed (header formatting)\n");
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: mapHeader sent (width=%d height=%d)\n", width, height);
}

void handleGetMapChunkMessage(const char* line, size_t lineLength)
{
    int index = 0;
    if (!companionExtractMapChunkIndex(line, lineLength, index)) {
        disconnectClient("invalid getMapChunk");
        return;
    }

    const unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    CacheEntry* handle = nullptr;
    if (!companionLockWorldMapImage(&pixels, &width, &height, &handle)) {
        queueMessage(companionBuildMapError("mapUnavailable"));
        debug_printf("companion: getMapChunk failed (mapUnavailable)\n");
        return;
    }

    size_t total = static_cast<size_t>(width) * static_cast<size_t>(height);
    size_t start = static_cast<size_t>(index) * kMapChunkBytes;
    if (index < 0 || start >= total) {
        companionUnlockWorldMapImage(handle);
        queueMessage(companionBuildMapError("index"));
        debug_printf("companion: getMapChunk index out of range (index=%d)\n", index);
        return;
    }

    size_t endOffset = start + kMapChunkBytes;
    if (endOffset > total) {
        endOffset = total;
    }
    size_t length = endOffset - start;

    std::string message = companionBuildMapChunk(index, pixels + start, length);
    companionUnlockWorldMapImage(handle);

    if (message.empty()) {
        queueMessage(companionBuildMapError("mapUnavailable"));
        debug_printf("companion: getMapChunk failed (chunk formatting)\n");
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: mapChunk sent (index=%d bytes=%zu)\n", index, length);
}

// Fixed palette for the local automap image. Only the three meaningful
// indices are populated, with increasing luminance so the app's
// luminance->green LUT renders them as distinct Pip-Boy shades: empty maps
// to the background, scenery to a mid green, and walls (brightest) to the
// foreground green. The remaining 253 entries are black and unused.
void buildLocalMapPalette(unsigned char out[768])
{
    memset(out, 0, 768);
    // index 0 = empty -> black (background)
    // index 1 = wall -> bright (walls stand out, like colorTable[992])
    out[3] = 230;
    out[4] = 230;
    out[5] = 230;
    // index 2 = scenery -> mid (like colorTable[480])
    out[6] = 120;
    out[7] = 120;
    out[8] = 120;
}

// True only when a real local map (town/dungeon/vault) is loaded and the
// player is actually playing -- the same gate the snapshot uses to pick the
// Local surface (`companionIsPlayerReallyPlaying()` + not on the world map),
// NOT `!worldMapIsActive()` alone.
bool localMapAvailable()
{
    return companionIsPlayerReallyPlaying() && !worldMapIsActive();
}

void handleGetLocalMapMessage()
{
    if (!localMapAvailable()) {
        queueMessage(companionBuildLocalMapError("noLocalMap"));
        debug_printf("companion: getLocalMap failed (noLocalMap)\n");
        return;
    }

    unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    bool explored = false;
    if (!companionBuildLocalMapImage(map_elevation, &pixels, &width, &height, &explored)) {
        queueMessage(companionBuildLocalMapError("mapUnavailable"));
        debug_printf("companion: getLocalMap failed (mapUnavailable)\n");
        return;
    }

    unsigned char palette[768];
    buildLocalMapPalette(palette);

    std::string message = companionBuildLocalMapHeader(map_get_index_number(),
        map_elevation,
        width,
        height,
        explored,
        palette,
        kMapChunkBytes);
    companionFreeLocalMapImage(pixels);

    if (message.empty()) {
        queueMessage(companionBuildLocalMapError("mapUnavailable"));
        debug_printf("companion: getLocalMap failed (header formatting)\n");
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: localMapHeader sent (map=%d elevation=%d)\n",
        map_get_index_number(),
        map_elevation);
}

void handleGetLocalMapChunkMessage(const char* line, size_t lineLength)
{
    int index = 0;
    if (!companionExtractLocalMapChunkIndex(line, lineLength, index)) {
        disconnectClient("invalid getLocalMapChunk");
        return;
    }

    if (!localMapAvailable()) {
        queueMessage(companionBuildLocalMapError("noLocalMap"));
        debug_printf("companion: getLocalMapChunk failed (noLocalMap)\n");
        return;
    }

    unsigned char* pixels = nullptr;
    int width = 0;
    int height = 0;
    if (!companionBuildLocalMapImage(map_elevation, &pixels, &width, &height)) {
        queueMessage(companionBuildLocalMapError("mapUnavailable"));
        debug_printf("companion: getLocalMapChunk failed (mapUnavailable)\n");
        return;
    }

    size_t total = static_cast<size_t>(width) * static_cast<size_t>(height);
    size_t start = static_cast<size_t>(index) * kMapChunkBytes;
    if (index < 0 || start >= total) {
        companionFreeLocalMapImage(pixels);
        queueMessage(companionBuildLocalMapError("index"));
        debug_printf("companion: getLocalMapChunk index out of range (index=%d)\n", index);
        return;
    }

    size_t endOffset = start + kMapChunkBytes;
    if (endOffset > total) {
        endOffset = total;
    }
    size_t length = endOffset - start;

    std::string message = companionBuildLocalMapChunk(index,
        map_get_index_number(),
        map_elevation,
        pixels + start,
        length);
    companionFreeLocalMapImage(pixels);

    if (message.empty()) {
        queueMessage(companionBuildLocalMapError("mapUnavailable"));
        debug_printf("companion: getLocalMapChunk failed (chunk formatting)\n");
        return;
    }

    if (!queueMessage(message)) {
        return;
    }
    debug_printf("companion: localMapChunk sent (index=%d bytes=%zu)\n", index, length);
}

void handleClientMessage(CompanionClientMessage message, const char* line, size_t lineLength)
{
    if (gConnection.state == ClientState::AwaitingAuth) {
        if (message != CompanionClientMessage::Auth) {
            disconnectClient("non-auth first message");
            return;
        }

        std::string_view candidate;
        if (!companionExtractAuthPassword(line, lineLength, candidate)) {
            debug_printf("companion: auth rejected\n");
            disconnectClient("auth rejected");
            return;
        }

        if (!constantTimeEquals(candidate, gPassword)) {
            debug_printf("companion: auth rejected\n");
            disconnectClient("auth rejected");
            return;
        }

        debug_printf("companion: auth accepted\n");
        gConnection.state = ClientState::AwaitingHello;
        return;
    }

    if (gConnection.state == ClientState::AwaitingHello) {
        if (message != CompanionClientMessage::Hello) {
            disconnectClient("invalid message");
            return;
        }

        queueWorldMessage();
        return;
    }

    if (message == CompanionClientMessage::GetSnapshot) {
        queueSnapshotMessage();
        return;
    }

    if (message == CompanionClientMessage::Cmd) {
        handleCommandMessage(line, lineLength);
        return;
    }

    if (message == CompanionClientMessage::GetMap) {
        handleGetMapMessage();
        return;
    }

    if (message == CompanionClientMessage::GetMapChunk) {
        handleGetMapChunkMessage(line, lineLength);
        return;
    }

    if (message == CompanionClientMessage::GetLocalMap) {
        handleGetLocalMapMessage();
        return;
    }

    if (message == CompanionClientMessage::GetLocalMapChunk) {
        handleGetLocalMapChunkMessage(line, lineLength);
        return;
    }

    if (message == CompanionClientMessage::GetTransmissionManifest) {
        handleGetTransmissionManifestMessage();
        return;
    }

    if (message == CompanionClientMessage::GetTransmissionAudio) {
        handleGetTransmissionAudioMessage(line, lineLength);
        return;
    }

    if (message == CompanionClientMessage::GetTransmissionAudioChunk) {
        handleGetTransmissionAudioChunkMessage(line, lineLength);
        return;
    }

    if (message == CompanionClientMessage::Hello) {
        return;
    }

    disconnectClient("invalid message");
}

void processInboundLines()
{
    while (hasClient()) {
        char* newline = static_cast<char*>(memchr(gConnection.inbound, '\n', gConnection.inboundLen));
        if (newline == nullptr) {
            return;
        }

        size_t lineLength = static_cast<size_t>(newline - gConnection.inbound);
        char* lineStart = gConnection.inbound;
        CompanionClientMessage message = companionParseClientMessage(lineStart, lineLength);
        if (message == CompanionClientMessage::Invalid) {
            disconnectClient("invalid message");
            return;
        }

        // Handle the message before shifting the buffer. `lineStart` is
        // `gConnection.inbound`; once the `memmove` runs, those bytes are
        // the *next* line, and the auth handler (which returns a
        // `string_view` into the buffer) would read the wrong content.
        handleClientMessage(message, lineStart, lineLength);
        if (!hasClient()) {
            return;
        }

        size_t consumed = lineLength + 1;
        memmove(gConnection.inbound,
            gConnection.inbound + consumed,
            gConnection.inboundLen - consumed);
        gConnection.inboundLen -= consumed;
    }
}

void readFromClient()
{
    while (hasClient()) {
        if (gConnection.inboundLen == kInboundBufferSize) {
            disconnectClient("inbound buffer overflow");
            return;
        }

        ssize_t bytesRead = recv(gConnection.fd,
            gConnection.inbound + gConnection.inboundLen,
            kInboundBufferSize - gConnection.inboundLen,
            MSG_DONTWAIT);

        if (bytesRead == 0) {
            disconnectClient("client closed connection");
            return;
        }

        if (bytesRead < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                return;
            }

            disconnectClient("recv error");
            return;
        }

        gConnection.inboundLen += static_cast<size_t>(bytesRead);
        processInboundLines();
        if (!hasClient()) {
            return;
        }

        if (gConnection.inboundLen == kInboundBufferSize
            && memchr(gConnection.inbound, '\n', gConnection.inboundLen) == nullptr) {
            disconnectClient("inbound buffer overflow");
            return;
        }
    }
}

void flushOutbound()
{
    while (hasClient() && !gConnection.outbound.empty()) {
        int flags = MSG_DONTWAIT;
#if defined(MSG_NOSIGNAL)
        flags |= MSG_NOSIGNAL;
#endif

        ssize_t bytesSent = send(
            gConnection.fd,
            gConnection.outbound.data(),
            gConnection.outbound.size(),
            flags);

        if (bytesSent > 0) {
            gConnection.outbound.erase(0, static_cast<size_t>(bytesSent));
            continue;
        }

        if (bytesSent < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            return;
        }

        disconnectClient("send error");
        return;
    }
}

void sampleReadyClient(unsigned int now)
{
    if (!hasClient() || gConnection.state != ClientState::Ready) {
        return;
    }

    if (gConnection.lastSampleMs != 0
        && now - gConnection.lastSampleMs < kSampleIntervalMs) {
        return;
    }

    gConnection.lastSampleMs = now;

    CompanionSnapshot current = companionCollectSnapshot();

    if (current.hasPlayer != gConnection.playerWasAvailable) {
        gConnection.playerWasAvailable = current.hasPlayer;
        if (current.hasPlayer) {
            // Absent -> present in steady state. Emit the one-shot
            // `onPlayerAvailable` notification and prime
            // `lastSent` to the current sample so the next tick's
            // diff is empty. The client is expected to send
            // `getSnapshot` in response; we do not push the
            // snapshot ourselves (snapshot stays a request/response
            // contract). The handshake path is unaffected: that one
            // runs before `sampleReadyClient` is ever called.
            queueOnPlayerAvailableMessage();
            primeLastSentState(current);
        } else {
            // Present -> absent. Emit the one-shot transition and
            // clear the baseline so the next present sample is
            // treated as fresh.
            gConnection.lastSentPrimed = false;
            queueOnPlayerUnavailableMessage();
        }
        return;
    }

    if (!current.hasPlayer || !gConnection.lastSentPrimed) {
        return;
    }

    // Vitals. Always present when the player is loaded.
    if (vitalsDiffer(current.vitals, gConnection.lastSent.vitals)) {
        if (!queueMessage(companionBuildVitalsUpdate(
                nextSequence(), current.vitals))) {
            return;
        }
        gConnection.lastSent.vitals = current.vitals;
        debug_printf("companion: update sent (player.vitals)\n");
    }

    if (statusDiffer(current.status, gConnection.lastSent.status)) {
        if (!queueMessage(companionBuildStatusUpdate(
                nextSequence(), current.status))) {
            return;
        }
        gConnection.lastSent.status = current.status;
        debug_printf("companion: update sent (player.status)\n");
    }

    if (specialDiffer(current.special, gConnection.lastSent.special)) {
        if (!queueMessage(companionBuildSpecialUpdate(
                nextSequence(), current.special))) {
            return;
        }
        gConnection.lastSent.special = current.special;
        debug_printf("companion: update sent (player.special)\n");
    }

    if (progressionDiffer(current.progression, gConnection.lastSent.progression)) {
        if (!queueMessage(companionBuildProgressionUpdate(
                nextSequence(), current.progression))) {
            return;
        }
        gConnection.lastSent.progression = current.progression;
        debug_printf("companion: update sent (player.progression)\n");
    }

    // Surface. The current surface drives which location kind is
    // meaningful. A change in `surface` forces the new kind's first
    // emit even if its numeric fields happen to match the stale
    // `lastSent` (which still holds the *other* surface's data).
    if (current.surface == CompanionPlayerSurface::Local) {
        bool surfaceChanged = gConnection.lastSent.surface != CompanionPlayerSurface::Local;
        if (surfaceChanged
            || localLocationDiffer(current.localLocation, gConnection.lastSent.localLocation)) {
            if (!queueMessage(companionBuildLocalLocationUpdate(
                    nextSequence(), current.localLocation))) {
                return;
            }
            gConnection.lastSent.localLocation = current.localLocation;
            gConnection.lastSent.surface = CompanionPlayerSurface::Local;
            debug_printf("companion: update sent (player.localLocation)\n");
        }
    } else {
        bool surfaceChanged = gConnection.lastSent.surface != CompanionPlayerSurface::World;
        if (surfaceChanged
            || worldLocationDiffer(current.worldLocation, gConnection.lastSent.worldLocation)) {
            if (!queueMessage(companionBuildWorldLocationUpdate(
                    nextSequence(), current.worldLocation))) {
                return;
            }
            gConnection.lastSent.worldLocation = current.worldLocation;
            gConnection.lastSent.surface = CompanionPlayerSurface::World;
            debug_printf("companion: update sent (player.worldLocation)\n");
        }
    }

    if (inventoryDiffer(current.inventory, gConnection.lastSent.inventory)) {
        if (!queueMessage(companionBuildInventoryUpdate(
                nextSequence(), current.inventory))) {
            return;
        }
        gConnection.lastSent.inventory = current.inventory;
        debug_printf("companion: update sent (player.inventory)\n");
    }

    if (questsDiffer(current.quests, gConnection.lastSent.quests)) {
        if (!queueMessage(companionBuildQuestsUpdate(
                nextSequence(), current.quests))) {
            return;
        }
        gConnection.lastSent.quests = current.quests;
        debug_printf("companion: update sent (player.quests)\n");
    }

    // This is what makes a disk found mid-session appear on the device
    // without a reconnect: the set is re-diffed on every sample, so the
    // GVAR flipping is picked up on the next tick.
    if (holodisksDiffer(current.holodisks, gConnection.lastSent.holodisks)) {
        if (!queueMessage(companionBuildHolodisksUpdate(
                nextSequence(), current.holodisks))) {
            return;
        }
        gConnection.lastSent.holodisks = current.holodisks;
        debug_printf("companion: update sent (player.holodisks)\n");
    }

    // Same rationale as the holodisk diff: re-diffed every sample, so a
    // cutscene watched mid-session reaches the device without a reconnect.
    if (transmissionsDiffer(current.transmissions, gConnection.lastSent.transmissions)) {
        if (!queueMessage(companionBuildTransmissionsUpdate(
                nextSequence(), current.transmissions))) {
            return;
        }
        gConnection.lastSent.transmissions = current.transmissions;
        debug_printf("companion: update sent (player.transmissions)\n");
    }
}

// Returns true when `buffer` looks like a `{"type":"discover"}` request.
// Whitespace-tolerant in the same minimal way the TCP parser is. Anything
// else is silently ignored (UDP is fire-and-forget; bad packets are
// dropped without a reply, so the server is not a useful reflector for
// arbitrary payloads).
bool isDiscoveryRequest(const char* buffer, size_t length)
{
    static constexpr char kDiscover[] = R"({"type":"discover"})";
    static constexpr char kDiscoverSpaced[] = R"({"type": "discover"})";
    constexpr size_t kDiscoverLen = sizeof(kDiscover) - 1;
    constexpr size_t kDiscoverSpacedLen = sizeof(kDiscoverSpaced) - 1;

    size_t start = 0;
    while (start < length
        && (buffer[start] == ' ' || buffer[start] == '\t'
            || buffer[start] == '\n' || buffer[start] == '\r')) {
        ++start;
    }
    size_t end = length;
    while (end > start
        && (buffer[end - 1] == ' ' || buffer[end - 1] == '\t'
            || buffer[end - 1] == '\n' || buffer[end - 1] == '\r')) {
        --end;
    }
    size_t trimmed = end - start;

    if (trimmed == kDiscoverLen
        && memcmp(buffer + start, kDiscover, kDiscoverLen) == 0) {
        return true;
    }
    if (trimmed == kDiscoverSpacedLen
        && memcmp(buffer + start, kDiscoverSpaced, kDiscoverSpacedLen) == 0) {
        return true;
    }
    return false;
}

void handleDiscoveryRequests()
{
    while (gDiscoveryFd >= 0) {
        char buffer[kDiscoveryRequestBufferSize];
        sockaddr_in sender;
        socklen_t senderLen = sizeof(sender);

        ssize_t bytesReceived = recvfrom(gDiscoveryFd,
            buffer,
            sizeof(buffer),
            MSG_DONTWAIT,
            reinterpret_cast<sockaddr*>(&sender),
            &senderLen);
        if (bytesReceived < 0) {
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                debug_printf("companion: discovery recv error: %d\n", errno);
                disableDiscoverySocket("recv error");
            }
            return;
        }

        if (bytesReceived == 0) {
            // Zero-length UDP datagram. Nothing to parse; drop it.
            continue;
        }

        if (!isDiscoveryRequest(buffer, static_cast<size_t>(bytesReceived))) {
            // Drop silently. Replying to arbitrary UDP traffic would
            // turn the server into a reflector.
            continue;
        }

        std::string reply = companionBuildAnnounce(gBindHost);
        if (reply.empty()) {
            disableDiscoverySocket("announce formatting failure");
            return;
        }

        ssize_t bytesSent = sendto(gDiscoveryFd,
            reply.data(),
            reply.size(),
            0,
            reinterpret_cast<sockaddr*>(&sender),
            senderLen);
        if (bytesSent < 0 || static_cast<size_t>(bytesSent) != reply.size()) {
            debug_printf("companion: discovery send failed: %d\n", errno);
            // Don't tear down on a single failed reply; the next request
            // may succeed. Tear down only on a hard error path.
            if (errno != EAGAIN && errno != EWOULDBLOCK) {
                disableDiscoverySocket("send failed");
                return;
            }
        }
    }
}

// Creates a socket of `type` (SOCK_STREAM or SOCK_DGRAM), sets
// SO_REUSEADDR and non-blocking, parses `host` as IPv4, and binds to
// `host:port`. On any failure logs with `label` as a prefix, closes the
// fd, and returns -1. On success returns the bound fd; the caller is
// responsible for `listen` (TCP) and closing the fd on shutdown.
int bindIPv4Socket(int type, const std::string& host, int port, const char* label)
{
    int fd = socket(AF_INET, type, 0);
    if (fd < 0) {
        debug_printf("companion: %s socket() failed: %d\n", label, errno);
        return -1;
    }

    int yes = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) < 0) {
        debug_printf("companion: %s setsockopt SO_REUSEADDR failed: %d\n", label, errno);
        close(fd);
        return -1;
    }

    if (!setNonBlocking(fd)) {
        debug_printf("companion: %s set non-blocking failed: %d\n", label, errno);
        close(fd);
        return -1;
    }

    sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) {
        debug_printf("companion: %s bind parse failed: %s\n", label, host.c_str());
        close(fd);
        return -1;
    }

    if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        debug_printf("companion: %s bind %s:%d failed: %d\n", label, host.c_str(), port, errno);
        close(fd);
        return -1;
    }

    return fd;
}

// Bind a UDP listener on the same address:port as the TCP listener. TCP
// and UDP coexist on the same port number; the kernel routes by protocol.
// On any failure the TCP listener is left untouched; discovery is a
// non-essential feature.
void initDiscoverySocket()
{
    int fd = bindIPv4Socket(SOCK_DGRAM, gBindHost, kListenPort, "discovery");
    if (fd < 0) {
        return;
    }

    gDiscoveryFd = fd;
    debug_printf("companion: discovery enabled (bind=%s, port=%d)\n",
        gBindHost.c_str(), kListenPort);
}

} // namespace

// debug_register_env() is never called from anywhere in this engine's init
// path, so all debug_printf() calls are silently dropped. The companion
// server invokes it here so DEBUGACTIVE=log actually produces a debug.log
// during development. Remove once a global debug init path is in place.
void companionEnableDebugLog()
{
    static bool registered = false;
    if (registered) {
        return;
    }
    debug_register_env();
    registered = true;
}

bool companionServerInit()
{
    companionEnableDebugLog();
    companionResetItemCatalog();
    companionResetQuestCatalog();

    // Load `pipboy.msg` now, at a session boundary, rather than letting the
    // first quest sample do it on the engine's frame loop. `main_init_system`
    // calls us after `game_init`, so the message database is open by here.
    companionWarmQuestCatalog();

    clearConfigBuffers();

    if (!gconfig_file_loaded()) {
        debug_printf("companion: disabled (fallout.cfg missing or unreadable)\n");
        return true;
    }

    char* bindPtr = nullptr;
    if (!config_get_string(&game_config,
            GAME_CONFIG_COMPANION_KEY,
            GAME_CONFIG_COMPANION_BIND_KEY,
            &bindPtr)) {
        debug_printf("companion: disabled (missing companion_bind)\n");
        return true;
    }
    gBindHost = bindPtr;

    char* passwordPtr = nullptr;
    if (!config_get_string(&game_config,
            GAME_CONFIG_COMPANION_KEY,
            GAME_CONFIG_COMPANION_PASSWORD_KEY,
            &passwordPtr)) {
        debug_printf("companion: disabled (missing companion_password)\n");
        return true;
    }
    gPassword = passwordPtr;

    // Optional. Absence is not a failure: it disables transmission audio and
    // the client shows `NO RECORD AVAILABLE`, which is a supported state.
    char* transmissionDirPtr = nullptr;
    if (config_get_string(&game_config,
            GAME_CONFIG_COMPANION_KEY,
            GAME_CONFIG_COMPANION_TRANSMISSION_AUDIO_DIR_KEY,
            &transmissionDirPtr)
        && transmissionDirPtr != nullptr) {
        gTransmissionAudioDir = transmissionDirPtr;
    }

    int fd = bindIPv4Socket(SOCK_STREAM, gBindHost, kListenPort, "listener");
    if (fd < 0) {
        clearConfigBuffers();
        return true;
    }

    if (listen(fd, kListenBacklog) < 0) {
        debug_printf("companion: listen failed: %d\n", errno);
        close(fd);
        clearConfigBuffers();
        return true;
    }

    gListenerFd = fd;
    initDiscoverySocket();
    resetConnectionState();
    debug_printf("companion: enabled (bind=%s, port=%d)\n", gBindHost.c_str(), kListenPort);

    if (!gIdleHookInstalled) {
        gOriginalIdleFunc = get_idle_func();
        set_idle_func(companionIdleHook);
        gIdleHookInstalled = true;
    }

    return true;
}

void companionServerExit()
{
    if (gIdleHookInstalled) {
        set_idle_func(gOriginalIdleFunc);
        gOriginalIdleFunc = nullptr;
        gIdleHookInstalled = false;
    }

    closeConnection();
    if (gDiscoveryFd >= 0) {
        debug_printf("companion: discovery closed\n");
    }
    closeFd(&gDiscoveryFd);
    closeFd(&gListenerFd);
    companionResetItemCatalog();
    companionResetQuestCatalog();
    clearConfigBuffers();
}

void companionServerTick(unsigned int now)
{
    if (gListenerFd < 0) {
        return;
    }

    handleDiscoveryRequests();

    acceptPendingClients();
    if (!hasClient()) {
        return;
    }

    readFromClient();
    if (!hasClient()) {
        return;
    }

    sampleReadyClient(now);
    if (!hasClient()) {
        return;
    }

    flushOutbound();
}

bool companionServerIsActive()
{
    return gListenerFd >= 0;
}

#else // _WIN32

bool companionServerInit()
{
    return true;
}

void companionServerExit()
{
}

void companionServerTick(unsigned int now)
{
    (void)now;
}

bool companionServerIsActive()
{
    return false;
}

#endif

} // namespace fallout
