#ifndef FALLOUT_COMPANION_AUDIO_DEGRADE_H_
#define FALLOUT_COMPANION_AUDIO_DEGRADE_H_

#include <cstddef>
#include <vector>

#include "companion_mve_audio.h"

namespace fallout {

// The single source of truth for the companion's audio output rate.
//
// NOT configurable, deliberately. `pygame.mixer.Sound(buffer=...)` reads a
// buffer in the MIXER's format and nothing on the wire carries a rate, so a
// server emitting anything else would play at the wrong pitch with wrong seek
// arithmetic - silently, and only for whoever changed the setting. The app's
// mixer format, the sink's bytes-per-second, the 5-second seek's 80,000
// bytes, the wire size table and the envelope's samples-per-frame all derive
// from this one number. See TASK-026 `decision-fixed-output-sample-rate`.
constexpr int kTransmissionSampleRate = 8000;

// Mono, 16-bit.
constexpr int kTransmissionBytesPerSecond = kTransmissionSampleRate * 2;

// The radio recipe, from `[companion]` keys in `fallout.cfg`. Absent keys
// keep these defaults, so an untouched config produces the intended sound -
// the feature must not depend on configuration to work at all.
struct CompanionTransmissionRecipe {
    int bandLow = 300; // band-pass low corner, Hz
    int bandHigh = 3400; // band-pass high corner, Hz
    double noise = 0.008; // noise floor amplitude, 0..1
    double compressRatio = 4.0; // compressor ratio
    double limit = 0.97; // limiter ceiling, 0..1
};

// Clamps every field into a sane range, logging once per field that moved.
// A `bandHigh` above the output Nyquist is clamped rather than honoured: the
// band-pass IS the anti-alias filter for the resample below it, so letting it
// exceed Nyquist would fold energy back into the band.
void companionClampRecipe(CompanionTransmissionRecipe& recipe);

// Downmix -> band-pass (at the SOURCE rate) -> resample to
// `kTransmissionSampleRate` -> seeded noise -> compress -> limit -> mono
// little-endian int16.
//
// Deterministic: the same input and recipe always produce byte-identical
// output. The noise floor is a fixed-seed LCG, which is what keeps the
// `bytes` field, the envelope and every size assertion reproducible across
// connections.
bool companionDegradeAudio(const CompanionMveAudio& in,
    const CompanionTransmissionRecipe& recipe,
    std::vector<unsigned char>& outPcm);

// Builds the `HDEV` equalizer envelope from degraded PCM:
//
//   "HDEV" | uint16 version=1 | uint16 bands | uint32 frames
//          | uint16 frameMs | uint8[bands * frames]
//
// 14-byte little-endian header; payload is FRAME-MAJOR,
// `payload[frame * bands + band]`, which is how the app indexes it
// (`equalizer.py:52-53`). Unchanged from the TASK-024 asset contract - only
// its source moved from an offline tool to here.
bool companionBuildEnvelope(const std::vector<unsigned char>& pcm,
    const CompanionTransmissionRecipe& recipe,
    std::vector<unsigned char>& outEnvelope);

} // namespace fallout

#endif /* FALLOUT_COMPANION_AUDIO_DEGRADE_H_ */
