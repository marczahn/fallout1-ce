"""Page enum and page dispatch registry (UI refactoring).

Pages are the top-level navigation concept — they replace the old
``Section`` enum. Each page maps to one of the four hardware section
buttons (1=STATUS, 2=DATA, 3=INVENTORY, 4=MAP).
"""
from __future__ import annotations

from enum import Enum


class Page(Enum):
    STATUS = 1
    DATA = 2
    INVENTORY = 3
    MAP = 4
