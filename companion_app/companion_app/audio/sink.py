"""Mixer lifecycle and streaming playback for transmission audio.

Purpose-built for one long, exclusive, interruptible recording at a time.
This is deliberately **not** the design cancelled TASK-020 carried: no
reserved channels, no ambience bed, no RAM-resident ``Sound`` bank. A
narration streams through ``pygame.mixer.music``, which has its own
channel outside the mixer's eight and does not contend with anything.

Three constraints inherited from TASK-020 still bind, because they are
true of *any* audio layer in this app:

* this module is the **sole owner** of mixer initialization -- nothing
  else may call ``pygame.mixer.init()`` behind its back;
* with the mixer down, every call is a no-op rather than an exception
  (:class:`NullAudioSink`);
* a packaged asset extension needs a ``pyproject.toml`` ``package-data``
  pattern. Narration is fetched to scratch at runtime, so none is needed
  here -- noted so the next asset does not rediscover the trap.

**Position is tracked manually, and the arithmetic is subtler than it
looks.** ``pygame.mixer.music.get_pos()`` reports milliseconds since
``play()`` and keeps counting straight through a ``set_pos()`` -- it does
not restart at the seek target *or* at zero. So the position is

    seek_target + (get_pos() - get_pos_at_the_moment_of_the_seek)

Measured, not assumed: play, wait 0.5s -> ``get_pos()`` 525; ``set_pos(3.0)``;
wait 0.5s -> ``get_pos()`` 1042. The naive ``seek_target + get_pos()``
would report 4042ms for a track that is 3.5s in, drifting further with
every seek.

**Seeks are clamped before they reach SDL.** ``set_pos()`` past the end of
a track raises ``pygame.error("Position not implemented for music type")``
-- a message that names the wrong cause; on a 7.10s file ``set_pos(3.0)``
succeeds and ``set_pos(10.0)`` raises. Fast-forwarding past the end is
therefore a stop, never a seek.
"""
from __future__ import annotations

from typing import Protocol


class AudioSink(Protocol):
    """What the playback controller depends on."""

    def play(self, path: str, duration_ms: int) -> None: ...

    def toggle_pause(self) -> None: ...

    def seek_by(self, delta_ms: int) -> None: ...

    def stop(self) -> None: ...

    @property
    def is_playing(self) -> bool: ...

    @property
    def is_paused(self) -> bool: ...

    @property
    def position_ms(self) -> int: ...


class NullAudioSink:
    """Every call a no-op. Used when audio is disabled or unavailable.

    Returning a null object rather than ``None`` keeps the controller free
    of ``if sink is not None`` at every call site, and means a device with
    no working audio degrades to silence instead of to a crash.
    """

    def play(self, path: str, duration_ms: int) -> None:
        return None

    def toggle_pause(self) -> None:
        return None

    def seek_by(self, delta_ms: int) -> None:
        return None

    def stop(self) -> None:
        return None

    def tick(self) -> None:
        return None

    @property
    def is_playing(self) -> bool:
        return False

    @property
    def is_paused(self) -> bool:
        return False

    @property
    def position_ms(self) -> int:
        return 0


class MusicAudioSink:
    """Streams one narration at a time via ``pygame.mixer.music``."""

    def __init__(self) -> None:
        import pygame

        self._pygame = pygame
        self._duration_ms = 0
        # Position of the last seek, and the raw `get_pos()` reading taken
        # at that instant. Both are needed -- see the module docstring.
        self._seek_base_ms = 0
        self._seek_origin_ms = 0
        self._paused = False
        self._active = False

    # -- state ---------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        return self._active

    @property
    def is_paused(self) -> bool:
        return self._active and self._paused

    @property
    def position_ms(self) -> int:
        """Tracked position, clamped to the track.

        ``get_pos()`` returns -1 when nothing is loaded, and counts only
        time since ``play()`` -- hence ``_seek_base_ms``.
        """
        if not self._active:
            return 0
        elapsed = self._pygame.mixer.music.get_pos()
        if elapsed < 0:
            elapsed = 0
        since_seek = elapsed - self._seek_origin_ms
        if since_seek < 0:
            since_seek = 0
        position = self._seek_base_ms + since_seek
        if self._duration_ms and position > self._duration_ms:
            return self._duration_ms
        return position

    # -- transport -----------------------------------------------------

    def play(self, path: str, duration_ms: int) -> None:
        try:
            self._pygame.mixer.music.load(path)
            self._pygame.mixer.music.play()
        except self._pygame.error:
            self._active = False
            return
        self._duration_ms = max(0, duration_ms)
        self._seek_base_ms = 0
        self._seek_origin_ms = 0
        self._paused = False
        self._active = True

    def toggle_pause(self) -> None:
        if not self._active:
            return
        if self._paused:
            self._pygame.mixer.music.unpause()
            self._paused = False
        else:
            self._pygame.mixer.music.pause()
            self._paused = True

    def seek_by(self, delta_ms: int) -> None:
        """Seek relative to the tracked position, clamped at both ends.

        Rewinding past the start clamps to 0. Fast-forwarding past the end
        **stops** rather than seeking: passing an out-of-range target to
        ``set_pos()`` raises (see the module docstring).
        """
        if not self._active:
            return

        target = self.position_ms + delta_ms
        if target < 0:
            target = 0
        if self._duration_ms and target >= self._duration_ms:
            self.stop()
            return

        try:
            self._pygame.mixer.music.set_pos(target / 1000.0)
        except self._pygame.error:
            # Defence in depth: the clamp above should make this
            # unreachable, but a mis-declared duration must not crash the
            # frame loop.
            self.stop()
            return
        self._seek_base_ms = target
        origin = self._pygame.mixer.music.get_pos()
        self._seek_origin_ms = origin if origin > 0 else 0
        if self._paused:
            # `set_pos` resumes playback; keep the paused contract.
            self._pygame.mixer.music.pause()

    def stop(self) -> None:
        if not self._active:
            return
        try:
            self._pygame.mixer.music.stop()
        except self._pygame.error:
            pass
        self._active = False
        self._paused = False
        self._seek_base_ms = 0
        self._seek_origin_ms = 0
        self._duration_ms = 0

    def tick(self) -> None:
        """Notice a track that ran to its end.

        Called once per frame. Without this the screen would keep drawing
        `PLAYING` after the audio finished.
        """
        if not self._active or self._paused:
            return
        if not self._pygame.mixer.music.get_busy():
            self.stop()


def create_sink(enabled: bool = True) -> AudioSink:
    """Initialize the mixer and return a sink, or a null sink.

    This is the ONLY place ``pygame.mixer.init()`` is called. Any failure
    -- disabled, no device, init error -- yields :class:`NullAudioSink`,
    so callers never branch on availability.
    """
    if not enabled:
        return NullAudioSink()

    try:
        import pygame

        pygame.mixer.init()
    except Exception:
        return NullAudioSink()

    return MusicAudioSink()
