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

#include <string>
#include <string_view>

#include "companion_item_catalog.h"
#include "companion_protocol.h"
#include "companion_snapshot.h"
#include "game/gconfig.h"
#include "platform_compat.h"
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

void queuePlayerUnavailableMessage()
{
    if (!queueMessage(companionBuildPlayerUnavailable(nextSequence()))) {
        return;
    }

    debug_printf("companion: player_unavailable sent\n");
}

bool vitalsDiffer(const CompanionPlayerVitals& a, const CompanionPlayerVitals& b)
{
    return a.hp != b.hp || a.maxHp != b.maxHp;
}

bool localLocationDiffer(const CompanionPlayerLocalLocation& a, const CompanionPlayerLocalLocation& b)
{
    return a.tile != b.tile
        || a.elevation != b.elevation
        || a.map != b.map
        || strcmp(a.location, b.location) != 0
        || strcmp(a.locationId, b.locationId) != 0;
}

bool worldLocationDiffer(const CompanionPlayerWorldLocation& a, const CompanionPlayerWorldLocation& b)
{
    return a.x != b.x || a.y != b.y;
}

bool inventoryItemDiffer(const CompanionInventoryItem& a, const CompanionInventoryItem& b)
{
    return a.pid != b.pid
        || a.type != b.type
        || a.count != b.count
        || a.slot != b.slot
        || strcmp(a.protoId, b.protoId) != 0
        || strcmp(a.name, b.name) != 0;
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

    if (request.name == "get_snapshot") {
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

    rejectCommand(request.id, request.name, "unknown_command");
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
            // Absent -> present. Prime `lastSent` to the current
            // sample so the next tick's diff is empty; the client is
            // expected to call `get_snapshot` to learn the state. We
            // do not force-emit here, because the client just got the
            // `world` handshake and has not asked for data yet.
            primeLastSentState(current);
        } else {
            // Present -> absent. Emit the one-shot transition and
            // clear the baseline so the next present sample is
            // treated as fresh.
            gConnection.lastSentPrimed = false;
            queuePlayerUnavailableMessage();
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
            debug_printf("companion: update sent (player.local_location)\n");
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
            debug_printf("companion: update sent (player.world_location)\n");
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
