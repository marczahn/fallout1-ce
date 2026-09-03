#include "companion_audio_degrade.h"

#include <algorithm>
#include <cmath>
#include <cstring>

#include "plib/gnw/debug.h"

namespace fallout {

namespace {

// Equalizer envelope shape. Both are contract, not taste: the app parses
// `bands` and `frameMs` out of the header, but 16 bands at 50 ms (20 fps) is
// what TASK-024's screen was built and sized against.
constexpr int kEnvelopeBands = 16;
constexpr int kEnvelopeFrameMs = 50;
constexpr int kEnvelopeVersion = 1;
constexpr size_t kEnvelopeHeaderBytes = 14;

// Samples per envelope frame: 400 at 8 kHz / 50 ms.
constexpr int kEnvelopeFrameSamples = kTransmissionSampleRate * kEnvelopeFrameMs / 1000;

// Compressor knee. Not exposed in `fallout.cfg`: the ratio is the knob that
// changes the character, and a second interacting one would make tuning by
// ear a two-variable search for no extra expressive range.
constexpr double kCompressorThreshold = 0.10;

// Envelope-follower coefficients, in samples at the output rate. Fast attack,
// slow release - the classic broadcast-limiter shape, which is the sound
// being imitated.
constexpr double kAttackCoef = 0.15;
constexpr double kReleaseCoef = 0.9995;

// A biquad in direct form I.
struct Biquad {
    double b0 = 1.0, b1 = 0.0, b2 = 0.0, a1 = 0.0, a2 = 0.0;
    double x1 = 0.0, x2 = 0.0, y1 = 0.0, y2 = 0.0;

    double process(double x)
    {
        double y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2;
        x2 = x1;
        x1 = x;
        y2 = y1;
        y1 = y;
        return y;
    }
};

// RBJ cookbook, Q = 1/sqrt(2) (Butterworth).
constexpr double kQ = 0.70710678118654752;

Biquad makeHighPass(double cutoff, double sampleRate)
{
    Biquad f;
    double w0 = 2.0 * M_PI * cutoff / sampleRate;
    double cosw = std::cos(w0);
    double alpha = std::sin(w0) / (2.0 * kQ);
    double a0 = 1.0 + alpha;

    f.b0 = ((1.0 + cosw) / 2.0) / a0;
    f.b1 = (-(1.0 + cosw)) / a0;
    f.b2 = ((1.0 + cosw) / 2.0) / a0;
    f.a1 = (-2.0 * cosw) / a0;
    f.a2 = (1.0 - alpha) / a0;
    return f;
}

Biquad makeLowPass(double cutoff, double sampleRate)
{
    Biquad f;
    double w0 = 2.0 * M_PI * cutoff / sampleRate;
    double cosw = std::cos(w0);
    double alpha = std::sin(w0) / (2.0 * kQ);
    double a0 = 1.0 + alpha;

    f.b0 = ((1.0 - cosw) / 2.0) / a0;
    f.b1 = (1.0 - cosw) / a0;
    f.b2 = ((1.0 - cosw) / 2.0) / a0;
    f.a1 = (-2.0 * cosw) / a0;
    f.a2 = (1.0 - alpha) / a0;
    return f;
}

// Deterministic noise. A fixed-seed LCG rather than `rand()`, because the
// same transmission must degrade to byte-identical PCM on every connection -
// otherwise `bytes`, the envelope and every size assertion stop being
// reproducible.
class SeededNoise {
public:
    explicit SeededNoise(unsigned int seed)
        : state_(seed)
    {
    }

