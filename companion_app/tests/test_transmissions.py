"""TASK-024 ARCHIVES/TRANSMISSIONS: projection, audio, controller, renderer.

Follows the project's habits: select state explicitly rather than driving
the UI to reach it, keep the pure layers pygame-free, and assert pixels
only where rendering is the thing under test.
"""
from __future__ import annotations

import hashlib
import os
import unittest
from dataclasses import replace

import pygame

from companion_app.audio import equalizer
from companion_app.audio.sink import (
    REQUIRED_MIXER_FORMAT,
    BufferAudioSink,
    NullAudioSink,
    byte_offset,
    create_sink,
)
from companion_app.input.events import (
    ConfirmEvent,
    EncoderLeftEvent,
    EncoderRightEvent,
)
from companion_app.state import (
    AppState,
    ConnectionState,
    Transmission,
    TransmissionAudioState,
    TransmissionRecording,
    TransmissionSyncStatus,
)
from companion_app.ui import transmission_list, transmission_playback, sections
from companion_app.render import palette
from companion_app.ui.pages import archives
from companion_app.ui.scroll_list import ListCursor
from companion_app.ui.sections import (
    ARCHIVES_HOLODISKS,
    ARCHIVES_TRANSMISSIONS,
    ARCHIVES_QUESTS,
    Page,
    SubSectionFocus,
)


def _envelope(bands: int, frames: int) -> bytes:
    return bytes([(i * 17) % 256 for i in range(bands * frames)])


def _state(indices=(3, 4, 7), *, recordings=(), status=TransmissionSyncStatus.READY):
    state = AppState()
    state.connection = ConnectionState.READY
    state.player.transmissions = [Transmission(index=i, title=f"DISK {i}") for i in indices]
    state.transmission_audio = TransmissionAudioState(status=status)
    for index in recordings:
        state.transmission_audio.recordings[index] = TransmissionRecording(
            index=index,
            # 16,000 bytes = 1000ms at 8kHz mono 16-bit, matching the
            # 20-frame/50ms envelope below. The two durations must agree in a
            # fixture, or tests silently assert against the wrong one.
            pcm=b"\x00\x01" * 8000,
            bands=16,
            frames=20,
            frame_ms=50,
            envelope=_envelope(16, 20),
        )
    return state


def _ui(selected=ARCHIVES_TRANSMISSIONS, *, activated=False, drill=""):
    ui = sections.default_sections_ui()
    seg = sections.for_page(ui, Page.ARCHIVES)
    while seg.selected_key != selected:
        seg = sections.cycle_next(seg)
    ui = sections.with_page(ui, Page.ARCHIVES, seg)
    return replace(ui, activated=activated, transmission_drill_key=drill)


class TransmissionListProjectionTests(unittest.TestCase):
    def test_rows_are_in_engine_table_order(self) -> None:
        # Real GameMovie indices: the listable range is 3..13, so the two
        # logos and the intro (0..2) never appear here.
        state = _state(indices=(7, 3, 5))
        rows = transmission_list.project(state.player.transmissions, state.transmission_audio)
        self.assertEqual([r.index for r in rows], [3, 5, 7])

    def test_key_round_trips(self) -> None:
        # Spans the real listable range MOVIE_VEXPLD..MOVIE_COUNT-1.
        for index in (3, 8, 13):
            self.assertEqual(
                transmission_list.transmission_index_from_key(transmission_list.transmission_key(index)), index
            )

    def test_foreign_key_does_not_decode(self) -> None:
        # A quest level-1 key must never resolve as a transmission.
        self.assertIsNone(transmission_list.transmission_index_from_key("L3"))
        self.assertIsNone(transmission_list.transmission_index_from_key(""))

    def test_missing_title_is_visible_not_dropped(self) -> None:
        state = _state(indices=(6,))
        state.player.transmissions = [Transmission(index=6, title="")]
        rows = transmission_list.project(state.player.transmissions, state.transmission_audio)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].title, transmission_list.NO_TITLE_LABEL)

    def test_listing_never_depends_on_whether_audio_arrived(self) -> None:
        """The core rule: availability lists, bakedness only marks."""
        without = _state(indices=(3, 4), recordings=())
        with_audio = _state(indices=(3, 4), recordings=(4,))
        self.assertEqual(
            [r.index for r in transmission_list.project(without.player.transmissions, without.transmission_audio)],
            [r.index for r in transmission_list.project(with_audio.player.transmissions, with_audio.transmission_audio)],
        )
        playable = transmission_list.project(with_audio.player.transmissions, with_audio.transmission_audio)
        self.assertEqual([r.playable for r in playable], [False, True])

    def test_unavailable_text_distinguishes_only_a_live_sync(self) -> None:
        for status in (TransmissionSyncStatus.IDLE, TransmissionSyncStatus.FETCHING):
            self.assertEqual(
                transmission_list.unavailable_text(TransmissionAudioState(status=status)),
                transmission_list.SYNCING_TEXT,
            )
        for status in (TransmissionSyncStatus.READY, TransmissionSyncStatus.UNAVAILABLE):
            self.assertEqual(
                transmission_list.unavailable_text(TransmissionAudioState(status=status)),
                transmission_list.NO_RECORD_TEXT,
            )


