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

#include "companion_protocol.h"
#include "companion_snapshot.h"
#include "platform_compat.h"
#include "plib/gnw/debug.h"

#if !defined(_WIN32)
#include "plib/gnw/input.h"
#endif

namespace fallout {

#if !defined(_WIN32)

namespace {

constexpr int kListenPort = 28080;
constexpr const char* kListenHost = "0.0.0.0";
constexpr int kListenBacklog = 1;

constexpr size_t kInboundBufferSize = 4096;
constexpr size_t kOutboundCap = 256 * 1024;
constexpr unsigned int kSampleIntervalMs = 500;

enum class ServerState {
    Disabled,
    Listening,
};

enum class ClientState {
    AwaitingHello,
    Ready,
};

struct CompanionConnection {
    int fd = -1;
    ClientState state = ClientState::AwaitingHello;
    unsigned int nextSeq = 1;
    unsigned int lastSampleMs = 0;
    bool playerWasAvailable = false;
    CompanionPlayerSnapshot lastSentPlayer = {};
    char inbound[kInboundBufferSize] = {};
    size_t inboundLen = 0;
    std::string outbound;
};

ServerState gServerState = ServerState::Disabled;
int gListenerFd = -1;

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

void resetConnectionState()
{
    gConnection.state = ClientState::AwaitingHello;
    gConnection.nextSeq = 1;
    gConnection.lastSampleMs = 0;
    gConnection.playerWasAvailable = false;
    gConnection.lastSentPlayer.hp = 0;
    gConnection.lastSentPlayer.maxHp = 0;
    gConnection.inboundLen = 0;
    gConnection.outbound.clear();
}

void closeConnection()
{
    closeFd(&(gConnection.fd));
    resetConnectionState();
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
    gConnection.playerWasAvailable = snapshot.hasPlayer;
    gConnection.lastSentPlayer = snapshot.player;
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

void queueSnapshotMessage()
{
    CompanionSnapshot snapshot = companionCollectSnapshot();
    if (!queueMessage(companionBuildSnapshot(nextSequence(), snapshot))) {
        return;
    }

    primeLastSentState(snapshot);
    debug_printf("companion: snapshot sent\n");
}

void queuePlayerUnavailableMessage()
{
    if (!queueMessage(companionBuildPlayerUnavailable(nextSequence()))) {
        return;
    }

    debug_printf("companion: player_unavailable sent\n");
}

void queuePlayerUpdateIfNeeded(const CompanionSnapshot& snapshot)
{
    const CompanionPlayerSnapshot& lastSent = gConnection.lastSentPlayer;
    if (snapshot.player.hp == lastSent.hp
        && snapshot.player.maxHp == lastSent.maxHp) {
        return;
    }

    if (!queueMessage(companionBuildPlayerUpdate(
            nextSequence(),
            snapshot.hasPlayer,
            snapshot.player,
            lastSent))) {
        return;
    }

    gConnection.lastSentPlayer = snapshot.player;
    debug_printf("companion: update sent\n");
}

void handleClientMessage(CompanionClientMessage message)
{
    if (gConnection.state == ClientState::AwaitingHello) {
        if (message != CompanionClientMessage::Hello) {
            disconnectClient("non-hello first message");
            return;
        }

        queueWorldMessage();
        return;
    }

    if (message == CompanionClientMessage::GetSnapshot) {
        queueSnapshotMessage();
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
        CompanionClientMessage message = companionParseClientMessage(gConnection.inbound, lineLength);
        if (message == CompanionClientMessage::Invalid) {
            disconnectClient("invalid message");
            return;
        }

        size_t consumed = lineLength + 1;
        memmove(gConnection.inbound,
            gConnection.inbound + consumed,
            gConnection.inboundLen - consumed);
        gConnection.inboundLen -= consumed;

        handleClientMessage(message);
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

    CompanionSnapshot snapshot = companionCollectSnapshot();
    if (snapshot.hasPlayer != gConnection.playerWasAvailable) {
        gConnection.playerWasAvailable = snapshot.hasPlayer;
        if (!snapshot.hasPlayer) {
            queuePlayerUnavailableMessage();
        }
        return;
    }

    if (snapshot.hasPlayer) {
        queuePlayerUpdateIfNeeded(snapshot);
    }
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

    int fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0) {
        debug_printf("companion: socket() failed: %d\n", errno);
        gServerState = ServerState::Disabled;
        return true;
    }

    int yes = 1;
    if (setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes)) < 0) {
        debug_printf("companion: setsockopt SO_REUSEADDR failed: %d\n", errno);
        close(fd);
        gServerState = ServerState::Disabled;
        return true;
    }

    if (!setNonBlocking(fd)) {
        debug_printf("companion: set non-blocking failed: %d\n", errno);
        close(fd);
        gServerState = ServerState::Disabled;
        return true;
    }

    sockaddr_in addr;
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(kListenPort);
    if (inet_pton(AF_INET, kListenHost, &addr.sin_addr) != 1) {
        debug_printf("companion: inet_pton failed\n");
        close(fd);
        gServerState = ServerState::Disabled;
        return true;
    }

    if (bind(fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
        debug_printf("companion: bind %s:%d failed: %d\n", kListenHost, kListenPort, errno);
        close(fd);
        gServerState = ServerState::Disabled;
        return true;
    }

    if (listen(fd, kListenBacklog) < 0) {
        debug_printf("companion: listen failed: %d\n", errno);
        close(fd);
        gServerState = ServerState::Disabled;
        return true;
    }

    gListenerFd = fd;
    resetConnectionState();
    gServerState = ServerState::Listening;
    debug_printf("companion: listening on %s:%d\n", kListenHost, kListenPort);

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
    closeFd(&gListenerFd);
    gServerState = ServerState::Disabled;
}

void companionServerTick(unsigned int now)
{
    if (gServerState == ServerState::Disabled) {
        return;
    }

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

#endif

} // namespace fallout
