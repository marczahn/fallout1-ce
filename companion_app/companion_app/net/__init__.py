"""Companion app networking (M3).

Non-blocking TCP client that connects to the companion server,
completes the auth + hello/world handshake, ingests snapshots and
updates, and auto-reconnects on disconnect.
"""
from companion_app.net.client import NetworkClient

__all__ = [
    "NetworkClient",
]