class EqualizerTests(unittest.TestCase):
    def test_frame_index_tracks_position(self) -> None:
        self.assertEqual(equalizer.frame_index(0, 50, 20), 0)
        self.assertEqual(equalizer.frame_index(125, 50, 20), 2)

    def test_frame_index_clamps_both_ends(self) -> None:
        self.assertEqual(equalizer.frame_index(-500, 50, 20), 0)
        self.assertEqual(equalizer.frame_index(10_000, 50, 20), 19)

    def test_bars_follow_a_seek(self) -> None:
        """Criterion 11: the envelope is indexed by *position*, not by
        elapsed playback, so a seek moves the bars."""
        env = _envelope(4, 10)
        early = equalizer.bar_levels(env, 4, 10, 50, position_ms=0)
        later = equalizer.bar_levels(env, 4, 10, 50, position_ms=400)
        self.assertEqual(len(early), 4)
        self.assertNotEqual(early, later)

    def test_malformed_envelope_yields_no_bars_rather_than_raising(self) -> None:
        self.assertEqual(equalizer.bar_levels(b"\x00\x01", 16, 20, 50, 0), [])
        self.assertEqual(equalizer.bar_levels(b"", 0, 0, 0, 0), [])

    def test_silent_levels_are_all_zero(self) -> None:
        self.assertEqual(equalizer.silent_levels(3), [0.0, 0.0, 0.0])


class _FakePygameError(Exception):
    pass


class _FakeChannel:
    def __init__(self) -> None:
        self.busy = True
        self.calls: list[str] = []

    def pause(self) -> None:
        self.calls.append("pause")

    def unpause(self) -> None:
        self.calls.append("unpause")

    def stop(self) -> None:
        self.busy = False
        self.calls.append("stop")

    def get_busy(self) -> bool:
        return self.busy


class _FakeSound:
    def __init__(self, buffer: bytes, owner: "_FakeMixer") -> None:
        self.buffer = bytes(buffer)
        self._owner = owner

    def play(self):
        channel = _FakeChannel()
        self._owner.channels.append(channel)
        return channel


class _FakeMixer:
    def __init__(self) -> None:
        self.buffers: list[bytes] = []
        self.channels: list[_FakeChannel] = []
        self.raise_on_sound = False

    def Sound(self, buffer=None):  # noqa: N802 - mirrors pygame's name
        if self.raise_on_sound:
            raise _FakePygameError("mixer not initialized")
        self.buffers.append(bytes(buffer))
        return _FakeSound(buffer, self)


class _FakePygame:
    error = _FakePygameError

    def __init__(self) -> None:
        self.mixer = _FakeMixer()


