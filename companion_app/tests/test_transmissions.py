"""TASK-024 ARCHIVES/TRANSMISSIONS: projection, audio, controller, renderer.

Follows the project's habits: select state explicitly rather than driving
the UI to reach it, keep the pure layers pygame-free, and assert pixels
only where rendering is the thing under test.
"""
from __future__ import annotations

import unittest
from dataclasses import replace

import pygame

from companion_app.audio import equalizer
from companion_app.audio.sink import MusicAudioSink, NullAudioSink
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
            path=f"/tmp/transmission_{index:02d}.ogg",
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


class _FakeMusic:
    """Stands in for ``pygame.mixer.music``, including its two traps."""

    def __init__(self, duration_ms: int = 5000) -> None:
        self.duration_ms = duration_ms
        self.elapsed = 0
        self.loaded = None
        self.playing = False
        self.paused = False
        self.calls: list[str] = []

    def load(self, path):
        self.loaded = path
        self.calls.append("load")

    def play(self):
        self.playing = True
        self.elapsed = 0
        self.calls.append("play")

    def stop(self):
        self.playing = False
        self.calls.append("stop")

    def pause(self):
        self.paused = True
        self.calls.append("pause")

    def unpause(self):
        self.paused = False
        self.calls.append("unpause")

    def get_busy(self):
        return self.playing

    def get_pos(self):
        # Trap 1: counts since play(), ignoring set_pos.
        return self.elapsed if self.playing else -1

    def set_pos(self, seconds):
        # Trap 2: raises past end-of-track, with a misleading message.
        if seconds * 1000 >= self.duration_ms:
            raise _FakePygameError("Position not implemented for music type")
        self.calls.append(f"set_pos:{seconds}")


class _FakePygameError(Exception):
    pass


class _FakePygame:
    error = _FakePygameError

    def __init__(self, music: _FakeMusic) -> None:
        class _Mixer:
            pass

        self.mixer = _Mixer()
        self.mixer.music = music


def _sink_with(music: _FakeMusic) -> MusicAudioSink:
    sink = MusicAudioSink.__new__(MusicAudioSink)
    sink._pygame = _FakePygame(music)
    sink._duration_ms = 0
    sink._seek_base_ms = 0
    sink._seek_origin_ms = 0
    sink._paused = False
    sink._active = False
    return sink


class NullSinkTests(unittest.TestCase):
    def test_every_call_is_a_noop(self) -> None:
        sink = NullAudioSink()
        sink.play("/nope", 1000)
        sink.toggle_pause()
        sink.seek_by(5000)
        sink.tick()
        sink.stop()
        self.assertFalse(sink.is_playing)
        self.assertFalse(sink.is_paused)
        self.assertEqual(sink.position_ms, 0)


class MusicSinkTests(unittest.TestCase):
    def test_position_is_tracked_across_a_seek(self) -> None:
        """`get_pos()` ignores `set_pos()`, so the sink must add a base."""
        music = _FakeMusic(duration_ms=10_000)
        sink = _sink_with(music)
        sink.play("/a.ogg", 10_000)
        music.elapsed = 500
        self.assertEqual(sink.position_ms, 500)

        # SDL does NOT restart its counter at a seek; it keeps counting
        # from play(). The sink must subtract the reading it took at the
        # seek, or every seek compounds. Measured against real SDL in the
        # TASK-024 P0 check.
        sink.seek_by(3000)
        self.assertEqual(sink.position_ms, 3500, "position lands on the seek target")
        music.elapsed = 1000  # 500ms more wall-clock since the seek
        self.assertEqual(sink.position_ms, 4000, "and advances from there, once")

    def test_rewind_clamps_at_zero(self) -> None:
        music = _FakeMusic(duration_ms=10_000)
        sink = _sink_with(music)
        sink.play("/a.ogg", 10_000)
        music.elapsed = 1000
        sink.seek_by(-5000)
        self.assertEqual(sink.position_ms, 0)
        self.assertTrue(sink.is_playing)

    def test_fast_forward_past_the_end_stops_instead_of_seeking(self) -> None:
        """The P0 finding: `set_pos()` past the end raises, so it is never
        called with an out-of-range target."""
        music = _FakeMusic(duration_ms=5000)
        sink = _sink_with(music)
        sink.play("/a.ogg", 5000)
        music.elapsed = 4000
        sink.seek_by(5000)
        self.assertFalse(sink.is_playing)
        self.assertNotIn("set_pos:9.0", music.calls)

    def test_toggle_pause_round_trips(self) -> None:
        music = _FakeMusic()
        sink = _sink_with(music)
        sink.play("/a.ogg", 5000)
        sink.toggle_pause()
        self.assertTrue(sink.is_paused)
        sink.toggle_pause()
        self.assertFalse(sink.is_paused)
        self.assertEqual(music.calls.count("pause"), 1)
        self.assertEqual(music.calls.count("unpause"), 1)

    def test_stop_resets_so_replay_starts_from_the_beginning(self) -> None:
        music = _FakeMusic(duration_ms=10_000)
        sink = _sink_with(music)
        sink.play("/a.ogg", 10_000)
        music.elapsed = 2000
        sink.seek_by(3000)
        sink.stop()
        self.assertEqual(sink.position_ms, 0)
        sink.play("/a.ogg", 10_000)
        music.elapsed = 0
        self.assertEqual(sink.position_ms, 0)

    def test_tick_notices_a_finished_track(self) -> None:
        music = _FakeMusic()
        sink = _sink_with(music)
        sink.play("/a.ogg", 5000)
        music.playing = False
        sink.tick()
        self.assertFalse(sink.is_playing)

    def test_a_failed_load_does_not_leave_the_sink_active(self) -> None:
        music = _FakeMusic()

        def boom(_path):
            raise _FakePygameError("no such file")

        music.load = boom
        sink = _sink_with(music)
        sink.play("/missing.ogg", 1000)
        self.assertFalse(sink.is_playing)


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
    """Criterion 12 (fetch on connect) and 14 (no truncated file)."""

    def setUp(self) -> None:
        import base64

        self.b64 = base64.b64encode
        self.state = AppState()
        self.state.transmission_audio.status = TransmissionSyncStatus.FETCHING
        self.client = _client_for(self.state)

    def tearDown(self) -> None:
        self.client._discard_transmission_scratch()

    def test_manifest_drives_the_fetch_set_not_availability(self) -> None:
        """The disk the player has NOT found is still fetched."""
        self.state.player.transmissions = [Transmission(index=3, title="FOUND")]
        self.client._on_transmission_manifest({"entries": [{"index": 3}, {"index": 9}]})
        self.assertEqual(self.state.transmission_audio.manifest, [3, 9])
        self.assertEqual(self.client.sent[-1]["type"], "getTransmissionAudio")

    def test_full_fetch_stores_a_playable_recording(self) -> None:
        audio = b"OggS" + b"\x00" * 100
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
        self.assertEqual(recording.duration_ms, 500)
        with open(recording.path, "rb") as handle:
            self.assertEqual(handle.read(), audio)
        self.assertIs(self.state.transmission_audio.status, TransmissionSyncStatus.READY)

    def test_a_short_transfer_stores_nothing(self) -> None:
        """Criterion 14: a truncated stream must never become a file."""
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
