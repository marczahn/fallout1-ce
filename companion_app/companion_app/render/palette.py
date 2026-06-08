"""Monochrome-green Pip-Boy palette (M2 Resolved Decision 4).

Three colors. No theme abstraction, no aliases. Future warning/critical
states land with their consumers, not speculatively.
"""
from __future__ import annotations

BACKGROUND: tuple[int, int, int] = (0, 0, 0)
FOREGROUND: tuple[int, int, int] = (51, 255, 102)
DIM: tuple[int, int, int] = (26, 160, 51)
