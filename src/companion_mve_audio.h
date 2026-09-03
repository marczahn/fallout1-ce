#ifndef FALLOUT_COMPANION_MVE_AUDIO_H_
#define FALLOUT_COMPANION_MVE_AUDIO_H_

#include <cstddef>
#include <vector>

namespace fallout {

// Standalone reader for the audio track of an `art\cuts\*.mve` cutscene.
//
// This deliberately does NOT go through `movie_lib`'s playback path. That
// path decodes only as fast as the audio ring buffer drains
// (`movie_lib.cc:1361-1388`), which is correct for playing a movie and
// useless for producing a whole track in one call. What is shared with
// `movie_lib` is the one thing that must not diverge: the DPCM delta table,
// read through `companionMveDeltaTable()`.
//
// Everything here is a pure read. No engine state is touched, no playback is
// disturbed, and the movie need never have been played.
//
// SAFETY: this parses files the player owns and may have modified, on the
// game's frame loop. Every length is validated before use and every failure
// returns `false` rather than throwing, asserting, or partially publishing.
struct CompanionMveAudio {
    // Source format, read from the movie's `0x03` sound-configuration chunk.
    // Every Fallout cutscene measures 22050 / 2 / 16.
    int sampleRate = 0;
    int channels = 0;
    int bitsPerSample = 0;

    // Interleaved samples at the SOURCE rate. Stereo means L,R,L,R...
    std::vector<short> samples;

    // Sum of the audio subheader's `count` field (`v1[2]`) over `0x08`/`0x09`
    // chunks that the stream mask ACCEPTS.
    //
    // This is NOT the chunk header's payload length: that also covers the
    // 6-byte audio subheader and, for `0x08`, the compressed input bytes,
    // which are half the decoded size. `count` is exactly what the engine
    // hands its own consumer (`movie_lib.cc:980-989`), which is what makes it
    // comparable against the measured per-movie table on TASK-026.
    size_t decodedBytes = 0;

    // Diagnostics for the TASK-026 acceptance gate. `silenceChunksPresent`
    // counts every `0x09` seen; `silenceChunksAccepted` counts those the mask
    // let through. They are NOT necessarily equal - silence appears with both
    // mask `0xFFFF` (accepted) and `0xFFFE` (skipped, it duplicates the data
    // track) - and conflating them is how a decoder ends up longer or shorter
    // than the engine's own timeline.
    int silenceChunksPresent = 0;
    int silenceChunksAccepted = 0;
    int audioChunksAccepted = 0;

    // `0x08` chunks the engine treats as silence because the chunk header's
    // version byte is non-zero (see the note in the .cc). Expected to be 0;
    // logged because a non-zero count would mean real audio is being dropped.
    int versionedAudioChunks = 0;
};

// Cheap membership probe: does this movie exist in the DAT and carry a usable
// audio track?
//
// Decompresses kilobytes, not megabytes. `db_fopen` on an LZSS-block entry
// (attribute 0x40) allocates a 16 KiB working buffer and inflates per
// `db_fread` rather than at open (`db.cc:648-655`), so a bounded prefix scan
// really is bounded.
//
// Requires BOTH a `0x03` sound configuration AND at least one accepted audio
// or silence chunk. `0x03` alone only proves a sound buffer was configured,
// not that anything was ever written to it.
bool companionMveHasAudioTrack(int game_movie);

// Full read: open, walk every record, DPCM-decode the accepted audio chunks.
// Returns false for a missing, malformed, or silent movie.
bool companionMveReadAudio(int game_movie, CompanionMveAudio& out);

} // namespace fallout

#endif /* FALLOUT_COMPANION_MVE_AUDIO_H_ */
