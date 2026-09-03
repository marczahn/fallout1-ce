#include "companion_mve_audio.h"

#include <cstdio>
#include <cstring>

#include "game/gmovie.h"
#include "movie_lib.h"
#include "platform_compat.h"
#include "plib/db/db.h"
#include "plib/gnw/debug.h"

namespace fallout {

namespace {

// MVE is RECORD-FRAMED, and this is the first thing a new reader gets wrong.
// Reading the file as one continuous chunk stream desynchronises immediately
// and reports nonsense (a 57346 Hz sample rate, in the case that prompted
// this comment). The layout, from `movie_lib.cc`:
//
//   [30-byte file header, whose LAST 4 bytes are record 0's header]
//   [record payload][next record's 4-byte header]
//   [record payload][next record's 4-byte header] ...
//
// A record header is `uint16 length, uint16 kind` (`_ioNextRecord`,
// `movie_lib.cc:756-767`). Inside a record are chunks, each a `uint32`:
// low 16 bits = payload length, bits 16-23 = opcode, bits 24-31 = version
// (`_MVE_rmStepMovie`, `:861-866`). Opcode 0x01 ends a record; 0x00 ends the
// stream.
//
// The DAT directory is big-endian; the MVE stream inside is little-endian.
// Only little-endian loads appear in this file.

constexpr size_t kMveFileHeaderSize = 30;
constexpr char kMveSignature[] = "Interplay MVE File\x1A\x00";
constexpr size_t kMveSignatureLength = 20;

// Chunk opcodes this reader cares about. Everything else is skipped by its
// declared length.
constexpr unsigned int kOpcodeEndOfStream = 0x00;
constexpr unsigned int kOpcodeEndOfRecord = 0x01;
constexpr unsigned int kOpcodeSoundConfig = 0x03;
constexpr unsigned int kOpcodeAudioData = 0x08;
constexpr unsigned int kOpcodeAudioSilence = 0x09;

// The engine selects audio stream 0, so its mask bit is 1
// (`_rm_track_bit`, `movie_lib.cc:653-656`).
constexpr unsigned int kTrackBit = 1;

// An audio chunk's payload starts with a 6-byte subheader:
// `uint16 sequence, uint16 streamMask, uint16 count`.
constexpr size_t kAudioSubheaderSize = 6;

// A `0x03` payload needs three `uint16` plus a `uint32` at offset 6.
constexpr size_t kSoundConfigMinSize = 10;

// Hard ceilings. A record's declared length is a `uint16`, so 64 KiB is the
// structural maximum and this is a restatement rather than a policy.
constexpr size_t kMaxRecordPayload = 0x10000;

// Cap on SOURCE-RATE decoded audio, which is NOT the server's 8 MiB cap on
// the DEGRADED buffer. At 22050 Hz stereo 16-bit the source is 5.5x the size
// of 8 kHz mono output: `ovrintro` decodes to 10,058,032 B (9.59 MiB) and
// degrades to 1,824,586 B (1.74 MiB).
//
// Getting this wrong is not theoretical - the first version of this file
// reused the 8 MiB figure and silently refused `ovrintro`, the largest and
// most important transmission. The B2 oracle caught it. 64 MiB is a generous
// bound: the whole `ART\CUTS` set is 27.5 MB of decoded audio.
constexpr size_t kMaxDecodedBytes = 64u * 1024u * 1024u;

// Probe budget. Measured during TASK-026 step B2: across all 13 movies
// present in MASTER.DAT the `0x03` appears within the first record and the
// first accepted audio chunk within the first 2 records, at a decompressed
// offset under 3 KiB. 8 records / 256 KiB is a wide margin over that.
constexpr int kProbeMaxRecords = 8;
constexpr size_t kProbeMaxBytes = 256u * 1024u;

unsigned short loadUInt16(const unsigned char* p)
{
    return static_cast<unsigned short>(p[0] | (p[1] << 8));
}

unsigned int loadUInt32(const unsigned char* p)
{
    return static_cast<unsigned int>(p[0])
        | (static_cast<unsigned int>(p[1]) << 8)
        | (static_cast<unsigned int>(p[2]) << 16)
        | (static_cast<unsigned int>(p[3]) << 24);
}

// Walks an MVE's record/chunk structure and hands each chunk to a callback.
//
// The callback returns false to stop the walk early (the probe uses this).
// `recordLimit` and `byteLimit` bound the walk for the probe; the full read
// passes the structural maxima.
//
// Opens and closes the DAT entry itself, so callers cannot leak the handle on
// an error path.
class MveWalker {
public:
    // Returns false when the file is absent or structurally invalid. A
    // callback-requested early stop is NOT a failure.
    template <typename ChunkFn>
    bool walk(int game_movie, int recordLimit, size_t byteLimit, ChunkFn&& onChunk)
    {
        const char* name = companionMovieFileName(game_movie);
        if (name == nullptr) {
            return false;
        }

        char path[COMPAT_MAX_PATH];
        int n = snprintf(path, sizeof(path), "art\\cuts\\%s", name);
        if (n < 0 || static_cast<size_t>(n) >= sizeof(path)) {
            return false;
        }

        DB_FILE* stream = db_fopen(path, "rb");
        if (stream == nullptr) {
            return false;
        }

        bool ok = walkOpened(stream, recordLimit, byteLimit, onChunk);
        db_fclose(stream);
        return ok;
    }

private:
    template <typename ChunkFn>
    bool walkOpened(DB_FILE* stream, int recordLimit, size_t byteLimit, ChunkFn& onChunk)
    {
        unsigned char header[kMveFileHeaderSize];
        if (!readExact(stream, header, sizeof(header))) {
            return false;
        }

        // The engine's own validation, replicated verbatim rather than
        // reasoned about (`_ioReset`, `movie_lib.cc:681-710`). The three
        // numeric checks are magic constants in the original too.
        if (memcmp(header, kMveSignature, kMveSignatureLength) != 0) {
            return false;
        }

        short field14 = static_cast<short>(loadUInt16(header + 20));
        short field16 = static_cast<short>(loadUInt16(header + 22));
        short field18 = static_cast<short>(loadUInt16(header + 24));
        if (static_cast<unsigned int>(~field16 - field18) != 0xFFFFEDCCu) {
            return false;
        }
        if (field16 != 256 || field14 != 26) {
            return false;
        }

        // The file header's last 4 bytes are record 0's header.
        unsigned int nextHeader = loadUInt32(header + 26);

        size_t bytesConsumed = sizeof(header);
        std::vector<unsigned char> record;

        for (int recordIndex = 0; recordIndex < recordLimit; ++recordIndex) {
            size_t payloadLength = nextHeader & 0xFFFF;
            if (payloadLength > kMaxRecordPayload) {
                return false;
            }

            // `_ioNextRecord` reads the payload PLUS the following record's
            // 4-byte header in one go, then picks the header off the end.
            record.resize(payloadLength + 4);
            if (!readExact(stream, record.data(), record.size())) {
                return false;
            }
            nextHeader = loadUInt32(record.data() + payloadLength);

            bytesConsumed += record.size();

            size_t offset = 0;
            while (true) {
                // Chunk header must fit inside the record payload.
                if (offset + 4 > payloadLength) {
                    // Ran off the end without an end-of-record opcode.
                    return false;
                }

                unsigned int chunkHeader = loadUInt32(record.data() + offset);
                size_t chunkLength = chunkHeader & 0xFFFF;
                unsigned int opcode = (chunkHeader >> 16) & 0xFF;
                offset += 4;

                if (opcode == kOpcodeEndOfStream) {
                    return true;
                }
                if (opcode == kOpcodeEndOfRecord) {
                    break;
                }

                if (offset + chunkLength > payloadLength) {
                    return false;
                }

                if (!onChunk(chunkHeader, opcode, record.data() + offset, chunkLength)) {
                    return true;
                }

                offset += chunkLength;
            }

            if (bytesConsumed >= byteLimit) {
                // Budget spent. Not a failure - the caller decides what an
                // unfinished walk means.
                return true;
            }
        }

        return true;
    }

