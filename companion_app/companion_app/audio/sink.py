"""Mixer lifecycle and buffer playback for transmission audio.

Purpose-built for one recording at a time, played from memory. The engine
decodes each cutscene out of ``MASTER.DAT``, degrades it into the radio
aesthetic, and streams raw PCM; **nothing is written to disk by either
process**, which is why this plays a ``Sound`` built over a buffer rather
than loading a file through ``pygame.mixer.music``.

Three constraints inherited from cancelled TASK-020 still bind, because they
are true of *any* audio layer in this app:

* this module is the **sole owner** of mixer initialization -- nothing else
  may call ``pygame.mixer.init()`` behind its back;
* with the mixer down, every call is a no-op rather than an exception
  (:class:`NullAudioSink`);
* a packaged asset extension needs a ``pyproject.toml`` ``package-data``
  pattern. Audio arrives over the wire at runtime, so none is needed here --
  noted so the next asset does not rediscover the trap.

**The mixer is initialised at the PCM's own format**, 8 kHz mono 16-bit.
``pygame.mixer.Sound(buffer=...)`` interprets a buffer in the *mixer's*
format, so matching them is what makes a byte slice a valid seek. This is
legitimate only because transmissions are the app's **only** audio; if the
app ever gains other sounds, revisit -- the alternative is initialising
higher and upsampling once on receipt.

**Taking that format requires tearing the mixer down first, and skipping
that step is audible.** ``pygame.init()`` initialises *every* pygame module,
the mixer included, at its own defaults of 44,100 Hz stereo -- and this app
calls it while loading config (``config.py:388``), long before any sink
exists. A later ``mixer.init()`` with different arguments is then a **silent
no-op**: it returns cleanly and changes nothing. 8 kHz mono PCM read as
44.1 kHz stereo plays at ``44100/8000 * 2`` = **11.03x speed**, which is what
it sounds like -- not a subtle pitch error, a chipmunk. So ``create_sink``
calls ``mixer.quit()`` first and then **verifies** ``get_init()`` rather than
trusting it.

**Position is tracked from a monotonic clock, and that is simpler than what
this file used to do.** A seek builds a *fresh* ``Sound`` from a tail slice,
which restarts at zero, so no device-reported position survives one. The old
file-backed sink had to correct for ``mixer.music.get_pos()`` counting
straight through a ``set_pos()``; none of that arithmetic is needed now.
Position is ``seek_base_ms + elapsed since the last play``, frozen while
paused.
"""
from __future__ import annotations

import time
from typing import Protocol

from companion_app.state.models import TRANSMISSION_BYTES_PER_SECOND, TRANSMISSION_SAMPLE_RATE


def byte_offset(position_ms: int) -> int:
    """Byte offset of a playback position, aligned to a 16-bit frame.

    The alignment step is defence in depth and this docstring is the place to
    be honest about that: with integer millisecond targets and 16 bytes per
    millisecond, ``position_ms * 16000 // 1000`` is always ``position_ms * 16``
    and therefore always even. The guard exists because an odd offset shifts
    every following sample by one byte -- silent, and it sounds like static --
    and because ``TRANSMISSION_BYTES_PER_SECOND`` is exactly the kind of
    constant that changes later.
    """
    if position_ms <= 0:
        return 0
    offset = position_ms * TRANSMISSION_BYTES_PER_SECOND // 1000
    return offset - (offset % 2)


class AudioSink(Protocol):
    """What the playback controller depends on."""

    def play(self, pcm: bytes, duration_ms: int) -> None: ...

    def toggle_pause(self) -> None: ...

    def seek_by(self, delta_ms: int) -> None: ...

    def stop(self) -> None: ...

    def tick(self) -> None: ...

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

    def play(self, pcm: bytes, duration_ms: int) -> None:
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