class _FakeClock:
    """Monotonic clock the tests drive by hand, in seconds."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance_ms(self, ms: int) -> None:
        self.now += ms / 1000.0


def _buffer_sink():
    """A `BufferAudioSink` over a fake pygame and a hand-driven clock."""
    pygame = _FakePygame()
    clock = _FakeClock()
    sink = BufferAudioSink.__new__(BufferAudioSink)
    sink._pygame = pygame
    sink._clock = clock
    sink._pcm = b""
    sink._duration_ms = 0
    sink._seek_base_ms = 0
    sink._started_at = 0.0
    sink._paused_at = 0.0
    sink._paused = False
    sink._active = False
    sink._sound = None
    sink._channel = None
    return sink, pygame.mixer, clock


# 16 bytes per millisecond at 8kHz mono 16-bit.
def _pcm(duration_ms: int) -> bytes:
    return bytes(duration_ms * 16)


class ByteOffsetTests(unittest.TestCase):
    """`byte_offset` is tested directly, and here is why.

    The alignment guard cannot be reached through `seek_by`: with integer
    millisecond targets and 16 bytes per millisecond the offset is always
    `ms * 16`, always even. Driving it through the seek path would be a test
    that cannot fail - the pattern this suite has been bitten by three times.
    So the helper is exercised on its own, including inputs that would yield
    an odd offset if the rate ever changes.
    """

    def test_five_seconds_is_exactly_eighty_thousand_bytes(self) -> None:
        self.assertEqual(byte_offset(5000), 80_000)

    def test_offset_is_always_even(self) -> None:
        for ms in (0, 1, 7, 999, 5000, 10_943):
            self.assertEqual(byte_offset(ms) % 2, 0, f"odd offset for {ms}ms")

    def test_negative_and_zero_clamp_to_zero(self) -> None:
        self.assertEqual(byte_offset(0), 0)
        self.assertEqual(byte_offset(-5000), 0)


class _RealisticFakeMixer:
    """Reproduces the pygame behaviour that made every transmission play
    11x too fast.

    The trap is that ``mixer.init()`` is a **silent no-op when the mixer is
    already initialised** -- it returns cleanly and keeps the old format. And
    the mixer is nearly always already up, because ``pygame.init()``
    initialises every module including this one, at 44.1kHz stereo, and this
    app calls it while loading config (`config.py:388`).
    """

    DEFAULT = (44100, -16, 2)

    def __init__(self, *, already_initialised=True, refuse=None) -> None:
        self.format = self.DEFAULT if already_initialised else None
        self.refuse = refuse

    def quit(self) -> None:
        self.format = None

    def init(self, frequency=44100, size=-16, channels=2) -> None:
        if self.format is not None:
            return  # <-- the no-op
        self.format = self.refuse if self.refuse else (frequency, size, channels)

    def get_init(self):
        return self.format


class _FakePygameModule:
    def __init__(self, mixer) -> None:
        self.mixer = mixer


class _FixedPositionSink:
    """A sink that reports a position, for renderer tests."""

    def __init__(self, position_ms: int, *, playing=True, paused=False) -> None:
        self.position_ms = position_ms
        self.is_playing = playing
        self.is_paused = paused

    def play(self, pcm, duration_ms): pass
    def toggle_pause(self): pass
    def seek_by(self, delta_ms): pass
    def stop(self): pass
    def tick(self): pass


class TimebarTests(unittest.TestCase):
    """The transport had no visual feedback at all until this was added:
    pause and the 5-second seek worked, but nothing on screen moved, so the
    screen read as having no controls rather than no feedback."""

    def test_clock_is_floored_not_rounded(self) -> None:
        # A stopwatch never shows a second the audio has not reached.
        self.assertEqual(archives.format_clock(0), "0:00")
        self.assertEqual(archives.format_clock(999), "0:00")
        self.assertEqual(archives.format_clock(1000), "0:01")
        self.assertEqual(archives.format_clock(59_999), "0:59")
        self.assertEqual(archives.format_clock(60_000), "1:00")
        self.assertEqual(archives.format_clock(125_000), "2:05")

    def test_clock_clamps_negative_to_zero(self) -> None:
        self.assertEqual(archives.format_clock(-5000), "0:00")

    def test_the_fill_grows_with_position(self) -> None:
        """Pixel-counted, because the point of this feature is that the
        user can SEE the position move."""
        surface = pygame.Surface((240, 40))
        rect = pygame.Rect(0, 0, 240, 30)

        def lit(position_ms: int) -> int:
            surface.fill((0, 0, 0))
            archives._draw_timebar(surface, rect, position_ms, 10_000)
            return sum(
                1
                for x in range(surface.get_width())
                for y in range(surface.get_height())
                if surface.get_at((x, y))[:3] == palette.FOREGROUND
            )

        start, middle, end = lit(0), lit(5000), lit(10_000)
        self.assertLess(start, middle, "the bar did not advance")
        self.assertLess(middle, end, "the bar did not reach the end")

    def test_a_finished_track_fills_the_whole_track(self) -> None:
        surface = pygame.Surface((240, 40))
        archives._draw_timebar(surface, pygame.Rect(0, 0, 240, 30), 10_000, 10_000)
        row = archives._TIMEBAR_HEIGHT // 2
        self.assertEqual(surface.get_at((239, row))[:3], palette.FOREGROUND)

    def test_position_past_the_end_does_not_overflow_the_track(self) -> None:
        surface = pygame.Surface((240, 40))
        archives._draw_timebar(surface, pygame.Rect(0, 0, 240, 30), 99_000, 10_000)
        self.assertEqual(surface.get_at((239, 0))[:3], palette.FOREGROUND)

    def test_zero_duration_draws_a_track_but_no_fill(self) -> None:
        surface = pygame.Surface((240, 40))
        surface.fill((0, 0, 0))
        archives._draw_timebar(surface, pygame.Rect(0, 0, 240, 30), 0, 0)
        row = archives._TIMEBAR_HEIGHT // 2
        self.assertEqual(surface.get_at((0, row))[:3], palette.DIM, "no track drawn")

    def test_player_labels_duration_from_the_pcm_not_the_envelope(self) -> None:
        """Two recordings with the SAME envelope and DIFFERENT audio lengths.

        The envelope rounds up to a whole 50ms frame, so it is a different
        number from the PCM's duration and using it would leave the fill and
        the total short on every transmission. Asserting `format_clock` on
        both values would NOT catch that - it never touches the renderer -
        so this drives the real screen instead: same envelope means the same
        equalizer bars at the same position, therefore any pixel difference
        is the timebar reading a different duration. Render both and require
        them to differ.
        """
        def render(pcm_ms: int) -> bytes:
            state = _state(recordings=())
            state.transmission_audio.recordings[1] = TransmissionRecording(
                index=1,
                pcm=b"\x00" * (pcm_ms * 16),
                bands=16,
                frames=180,            # 180 * 50ms = 9,000ms for both
                frame_ms=50,
                envelope=_envelope(16, 180),
            )
            surface = pygame.Surface((480, 320))
            surface.fill((0, 0, 0))
            archives.render_transmission_player(
                surface, pygame.Rect(0, 0, 480, 320), state, 1,
                _FixedPositionSink(1000),
            )
            # Hashed, not raw bytes: a failure here should print a short
            # digest, not 3MB of pixels.
            return hashlib.sha256(pygame.image.tostring(surface, "RGB")).hexdigest()

        # 0:08 against 0:05, both inside a 0:09 envelope.
        self.assertNotEqual(
            render(8999), render(5000),
            "the screen renders identically for two different audio lengths, "
            "so it is labelling from the envelope duration, not the PCM",
        )

    def test_the_player_screen_draws_the_timebar(self) -> None:
        surface = pygame.Surface((480, 320))
        rect = pygame.Rect(0, 0, 480, 320)
        state = _state(recordings=(1,))

        def lit(position_ms: int) -> int:
            surface.fill((0, 0, 0))
            archives.render_transmission_player(
                surface, rect, state, 1, _FixedPositionSink(position_ms)
            )
            return sum(
                1
                for x in range(surface.get_width())
                for y in range(surface.get_height())
                if surface.get_at((x, y))[:3] != (0, 0, 0)
            )

        # Same envelope frame (50ms apart would be identical bars), so any
        # difference is the timebar and the clock, not the equalizer.
        self.assertNotEqual(lit(0), lit(900), "the player screen shows no position")


class CreateSinkTests(unittest.TestCase):
    def test_mixer_already_up_at_44k_is_torn_down_and_reopened_at_8k(self) -> None:
        """Fails against a `create_sink` that does not call `mixer.quit()`:
        the format stays 44100/stereo and playback runs at 11.03x."""
        mixer = _RealisticFakeMixer(already_initialised=True)
        sink = create_sink(pygame_module=_FakePygameModule(mixer))

        self.assertEqual(mixer.get_init(), REQUIRED_MIXER_FORMAT)
        self.assertIsInstance(sink, BufferAudioSink)

    def test_a_mixer_that_will_not_give_the_format_degrades_to_silence(self) -> None:
        """Silence is diagnosable; 11x-speed audio sounds like a decoder bug."""
        mixer = _RealisticFakeMixer(already_initialised=True, refuse=(48000, -16, 2))
        sink = create_sink(pygame_module=_FakePygameModule(mixer))
        self.assertIsInstance(sink, NullAudioSink)

    def test_disabled_yields_a_null_sink_without_touching_the_mixer(self) -> None:
        mixer = _RealisticFakeMixer(already_initialised=True)
        sink = create_sink(enabled=False, pygame_module=_FakePygameModule(mixer))
        self.assertIsInstance(sink, NullAudioSink)
        self.assertEqual(mixer.get_init(), _RealisticFakeMixer.DEFAULT, "mixer was touched")


class NullSinkTests(unittest.TestCase):
    def test_every_call_is_a_noop(self) -> None:
        sink = NullAudioSink()
        sink.play(b"\x00\x00", 1000)
        sink.toggle_pause()
        sink.seek_by(5000)
        sink.tick()
        sink.stop()
        self.assertFalse(sink.is_playing)
        self.assertFalse(sink.is_paused)
        self.assertEqual(sink.position_ms, 0)


class BufferSinkTests(unittest.TestCase):
    def test_play_hands_the_whole_buffer_to_sound_and_keeps_it_alive(self) -> None:
        sink, mixer, _clock = _buffer_sink()
        pcm = _pcm(5000)
        sink.play(pcm, 5000)

        self.assertTrue(sink.is_playing)
        self.assertEqual(mixer.buffers, [pcm])
        # pygame does not hold the Sound for you; a collected one stops
        # playback mid-track.
        self.assertIsNotNone(sink._sound)

    def test_position_advances_with_the_clock_and_freezes_while_paused(self) -> None:
        sink, _mixer, clock = _buffer_sink()
        sink.play(_pcm(10_000), 10_000)

        clock.advance_ms(500)
        self.assertEqual(sink.position_ms, 500)

        sink.toggle_pause()
        clock.advance_ms(2000)
        self.assertEqual(sink.position_ms, 500, "a paused track does not advance")

        sink.toggle_pause()
        clock.advance_ms(300)
        self.assertEqual(sink.position_ms, 800, "and resumes from where it stopped")

    def test_position_clamps_to_the_declared_duration(self) -> None:
        sink, _mixer, clock = _buffer_sink()
        sink.play(_pcm(5000), 5000)
        clock.advance_ms(9999)
        self.assertEqual(sink.position_ms, 5000)

    def test_seek_forward_slices_exactly_eighty_thousand_bytes(self) -> None:
        """Asserts the slice handed to `Sound`, not the bookkeeping field."""
        sink, mixer, clock = _buffer_sink()
        pcm = _pcm(20_000)
        sink.play(pcm, 20_000)
        clock.advance_ms(1000)

        sink.seek_by(5000)

        self.assertEqual(len(mixer.buffers), 2)
        self.assertEqual(mixer.buffers[1], pcm[byte_offset(6000):])
        self.assertEqual(len(pcm) - len(mixer.buffers[1]), 96_000)
        self.assertEqual(sink.position_ms, 6000)

    def test_rewind_past_the_start_clamps_to_offset_zero(self) -> None:
        sink, mixer, clock = _buffer_sink()
        pcm = _pcm(20_000)
        sink.play(pcm, 20_000)
        clock.advance_ms(2000)

        sink.seek_by(-5000)

        self.assertTrue(sink.is_playing)
        self.assertEqual(sink.position_ms, 0)
        self.assertEqual(mixer.buffers[1], pcm, "clamped seek replays the whole buffer")

    def test_seek_into_the_envelope_rounding_gap_stops_instead_of_slicing_empty(self) -> None:
        """The near-end case, with `boil1`'s real, non-frame-aligned size.

        175,090 bytes is 10,943ms of audio, but its 219 envelope frames
        describe 10,950ms. A sink that bounds seeks on the ENVELOPE duration
        accepts a target in that 7ms gap and then slices an empty buffer:
        playback stops silently while the transport still shows time left.

        The duration passed here is deliberately the wrong one - the
        envelope's - so the test fails against a sink that trusts it.

        The target matters. `_start_at` refuses an offset past the end of the
        buffer, so most of the gap is caught by that guard whichever bound is
        used, and a test aiming there passes against BOTH implementations.
        10,943ms is the one millisecond in the gap whose byte offset
        (175,088) still lands inside the buffer: bound on the envelope and
        the sink happily builds a Sound over the final 2 bytes - one sample -
        and reports itself as playing.
        """
        sink, mixer, clock = _buffer_sink()
        pcm = bytes(175_090)  # boil1: 10,943ms of audio, 10,950ms of envelope
        sink.play(pcm, 10_950)
        clock.advance_ms(5943)

        sink.seek_by(5000)  # target 10,943ms: the end of the audio exactly

        self.assertFalse(sink.is_playing, "must stop rather than play a 2-byte tail")
        self.assertEqual(len(mixer.buffers), 1, "no second Sound was built")

    def test_fast_forward_past_the_end_stops(self) -> None:
        sink, _mixer, clock = _buffer_sink()
        sink.play(_pcm(5000), 5000)
        clock.advance_ms(4000)
        sink.seek_by(5000)
        self.assertFalse(sink.is_playing)

    def test_a_seek_while_paused_stays_paused(self) -> None:
        sink, _mixer, clock = _buffer_sink()
        sink.play(_pcm(20_000), 20_000)
        clock.advance_ms(1000)
        sink.toggle_pause()

        sink.seek_by(5000)

        self.assertTrue(sink.is_paused, "a seek must not silently resume playback")
        self.assertEqual(sink.position_ms, 6000)

    def test_toggle_pause_round_trips_on_the_channel(self) -> None:
        sink, mixer, _clock = _buffer_sink()
        sink.play(_pcm(5000), 5000)

        sink.toggle_pause()
        self.assertTrue(sink.is_paused)
        sink.toggle_pause()
        self.assertFalse(sink.is_paused)

        channel = mixer.channels[0]
        self.assertEqual(channel.calls.count("pause"), 1)
        self.assertEqual(channel.calls.count("unpause"), 1)

    def test_tick_notices_a_finished_track(self) -> None:
        sink, mixer, _clock = _buffer_sink()
        sink.play(_pcm(5000), 5000)
        mixer.channels[0].busy = False
        sink.tick()
        self.assertFalse(sink.is_playing)

    def test_stop_resets_so_replay_starts_from_the_beginning(self) -> None:
        sink, _mixer, clock = _buffer_sink()
        pcm = _pcm(10_000)
        sink.play(pcm, 10_000)
        clock.advance_ms(2000)
        sink.seek_by(3000)
        sink.stop()
        self.assertEqual(sink.position_ms, 0)

        sink.play(pcm, 10_000)
        self.assertEqual(sink.position_ms, 0)

    def test_a_failing_mixer_leaves_the_sink_stopped_rather_than_raising(self) -> None:
        sink, mixer, _clock = _buffer_sink()
        mixer.raise_on_sound = True
        sink.play(_pcm(5000), 5000)
        self.assertFalse(sink.is_playing)
        self.assertEqual(sink.position_ms, 0)

    def test_an_empty_buffer_is_not_playable(self) -> None:
        sink, mixer, _clock = _buffer_sink()
        sink.play(b"", 0)
        self.assertFalse(sink.is_playing)
        self.assertEqual(mixer.buffers, [])


class _RecordingSink:
    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.is_playing = False
        self.is_paused = False
        self.position_ms = 0

    def play(self, path, duration_ms):
        self.calls.append(("play", path, duration_ms))
        self.is_playing = True

    def toggle_pause(self):
        self.calls.append(("toggle_pause",))

    def seek_by(self, delta_ms):
        self.calls.append(("seek_by", delta_ms))

    def stop(self):
        self.calls.append(("stop",))
        self.is_playing = False

    def tick(self):
        self.calls.append(("tick",))


class PlaybackControllerTests(unittest.TestCase):
    def _apply(self, sink, before, after, event, state):
        transmission_playback.apply(
            sink, Page.ARCHIVES, before, Page.ARCHIVES, after, event, state
        )

    def test_opening_a_disk_starts_playback(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        self._apply(sink, _ui(activated=True), _ui(activated=True, drill="T1"),
                    ConfirmEvent(), state)
        self.assertEqual(sink.calls[0], ("stop",))
        self.assertEqual(sink.calls[1][0], "play")
        self.assertEqual(sink.calls[1][2], 1000)  # 20 frames * 50ms

    def test_opening_a_disk_without_audio_does_not_play(self) -> None:
        state = _state(recordings=())
        sink = _RecordingSink()
        self._apply(sink, _ui(activated=True), _ui(activated=True, drill="T1"),
                    ConfirmEvent(), state)
        self.assertEqual(sink.calls, [("stop",)])

    def test_confirm_on_an_open_disk_toggles_pause(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        open_ui = _ui(activated=True, drill="T1")
        self._apply(sink, open_ui, open_ui, ConfirmEvent(), state)
        self.assertEqual(sink.calls, [("toggle_pause",)])

    def test_encoder_seeks_five_seconds_each_way(self) -> None:
        state = _state(recordings=(1,))
        open_ui = _ui(activated=True, drill="T1")
        for event, expected in (
            (EncoderLeftEvent(), -transmission_playback.SEEK_STEP_MS),
            (EncoderRightEvent(), transmission_playback.SEEK_STEP_MS),
        ):
            sink = _RecordingSink()
            self._apply(sink, open_ui, open_ui, event, state)
            self.assertEqual(sink.calls, [("seek_by", expected)])

    def test_leaving_the_disk_stops_and_resets(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        self._apply(sink, _ui(activated=True, drill="T1"), _ui(activated=True),
                    ConfirmEvent(), state)
        self.assertEqual(sink.calls, [("stop",)])

    def test_section_switch_stops(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        transmission_playback.apply(
            sink,
            Page.ARCHIVES,
            _ui(activated=True, drill="T1"),
            Page.STATUS,
            sections.deactivated(_ui(activated=True, drill="T1")),
            ConfirmEvent(),
            state,
        )
        self.assertEqual(sink.calls, [("stop",)])

    def test_transport_is_inert_when_no_disk_is_open(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        closed = _ui(activated=True)
        self._apply(sink, closed, closed, ConfirmEvent(), state)
        self.assertEqual(sink.calls, [])

    def test_sync_stops_on_disconnect(self) -> None:
        """A disconnect never passes through input routing at all."""
        state = _state(recordings=(1,))
        state.connection = ConnectionState.RECONNECTING
        sink = _RecordingSink()
        transmission_playback.sync(sink, Page.ARCHIVES, _ui(activated=True, drill="T1"), state)
        self.assertEqual(sink.calls, [("stop",)])

    def test_sync_ticks_while_a_disk_is_open(self) -> None:
        state = _state(recordings=(1,))
        sink = _RecordingSink()
        transmission_playback.sync(sink, Page.ARCHIVES, _ui(activated=True, drill="T1"), state)
        self.assertEqual(sink.calls, [("tick",)])

    def test_quests_depth_is_never_read_as_a_transmission(self) -> None:
        """The leak TASK-017's test caught; guarded here from the other side."""
        ui = _ui(ARCHIVES_QUESTS, activated=True)
        ui = replace(ui, quest_drill_key="L3")
        self.assertIsNone(transmission_playback.open_disk_index(Page.ARCHIVES, ui))