    static bool readExact(DB_FILE* stream, unsigned char* buffer, size_t length)
    {
        if (length == 0) {
            return true;
        }
        return db_fread(buffer, 1, length, stream) == length;
    }
};

// Decodes one accepted audio chunk's worth of output, mirroring
// `_MVE_sndAdd` + `_MVE_sndDecompS16` (`movie_lib.cc:1400-1459`, `:1812-1834`).
//
// Contract, per chunk:
//   * output is exactly `count` bytes;
//   * the predictors RE-SEED from the chunk's leading `uint32` (low 16 bits
//     left, high 16 right), which is emitted verbatim as the first output
//     sample pair;
//   * the remaining `(count - 4) / 4` pairs come from `(count - 4) / 2` input
//     bytes, one byte per sample;
//   * arithmetic is `unsigned short` wraparound. NOT clamped, NOT saturated -
//     the engine does neither, and clamping would change the sound.
//
// `source == nullptr` means silence: `count` bytes of 0x00 for 16-bit
// (`_MVE_sndAdd`'s null branch memsets 0 when `dword_6B36A0 >= 1`).
bool decodeStereoChunk(const unsigned char* source,
    size_t sourceLength,
    size_t count,
    std::vector<short>& out)
{
    if (count < 4 || (count % 4) != 0) {
        return false;
    }

    size_t pairs = (count - 4) / 4;

    if (source == nullptr) {
        out.insert(out.end(), count / 2, 0);
        return true;
    }

    // 4 seed bytes plus one input byte per sample.
    size_t needed = 4 + pairs * 2;
    if (sourceLength < needed) {
        return false;
    }

    const unsigned short* table = companionMveDeltaTable();

    unsigned short left = loadUInt16(source);
    unsigned short right = loadUInt16(source + 2);
    out.push_back(static_cast<short>(left));
    out.push_back(static_cast<short>(right));

    const unsigned char* p = source + 4;
    for (size_t i = 0; i < pairs; ++i) {
        left = static_cast<unsigned short>(left + table[*p++]);
        out.push_back(static_cast<short>(left));
        right = static_cast<unsigned short>(right + table[*p++]);
        out.push_back(static_cast<short>(right));
    }

    return true;
}

// Mono variant, mirroring `_MVE_sndDecompM16`. No Fallout cutscene uses it;
// implemented so a mono movie degrades to correct audio rather than to a
// refusal, and because leaving it out would make the format check below a
// lie.
bool decodeMonoChunk(const unsigned char* source,
    size_t sourceLength,
    size_t count,
    std::vector<short>& out)
{
    if (count < 2 || (count % 2) != 0) {
        return false;
    }

    size_t samples = (count - 2) / 2;

    if (source == nullptr) {
        out.insert(out.end(), count / 2, 0);
        return true;
    }

    size_t needed = 2 + samples;
    if (sourceLength < needed) {
        return false;
    }

    const unsigned short* table = companionMveDeltaTable();

    unsigned short value = loadUInt16(source);
    out.push_back(static_cast<short>(value));

    const unsigned char* p = source + 2;
    for (size_t i = 0; i < samples; ++i) {
        value = static_cast<unsigned short>(value + table[*p++]);
        out.push_back(static_cast<short>(value));
    }

    return true;
}

} // namespace

bool companionMveHasAudioTrack(int game_movie)
{
    bool sawSoundConfig = false;
    bool sawAcceptedChunk = false;

    MveWalker walker;
    bool ok = walker.walk(game_movie,
        kProbeMaxRecords,
        kProbeMaxBytes,
        [&](unsigned int chunkHeader, unsigned int opcode, const unsigned char* payload, size_t length) {
            (void)chunkHeader;

            if (opcode == kOpcodeSoundConfig) {
                if (length < kSoundConfigMinSize) {
                    return false;
                }
                sawSoundConfig = true;
                return true;
            }

            if (opcode == kOpcodeAudioData || opcode == kOpcodeAudioSilence) {
                if (length < kAudioSubheaderSize) {
                    return false;
                }
                if ((loadUInt16(payload + 2) & kTrackBit) != 0) {
                    sawAcceptedChunk = true;
                    // Both conditions met; nothing further to learn.
                    return false;
                }
            }

            return true;
        });

    if (!ok) {
        return false;
    }

    return sawSoundConfig && sawAcceptedChunk;
}

bool companionMveReadAudio(int game_movie, CompanionMveAudio& out)
{
    out = CompanionMveAudio{};

    bool configured = false;
    bool failed = false;

    MveWalker walker;
    bool ok = walker.walk(game_movie,
        // The structural maximum: a record count high enough that no real
        // movie reaches it, with the byte budget doing the real bounding.
        1 << 24,
        kMaxDecodedBytes * 4,
        [&](unsigned int chunkHeader, unsigned int opcode, const unsigned char* payload, size_t length) {
            if (opcode == kOpcodeSoundConfig) {
                if (length < kSoundConfigMinSize) {
                    failed = true;
                    return false;
                }

                unsigned short flags = loadUInt16(payload + 2);
                out.channels = (flags & 0x01) != 0 ? 2 : 1;
                out.bitsPerSample = (flags & 0x02) != 0 ? 16 : 8;
                out.sampleRate = loadUInt16(payload + 4);

                // 8-bit source would need a different decoder and a
                // different silence value (0x80, not 0x00). No Fallout
                // cutscene is 8-bit; refuse rather than guess.
                if (out.bitsPerSample != 16 || out.sampleRate <= 0) {
                    failed = true;
                    return false;
                }

                configured = true;
                return true;
            }

            if (opcode != kOpcodeAudioData && opcode != kOpcodeAudioSilence) {
                return true;
            }

            if (length < kAudioSubheaderSize) {
                failed = true;
                return false;
            }

            if (opcode == kOpcodeAudioSilence) {
                out.silenceChunksPresent += 1;
            }

            unsigned short streamMask = loadUInt16(payload + 2);
            if ((streamMask & kTrackBit) == 0) {
                // Skipped. Silence carries mask 0xFFFE here, which duplicates
                // the data track; 0xFFFF is the accepted one. Emitting both
                // would make this track LONGER than the engine's timeline.
                return true;
            }

            if (!configured) {
                // Audio before its configuration. The engine would have no
                // sound buffer to write into; we have no format to decode
                // with.
                failed = true;
                return false;
            }

            size_t count = loadUInt16(payload + 4);

            // The engine's own source selection, replicated exactly:
            // `v14 = payload + 6; if ((v5 >> 16) != 8) v14 = NULL;`
            // (`movie_lib.cc:983-988`). Note it compares the FULL upper half
            // of the chunk header, so a `0x08` with a non-zero version byte
            // is treated as SILENCE. That looks like an original-code quirk
            // rather than intent, but it is what plays, so it is what we
            // reproduce. Counted so a non-zero tally is visible rather than
            // silent.
            const unsigned char* source = payload + kAudioSubheaderSize;
            if ((chunkHeader >> 16) != kOpcodeAudioData) {
                if (opcode == kOpcodeAudioData) {
                    out.versionedAudioChunks += 1;
                }
                source = nullptr;
            }

            size_t sourceLength = length - kAudioSubheaderSize;

            if (out.decodedBytes + count > kMaxDecodedBytes) {
                failed = true;
                return false;
            }

            bool decoded = out.channels == 2
                ? decodeStereoChunk(source, sourceLength, count, out.samples)
                : decodeMonoChunk(source, sourceLength, count, out.samples);
            if (!decoded) {
                failed = true;
                return false;
            }

            out.decodedBytes += count;
            if (opcode == kOpcodeAudioSilence) {
                out.silenceChunksAccepted += 1;
            } else {
                out.audioChunksAccepted += 1;
            }

            return true;
        });

    if (!ok || failed || !configured || out.decodedBytes == 0) {
        out = CompanionMveAudio{};
        return false;
    }

    return true;
}

} // namespace fallout
