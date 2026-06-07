"""Newline-delimited JSON framing helpers (M3-T2).

Pure functions with no socket I/O or side effects.
"""
from __future__ import annotations

import json
from typing import Any


def encode_line(obj: dict[str, Any]) -> bytes:
    """Serialize `obj` to compact JSON and append ``\\n``.

    Uses ``separators=(",", ":")`` and ``ensure_ascii=True`` to match
    the server's encoding.
    """
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=True)
    return (text + "\n").encode("utf-8")


def read_line(buffer: bytearray) -> tuple[dict[str, Any] | None, bytearray]:
    """Extract one newline-terminated JSON line from *buffer*.

    Args:
        buffer: accumulated bytes from the socket.

    Returns:
        ``(parsed_dict, remainder)`` if a complete line is found, or
        ``(None, buffer)`` if no ``\\n`` is present.
    """
    idx = buffer.find(b"\n")
    if idx == -1:
        return None, buffer

    line_bytes = buffer[:idx]
    remainder = buffer[idx + 1 :]

    try:
        obj = json.loads(line_bytes.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        obj = None

    if not isinstance(obj, dict):
        obj = None

    return obj, remainder