class TransmissionRenderTests(unittest.TestCase):
    """Pixel assertions only where rendering is the thing under test."""

    RECT = pygame.Rect(0, 112, 480, 688)

    def setUp(self) -> None:
        pygame.init()
        self.surface = pygame.Surface((480, 800))

    def _lit(self) -> int:
        count = 0
        for y in range(112, 800, 2):
            for x in range(0, 480, 2):
                if self.surface.get_at((x, y))[:3] != (0, 0, 0):
                    count += 1
        return count

    def _render(self, state, focus, sink=None) -> int:
        self.surface.fill((0, 0, 0))
        archives.render_transmissions(self.surface, self.RECT, state, focus, sink)
        return self._lit()

    def test_every_mode_draws_something(self) -> None:
        state = _state()
        modes = {
            "list": (state, SubSectionFocus(activated=True, cursor=ListCursor(selected_key="T1"))),
            "empty": (AppState(), SubSectionFocus(activated=False, cursor=ListCursor())),
            "no_record": (state, SubSectionFocus(activated=True, cursor=ListCursor(), location_key="T1")),
        }
        for name, (st, focus) in modes.items():
            with self.subTest(mode=name):
                self.assertGreater(self._render(st, focus), 0, f"{name} drew nothing")

    def test_syncing_and_no_record_are_different_messages(self) -> None:
        focus = SubSectionFocus(activated=True, cursor=ListCursor(), location_key="T1")
        syncing = self._render(_state(status=TransmissionSyncStatus.FETCHING), focus)
        settled = self._render(_state(status=TransmissionSyncStatus.READY), focus)
        self.assertNotEqual(syncing, settled)

    def test_playing_draws_more_than_paused(self) -> None:
        """The equalizer must visibly move while playing and sit at its
        floor while paused — that is what makes pause readable."""
        state = _state(recordings=(1,))
        focus = SubSectionFocus(activated=True, cursor=ListCursor(), location_key="T1")

        class Playing:
            is_playing, is_paused, position_ms = True, False, 250

        class Paused:
            is_playing, is_paused, position_ms = True, True, 250

        self.assertGreater(self._render(state, focus, Playing()),
                           self._render(state, focus, Paused()))

    def test_no_body_text_is_ever_carried(self) -> None:
        """Contract test: the model has no field a body could live in."""
        self.assertEqual(
            {f for f in Transmission.__dataclass_fields__},
            {"index", "title"},
        )