    // Uniform in [-1, 1).
    double next()
    {
        state_ = state_ * 1664525u + 1013904223u;
        return (static_cast<double>(state_ >> 8) / 8388608.0) - 1.0;
    }

private:
    unsigned int state_;
};

short quantize(double value)
{
    double scaled = value * 32767.0;
    if (scaled > 32767.0) {
        scaled = 32767.0;
    }
    if (scaled < -32768.0) {
        scaled = -32768.0;
    }
    return static_cast<short>(std::lround(scaled));
}

// Goertzel magnitude for one band over one frame. The engine has no FFT and
// does not need one: 16 bands x 400 samples is 6,400 multiply-accumulates per
// frame, i.e. milliseconds for a whole transmission.
double goertzel(const short* samples, int count, double centerHz, double sampleRate)
{
    double k = centerHz * count / sampleRate;
    double w = 2.0 * M_PI * k / count;
    double coeff = 2.0 * std::cos(w);

    double s0 = 0.0;
    double s1 = 0.0;
    double s2 = 0.0;
    for (int i = 0; i < count; ++i) {
        s0 = samples[i] / 32768.0 + coeff * s1 - s2;
        s2 = s1;
        s1 = s0;
    }

    double magnitudeSquared = s1 * s1 + s2 * s2 - coeff * s1 * s2;
    return magnitudeSquared > 0.0 ? std::sqrt(magnitudeSquared) : 0.0;
}

} // namespace

void companionClampRecipe(CompanionTransmissionRecipe& recipe)
{
    CompanionTransmissionRecipe defaults;
    int nyquist = kTransmissionSampleRate / 2;

    if (recipe.bandLow <= 0 || recipe.bandLow >= nyquist) {
        debug_printf("companion: transmission_band_low out of range, using %d\n", defaults.bandLow);
        recipe.bandLow = defaults.bandLow;
    }

    // Clamped rather than honoured: the low-pass IS the anti-alias filter for
    // the 22050 -> 8000 resample, so a corner above Nyquist would fold
    // everything above 4 kHz back into the band. Intelligibility is the first
    // casualty and it reads as "bad radio" rather than as a bug.
    if (recipe.bandHigh <= recipe.bandLow || recipe.bandHigh > nyquist) {
        debug_printf("companion: transmission_band_high out of range, using %d\n", defaults.bandHigh);
        recipe.bandHigh = defaults.bandHigh;
    }

    if (recipe.noise < 0.0 || recipe.noise > 0.5) {
        debug_printf("companion: transmission_noise out of range, using %.4f\n", defaults.noise);
        recipe.noise = defaults.noise;
    }

    if (recipe.compressRatio < 1.0 || recipe.compressRatio > 20.0) {
        debug_printf("companion: transmission_compress_ratio out of range, using %.2f\n",
            defaults.compressRatio);
        recipe.compressRatio = defaults.compressRatio;
    }

    if (recipe.limit < 0.1 || recipe.limit > 1.0) {
        debug_printf("companion: transmission_limit out of range, using %.2f\n", defaults.limit);
        recipe.limit = defaults.limit;
    }
}

bool companionDegradeAudio(const CompanionMveAudio& in,
    const CompanionTransmissionRecipe& recipe,
    std::vector<unsigned char>& outPcm)
{
    outPcm.clear();

    if (in.channels < 1 || in.sampleRate <= 0 || in.samples.empty()) {
        return false;
    }

    size_t frames = in.samples.size() / static_cast<size_t>(in.channels);
    if (frames == 0) {
        return false;
    }

    // -- 1. Downmix to mono, normalised to -1..1 ------------------------
    std::vector<double> mono;
    mono.reserve(frames);
    for (size_t i = 0; i < frames; ++i) {
        int sum = 0;
        for (int c = 0; c < in.channels; ++c) {
            sum += in.samples[i * in.channels + c];
        }
        mono.push_back(static_cast<double>(sum) / (in.channels * 32768.0));
    }

    // -- 2. Band-pass AT THE SOURCE RATE --------------------------------
    //
    // This MUST run before the resample below. 22050 -> 8000 is a decimation
    // by 2.756, so without the low-pass already applied everything above
    // 4 kHz folds back into the band as aliasing. With `bandHigh` at 3400 the
    // band-pass IS the anti-alias filter - but only if it runs first. Do not
    // reorder these two stages for "efficiency".
    Biquad highPass = makeHighPass(recipe.bandLow, in.sampleRate);
    Biquad lowPass = makeLowPass(recipe.bandHigh, in.sampleRate);
    for (double& sample : mono) {
        sample = lowPass.process(highPass.process(sample));
    }

    // -- 3. Resample to the output rate ---------------------------------
    //
    // Output length is the exact ratio, floored. NOT derived from a rounded
    // duration: `boil1` is 241,298 source frames -> 87,545 output samples ->
    // 175,090 bytes. TASK-026's original table said 175,088 because it
    // multiplied a millisecond-rounded duration by the byte rate.
    size_t outSamples = static_cast<size_t>(
        static_cast<unsigned long long>(frames) * kTransmissionSampleRate / in.sampleRate);
    if (outSamples == 0) {
        return false;
    }

    std::vector<double> resampled;
    resampled.reserve(outSamples);
    double step = static_cast<double>(in.sampleRate) / kTransmissionSampleRate;
    for (size_t i = 0; i < outSamples; ++i) {
        double position = i * step;
        size_t index = static_cast<size_t>(position);
        double fraction = position - index;
        double a = mono[index];
        double b = (index + 1 < frames) ? mono[index + 1] : a;
        resampled.push_back(a + (b - a) * fraction);
    }

    // -- 4. Seeded noise floor ------------------------------------------
    SeededNoise noise(0x5AFE10A1u);
    for (double& sample : resampled) {
        sample += noise.next() * recipe.noise;
    }

    // -- 5. Compressor, makeup, limiter ---------------------------------
    double envelope = 0.0;
    for (double& sample : resampled) {
        double magnitude = std::fabs(sample);
        if (magnitude > envelope) {
            envelope += (magnitude - envelope) * kAttackCoef;
        } else {
            envelope *= kReleaseCoef;
        }

        if (envelope > kCompressorThreshold) {
            double compressed = kCompressorThreshold
                + (envelope - kCompressorThreshold) / recipe.compressRatio;
            sample *= compressed / envelope;
        }
    }

    // Makeup gain: bring the loudest moment up to the limiter ceiling, so
    // heavy compression does not simply mean quiet.
    double peak = 0.0;
    for (double sample : resampled) {
        peak = std::max(peak, std::fabs(sample));
    }
    if (peak > 0.0) {
        double makeup = recipe.limit / peak;
        for (double& sample : resampled) {
            sample *= makeup;
        }
    }

    // Soft limiter. `tanh` rather than a hard clip: the ticket asks for mild
    // clipping as a character, and hard clipping at this ratio buzzes.
    //
    // Then RE-NORMALISE to the ceiling, which is not cosmetic. `tanh(1)` is
    // 0.762, so saturating a signal already scaled to `limit` lands its peak
    // at 0.739 rather than 0.97 - every transmission came out 24% below the
    // ceiling, and `transmission_limit` silently meant something other than
    // what it says. That is the same defect class as a configurable sample
    // rate the app cannot honour: a key that lies. The second pass costs one
    // more scan and makes the number true.
    for (double& sample : resampled) {
        sample = recipe.limit * std::tanh(sample / recipe.limit);
    }

    double limitedPeak = 0.0;
    for (double sample : resampled) {
        limitedPeak = std::max(limitedPeak, std::fabs(sample));
    }
    if (limitedPeak > 0.0) {
        double trim = recipe.limit / limitedPeak;
        for (double& sample : resampled) {
            sample *= trim;
        }
    }

    // -- 6. Quantise to little-endian int16 -----------------------------
    outPcm.resize(outSamples * 2);
    for (size_t i = 0; i < outSamples; ++i) {
        short value = quantize(resampled[i]);
        outPcm[i * 2] = static_cast<unsigned char>(value & 0xFF);
        outPcm[i * 2 + 1] = static_cast<unsigned char>((value >> 8) & 0xFF);
    }

    return true;
}

bool companionBuildEnvelope(const std::vector<unsigned char>& pcm,
    const CompanionTransmissionRecipe& recipe,
    std::vector<unsigned char>& outEnvelope)
{
    outEnvelope.clear();

    size_t sampleCount = pcm.size() / 2;
    if (sampleCount == 0) {
        return false;
    }

    std::vector<short> samples(sampleCount);
    for (size_t i = 0; i < sampleCount; ++i) {
        samples[i] = static_cast<short>(
            static_cast<unsigned short>(pcm[i * 2]) | (static_cast<unsigned short>(pcm[i * 2 + 1]) << 8));
    }

    // The last frame is partial and is ZERO-PADDED rather than dropped -
    // dropping it would end the equalizer before the audio does.
    size_t frameCount = (sampleCount + kEnvelopeFrameSamples - 1) / kEnvelopeFrameSamples;
    if (frameCount == 0) {
        return false;
    }

    // Log-spaced band centres across the pass band. Log rather than linear
    // because that is how pitch is perceived, so the bars move evenly.
    double centers[kEnvelopeBands];
    double low = static_cast<double>(recipe.bandLow);
    double high = static_cast<double>(recipe.bandHigh);
    double logLow = std::log(low);
    double logHigh = std::log(high);
    for (int band = 0; band < kEnvelopeBands; ++band) {
        double t = static_cast<double>(band) / (kEnvelopeBands - 1);
        centers[band] = std::exp(logLow + (logHigh - logLow) * t);
    }

    std::vector<double> magnitudes(frameCount * kEnvelopeBands, 0.0);
    std::vector<short> frame(kEnvelopeFrameSamples, 0);

    for (size_t f = 0; f < frameCount; ++f) {
        size_t start = f * kEnvelopeFrameSamples;
        size_t available = std::min(static_cast<size_t>(kEnvelopeFrameSamples), sampleCount - start);
        std::memcpy(frame.data(), samples.data() + start, available * sizeof(short));
        if (available < static_cast<size_t>(kEnvelopeFrameSamples)) {
            std::memset(frame.data() + available, 0,
                (kEnvelopeFrameSamples - available) * sizeof(short));
        }

        for (int band = 0; band < kEnvelopeBands; ++band) {
            magnitudes[f * kEnvelopeBands + band] = goertzel(
                frame.data(), kEnvelopeFrameSamples, centers[band], kTransmissionSampleRate);
        }
    }

    // Normalise by this transmission's own 99th-percentile magnitude rather
    // than an absolute scale, so a quiet cutscene still animates. A handful
    // of transients clip to 255, which is what makes the bars hit the top.
    std::vector<double> sorted = magnitudes;
    std::sort(sorted.begin(), sorted.end());
    double reference = sorted[static_cast<size_t>(sorted.size() * 0.99)];
    if (reference <= 0.0) {
        reference = sorted.back();
    }

    outEnvelope.resize(kEnvelopeHeaderBytes + frameCount * kEnvelopeBands);
    std::memcpy(outEnvelope.data(), "HDEV", 4);
    auto put16 = [&](size_t offset, unsigned int value) {
        outEnvelope[offset] = static_cast<unsigned char>(value & 0xFF);
        outEnvelope[offset + 1] = static_cast<unsigned char>((value >> 8) & 0xFF);
    };
    put16(4, kEnvelopeVersion);
    put16(6, kEnvelopeBands);
    outEnvelope[8] = static_cast<unsigned char>(frameCount & 0xFF);
    outEnvelope[9] = static_cast<unsigned char>((frameCount >> 8) & 0xFF);
    outEnvelope[10] = static_cast<unsigned char>((frameCount >> 16) & 0xFF);
    outEnvelope[11] = static_cast<unsigned char>((frameCount >> 24) & 0xFF);
    put16(12, kEnvelopeFrameMs);

    // FRAME-MAJOR: `payload[frame * bands + band]`, matching `equalizer.py`.
    for (size_t i = 0; i < magnitudes.size(); ++i) {
        double normalised = reference > 0.0 ? magnitudes[i] / reference : 0.0;
        int level = static_cast<int>(std::lround(normalised * 255.0));
        if (level < 0) {
            level = 0;
        }
        if (level > 255) {
            level = 255;
        }
        outEnvelope[kEnvelopeHeaderBytes + i] = static_cast<unsigned char>(level);
    }

    return true;
}

} // namespace fallout
