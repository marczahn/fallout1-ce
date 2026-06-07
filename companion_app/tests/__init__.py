"""Shared test bootstrap.

Force pygame's dummy video/audio drivers before any test module
imports pygame. Importing the `tests` package (which `unittest
discover` does for every test file when `__init__.py` is present) is
sufficient to apply these environment variables.
"""
from __future__ import annotations

import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