class BufferAudioSink:
    """Plays one degraded PCM buffer at a time via ``pygame.mixer.Sound``."""

    def __init__(self, clock=time.monotonic) -> None:
        import pygame

        self._pygame = pygame
        # Injectable so tests can drive position without sleeping.
        self._clock = clock

        self._pcm = b""
        self._duration_ms = 0
        self._seek_base_ms = 0
        self._started_at = 0.0
        self._paused_at = 0.0
        self._paused = False
        self._active = False
        # A `Sound` must be kept alive for the duration of playback: pygame
        # does not hold a reference for you, and a collected one stops
        # mid-track.
        self._sound = None
        self._channel = None

    # -- state ---------------------------------------------------------

    @property
    def is_playing(self) -> bool:
        return self._active

    @property
    def is_paused(self) -> bool:
        return self._active and self._paused

    @property
    def position_ms(self) -> int:
        if not self._active:
            return 0
        now = self._paused_at if self._paused else self._clock()
        # `round`, not `int`. Truncation systematically under-reports, and
        # the pause/resume path accumulates float error: a 500ms play, a
        # 2000ms pause and a 300ms resume lands at 799.999... which `int`
        # reports as 799ms. One millisecond does not matter on its own; a
        # bias that grows with every pause does.
        elapsed_ms = round((now - self._started_at) * 1000)
        if elapsed_ms < 0:
            elapsed_ms = 0
        position = self._seek_base_ms + elapsed_ms
        if self._duration_ms and position > self._duration_ms:
            return self._duration_ms
        return position

    # -- transport -----------------------------------------------------

    def play(self, pcm: bytes, duration_ms: int) -> None:
        self.stop()
        if not pcm:
            return
        self._pcm = pcm
        self._duration_ms = max(0, duration_ms)
        if not self._start_at(0):
            self._pcm = b""
            self._duration_ms = 0

    def _start_at(self, position_ms: int) -> bool:
        """Build and play a Sound over the tail of the buffer from `position_ms`."""
        offset = byte_offset(position_ms)
        if offset >= len(self._pcm):
            return False

        try:
            sound = self._pygame.mixer.Sound(buffer=self._pcm[offset:])
            channel = sound.play()
        except Exception:
            # Never raise into the frame loop. A failed mixer call means
            # silence, not a crash.
            self._active = False
            self._sound = None
            self._channel = None
            return False

        self._sound = sound
        self._channel = channel
        self._seek_base_ms = position_ms
        self._started_at = self._clock()
        self._paused_at = 0.0
        self._paused = False
        self._active = True
        return True

    def toggle_pause(self) -> None:
        if not self._active or self._channel is None:
            return
        try:
            if self._paused:
                self._channel.unpause()
                # Resume the clock from where it stopped.
                self._started_at += self._clock() - self._paused_at
                self._paused = False
            else:
                self._channel.pause()
                self._paused_at = self._clock()
                self._paused = True
        except Exception:
            self.stop()

    def seek_by(self, delta_ms: int) -> None:
        """Seek relative to the tracked position, clamped at both ends.

        Rewinding past the start clamps to 0. Fast-forwarding to or past the
        end **stops**, matching the behaviour the screen has always had.

        The bound is the PCM's own duration, NOT the envelope's. They differ
        by up to one 50ms frame, and a target inside that gap would pass a
        check written against the envelope and then slice an empty buffer --
        playback would stop with the transport still showing time remaining.
        """
        if not self._active:
            return

        was_paused = self._paused
        target = self.position_ms + delta_ms
        if target < 0:
            target = 0

        pcm_duration_ms = len(self._pcm) * 1000 // TRANSMISSION_BYTES_PER_SECOND
        if target >= pcm_duration_ms:
            self.stop()
            return

        pcm = self._pcm
        duration_ms = self._duration_ms
        self._stop_device()
        self._pcm = pcm
        self._duration_ms = duration_ms

        if not self._start_at(target):
            self.stop()
            return

        if was_paused:
            try:
                self._channel.pause()
                self._paused_at = self._clock()
                self._paused = True
            except Exception:
                self.stop()

    def _stop_device(self) -> None:
        if self._channel is not None:
            try:
                self._channel.stop()
            except Exception:
                pass
        self._sound = None
        self._channel = None

    def stop(self) -> None:
        self._stop_device()
        self._pcm = b""
        self._active = False
        self._paused = False
        self._seek_base_ms = 0
        self._started_at = 0.0
        self._paused_at = 0.0
        self._duration_ms = 0

    def tick(self) -> None:
        """Notice a track that ran to its end.

        Called once per frame. Without this the screen would keep drawing
        `PLAYING` after the audio finished.
        """
        if not self._active or self._paused or self._channel is None:
            return
        try:
            busy = self._channel.get_busy()
        except Exception:
            self.stop()
            return
        if not busy:
            self.stop()


REQUIRED_MIXER_FORMAT = (TRANSMISSION_SAMPLE_RATE, -16, 1)


def create_sink(enabled: bool = True, pygame_module=None) -> AudioSink:
    """Initialize the mixer at the PCM's format and return a sink.

    Any failure -- disabled, no device, init error, or a mixer that will not
    take the required format -- yields :class:`NullAudioSink`, so callers
    never branch on availability.

    **The mixer is torn down before it is initialised, and the result is
    checked.** ``pygame.init()`` has usually already brought the mixer up at
    44.1 kHz stereo, and a second ``mixer.init()`` with other arguments is a
    silent no-op -- so without the ``quit()`` this function appears to
    succeed and every transmission plays 11x too fast. Verifying
    ``get_init()`` afterwards means a mixer that cannot give us this format
    degrades to **silence**, which is diagnosable, rather than to gibberish,
    which sounds like a decoder bug and is not one.

    ``pygame_module`` exists for tests; production passes nothing.
    """
    if not enabled:
        return NullAudioSink()

    try:
        if pygame_module is None:
            import pygame as pygame_module

        # Release whatever `pygame.init()` opened, so our format is honoured
        # rather than silently ignored.
        pygame_module.mixer.quit()
        pygame_module.mixer.init(
            frequency=TRANSMISSION_SAMPLE_RATE,
            size=-16,
            channels=1,
        )
    except Exception:
        return NullAudioSink()

    actual = pygame_module.mixer.get_init()
    if actual != REQUIRED_MIXER_FORMAT:
        # Silence beats 11x-speed audio: one is obviously broken, the other
        # sounds like a decode bug and would send the next person into the
        # DPCM reader.
        return NullAudioSink()

    return BufferAudioSink()