if __name__ == "__main__":
    unittest.main()


def _client_for(state):
    """A real ``NetworkClient`` with no socket and no ``__init__``.

    ``__new__`` plus the handful of attributes the transmission methods touch:
    the alternative is a proxy object, which silently fails to forward
    ``staticmethod``s like ``_envelope_is_valid``.
    """
    from companion_app.net.client import NetworkClient

    client = NetworkClient.__new__(NetworkClient)
    client._state = state
    client._transmission_dir = None
    client._log_fn = None
    client.sent = []
    client._queue_line = client.sent.append
    client._log = lambda msg, visible=True: None
    return client


def _hdev(bands: int, frames: int, frame_ms: int = 50) -> bytes:
    import struct

    return (
        b"HDEV"
        + struct.pack("<HH", 1, bands)
        + struct.pack("<IH", frames, frame_ms)
        + _envelope(bands, frames)
    )


class TransmissionSyncTests(unittest.TestCase):
    """Criterion 12 (fetch on connect) and 8 (nothing written to disk)."""

    def setUp(self) -> None:
        import base64

        self.b64 = base64.b64encode
        self.state = AppState()
        self.state.transmission_audio.status = TransmissionSyncStatus.FETCHING
        self.client = _client_for(self.state)

    def test_manifest_drives_the_fetch_set_not_availability(self) -> None:
        """The disk the player has NOT found is still fetched."""
        self.state.player.transmissions = [Transmission(index=3, title="FOUND")]
        self.client._on_transmission_manifest({"entries": [{"index": 3}, {"index": 9}]})
        self.assertEqual(self.state.transmission_audio.manifest, [3, 9])
        self.assertEqual(self.client.sent[-1]["type"], "getTransmissionAudio")

    def test_full_fetch_stores_a_playable_recording_in_memory(self) -> None:
        audio = bytes(range(256)) * 4
        env = _hdev(4, 10)
        self.client._on_transmission_manifest({"entries": [{"index": 3}]})
        self.client._on_transmission_audio_header({
            "index": 3, "bytes": len(audio), "chunkCount": 1,
            "chunkBytes": 4096, "envelopeB64": self.b64(env).decode(),
        })
        self.client._on_transmission_audio_chunk({
            "index": 3, "chunk": 0, "dataB64": self.b64(audio).decode(),
        })
        recording = self.state.transmission_audio.recordings[3]
        self.assertEqual(recording.duration_ms, 500, "envelope duration: 10 frames x 50ms")
        self.assertEqual(recording.pcm, audio, "the PCM is held, not a path to it")
        self.assertIs(self.state.transmission_audio.status, TransmissionSyncStatus.READY)

    def test_the_fetch_writes_no_file_anywhere(self) -> None:
        """Criterion 8, asserted by watching the filesystem rather than by
        asserting the absence of a call."""
        import tempfile as _tempfile
        from pathlib import Path

        audio = bytes(512)
        env = _hdev(4, 10)
        with _tempfile.TemporaryDirectory() as scratch:
            before = set(Path(scratch).rglob("*"))
            cwd = os.getcwd()
            os.chdir(scratch)
            try:
                self.client._on_transmission_manifest({"entries": [{"index": 3}]})
                self.client._on_transmission_audio_header({
                    "index": 3, "bytes": len(audio), "chunkCount": 1,
                    "chunkBytes": 4096, "envelopeB64": self.b64(env).decode(),
                })
                self.client._on_transmission_audio_chunk({
                    "index": 3, "chunk": 0, "dataB64": self.b64(audio).decode(),
                })
            finally:
                os.chdir(cwd)
            self.assertEqual(set(Path(scratch).rglob("*")), before,
                             "the transmission fetch created a file")

    def test_a_manifest_entry_needs_only_an_index(self) -> None:
        """schemaVersion 15 dropped `bytes` and `envelopeBytes`."""
        self.client._on_transmission_manifest({"entries": [{"index": 3}, {"index": 7}]})
        self.assertEqual(self.state.transmission_audio.manifest, [3, 7])

    def test_a_short_transfer_stores_nothing(self) -> None:
        """A truncated stream must never become a recording. The length
        check is now the ONLY integrity gate, since there is no file to be
        left behind half-written - so it matters more, not less."""
        env = _hdev(4, 10)
        self.client._on_transmission_manifest({"entries": [{"index": 3}]})
        self.client._on_transmission_audio_header({
            "index": 3, "bytes": 999, "chunkCount": 1,
            "chunkBytes": 4096, "envelopeB64": self.b64(env).decode(),
        })
        self.client._on_transmission_audio_chunk({
            "index": 3, "chunk": 0, "dataB64": self.b64(b"tooshort").decode(),
        })
        self.assertNotIn(3, self.state.transmission_audio.recordings)

    def test_a_malformed_envelope_skips_the_disk(self) -> None:
        self.client._on_transmission_manifest({"entries": [{"index": 3}]})
        self.client._on_transmission_audio_header({
            "index": 3, "bytes": 4, "chunkCount": 1, "chunkBytes": 4096,
            "envelopeB64": self.b64(b"NOPE").decode(),
        })
        self.assertNotIn(3, self.state.transmission_audio.recordings)

    def test_an_audio_error_skips_rather_than_aborting_the_sync(self) -> None:
        self.client._on_transmission_manifest({"entries": [{"index": 1}, {"index": 2}]})
        self.client._on_transmission_audio_error({"index": 1, "reason": "noRecord"})
        self.assertEqual(self.state.transmission_audio.current_index, 2)

    def test_envelope_validation_rejects_a_length_mismatch(self) -> None:
        import struct

        bad = b"HDEV" + struct.pack("<HH", 1, 4) + struct.pack("<IH", 10, 50) + b"\x00"
        self.assertFalse(self.client._envelope_is_valid(bad))
        self.assertTrue(self.client._envelope_is_valid(_hdev(4, 10)))

    def test_a_failed_disk_is_not_retried_forever(self) -> None:
        """Regression: the sync advances by *attempted*, not by *held*.

        Keying only on ``recordings`` re-selected the failed disk every
        time and the sync never reached READY.
        """
        self.client._on_transmission_manifest({"entries": [{"index": 1}, {"index": 2}]})
        self.client._on_transmission_audio_error({"index": 1, "reason": "noRecord"})
        self.client._on_transmission_audio_error({"index": 2, "reason": "noRecord"})
        self.assertIs(self.state.transmission_audio.status, TransmissionSyncStatus.READY)
        self.assertEqual(self.state.transmission_audio.failed, {1, 2})


