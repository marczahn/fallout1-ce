"""Envelope -> bar heights. Pure, pygame-free, no audio device.

The equalizer is driven by an amplitude envelope baked offline alongside
each recording, not by analysing the audio at runtime. The Raspberry Pi
does no DSP: it indexes a byte array. See the TASK-024 asset-contract
decision for the envelope's format and the audio-over-video decision for
why every aesthetic in this feature is baked rather than computed.
"""
from __future__ import annotations

# Envelope samples are unsigned bytes.
_MAX_SAMPLE: int = 255


def frame_index(position_ms: int, frame_ms: int, frames: int) -> int:
    """Envelope frame for a playback position, clamped into range.

    ``position_ms`` is the *tracked* position, not
    ``pygame.mixer.music.get_pos()`` — that reports time elapsed since
    ``play()`` and ignores ``set_pos()`` jumps, so indexing by it would
    desynchronise the bars from the audio after the first seek.
    """
    if frames <= 0 or frame_ms <= 0:
        return 0
    if position_ms <= 0:
        return 0
    index = position_ms // frame_ms
    if index >= frames:
        return frames - 1
    return int(index)


def bar_levels(
    envelope: bytes,
    bands: int,
    frames: int,
    frame_ms: int,
    position_ms: int,
) -> list[float]:
    """Normalised 0.0..1.0 level per band at ``position_ms``.

    Returns a list of exactly ``bands`` entries, or an empty list when the
    envelope cannot describe one — a malformed envelope produces no bars
    rather than a partial row or an exception, because this runs inside the
    frame loop.
    """
    if bands <= 0 or frames <= 0 or frame_ms <= 0:
        return []
    if len(envelope) < bands * frames:
        return []

    start = frame_index(position_ms, frame_ms, frames) * bands
    return [envelope[start + band] / _MAX_SAMPLE for band in range(bands)]


def silent_levels(bands: int) -> list[float]:
    """All-zero levels, for the paused and stopped states."""
    if bands <= 0:
        return []
    return [0.0] * bands