class ArchivesThreeSubSectionTests(unittest.TestCase):
    """TASK-024 subject correction: ARCHIVES holds three distinct things."""

    def test_order_is_quests_holodisks_transmissions(self) -> None:
        ui = sections.default_sections_ui()
        seg = sections.for_page(ui, Page.ARCHIVES)
        self.assertEqual(
            [s.key for s in seg.segments],
            [sections.ARCHIVES_QUESTS, ARCHIVES_HOLODISKS, ARCHIVES_TRANSMISSIONS],
        )

    def test_holodisks_and_transmissions_are_not_the_same_subsection(self) -> None:
        """The whole point of the correction: they are different features."""
        self.assertNotEqual(ARCHIVES_HOLODISKS, ARCHIVES_TRANSMISSIONS)

    def test_all_three_subsections_are_activatable(self) -> None:
        """HOLODISKS went live in TASK-025; ARCHIVES now has no placeholder.

        (Was ``test_holodisks_is_not_activatable_while_it_is_a_placeholder``,
        which asserted the opposite and was correct until the text reader
        landed.)
        """
        for key in (
            sections.ARCHIVES_QUESTS,
            ARCHIVES_HOLODISKS,
            ARCHIVES_TRANSMISSIONS,
        ):
            self.assertIn((Page.ARCHIVES, key), sections.ACTIVATABLE)

    def test_transmissions_keeps_its_own_cursor_and_depth(self) -> None:
        ui = sections.default_sections_ui()
        self.assertEqual(
            sections.drill_key_for(ui, Page.ARCHIVES, ARCHIVES_HOLODISKS), ""
        )
        self.assertEqual(
            sections.drill_key_for(ui, Page.ARCHIVES, ARCHIVES_TRANSMISSIONS), ""
        )

    def test_holodisks_renders_its_own_empty_state(self) -> None:
        """No longer the shared placeholder: HOLODISKS owns its empty state.

        With no disks reported it draws ``NO ARCHIVE DATA`` rather than
        ``NOT YET IMPLEMENTED``. Asserted as "something is drawn" for the same
        reason the placeholder test was: a blank body reads as a draw failure.
        """
        pygame.init()
        surface = pygame.Surface((480, 800))
        surface.fill((0, 0, 0))
        archives.ArchivesSection().render(
            surface,
            pygame.Rect(0, 56, 480, 744),
            AppState(),
            ARCHIVES_HOLODISKS,
            SubSectionFocus(activated=False, cursor=ListCursor()),
        )
        lit = sum(
            1
            for y in range(112, 800, 2)
            for x in range(0, 480, 2)
            if surface.get_at((x, y))[:3] != (0, 0, 0)
        )
        self.assertGreater(lit, 0, "HOLODISKS empty state drew nothing")


class TransmissionIdentityTests(unittest.TestCase):
    def test_two_entries_sharing_a_title_stay_distinct(self) -> None:
        """MOVIE_WALKM and MOVIE_WALKW are both 'Leaving Vault'.

        Row identity must key on the movie index, never the title, or one
        of them silently disappears from the list.
        """
        from companion_app.state import Transmission

        state = AppState()
        state.player.transmissions = [
            Transmission(index=8, title="Leaving Vault"),
            Transmission(index=9, title="Leaving Vault"),
        ]
        rows = transmission_list.list_rows(
            state.player.transmissions, state.transmission_audio
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({r.key for r in rows}), 2)

    def test_a_repeated_title_is_suffixed_from_the_second_occurrence(self) -> None:
        """The two 'Leaving Vault' rows must be distinguishable on screen.

        Distinct keys are not enough: the player only sees the label, so
        identical text means an unpickable choice. The first keeps the bare
        title, later ones get ` (n)`.
        """
        from companion_app.state import Transmission

        state = AppState()
        state.player.transmissions = [
            Transmission(index=8, title="Leaving Vault"),
            Transmission(index=9, title="Leaving Vault"),
        ]
        rows = transmission_list.project(
            state.player.transmissions, state.transmission_audio
        )
        self.assertEqual([r.title for r in rows], ["Leaving Vault", "Leaving Vault (1)"])
        # Identity stays on the index, not the decorated label.
        self.assertEqual([r.index for r in rows], [8, 9])

    def test_suffixing_is_stable_regardless_of_input_order(self) -> None:
        """Suffixes follow engine table order, not arrival order."""
        from companion_app.state import Transmission

        state = AppState()
        state.player.transmissions = [
            Transmission(index=9, title="Leaving Vault"),
            Transmission(index=8, title="Leaving Vault"),
        ]
        rows = transmission_list.project(
            state.player.transmissions, state.transmission_audio
        )
        self.assertEqual([(r.index, r.title) for r in rows],
                         [(8, "Leaving Vault"), (9, "Leaving Vault (1)")])

    def test_distinct_titles_are_left_alone(self) -> None:
        from companion_app.state import Transmission

        state = AppState()
        state.player.transmissions = [
            Transmission(index=3, title="Vat Destruction"),
            Transmission(index=4, title="Cathedral Destruction"),
        ]
        rows = transmission_list.project(
            state.player.transmissions, state.transmission_audio
        )
        self.assertEqual([r.title for r in rows],
                         ["Vat Destruction", "Cathedral Destruction"])

    def test_a_holodisk_key_never_decodes_as_a_transmission(self) -> None:
        """Guards the collision TASK-025 would otherwise introduce.

        The three ARCHIVES sub-sections share the cursor/drill machinery,
        so their row-key namespaces must stay disjoint: "L"/"Q" for quests,
        "H" for holodisks, "T" for transmissions.
        """
        self.assertIsNone(transmission_list.transmission_index_from_key("H5"))
        self.assertIsNone(transmission_list.transmission_index_from_key("L3"))
        self.assertIsNone(transmission_list.transmission_index_from_key("Q2"))
        self.assertEqual(transmission_list.transmission_index_from_key("T5"), 5)
