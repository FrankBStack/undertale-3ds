#include "ctr_adpcm_pcm.h"
#include <stddef.h>

#if defined(CTR_ADPCM_HOST) && defined(_WIN32)
#define PC_CODE
#define PC_EXPORT __declspec(dllexport)
#elif defined(CTR_ADPCM_HOST)
#define PC_CODE
#define PC_EXPORT
#else
#define PC_CODE __attribute__((noinline, noipa, section(".text.late.adpcm")))
#define PC_EXPORT PC_CODE
#endif

// Clamp to a 16-bit sample. On the 3DS one ssat; GCC's own clamp there spends two registers on the bounds, which
// the frame loop below needs (an asm statement, not __builtin_arm_ssat: that reordered this file's functions).
#if defined(CTR_ADPCM_HOST) || !defined(__arm__)
#define PC_SAT16(v) ((v) < -32768 ? -32768 : (v) > 32767 ? 32767 : (v))
#else
static inline __attribute__((always_inline)) int32_t PC_SAT16(int32_t v) {
    int32_t r;
    __asm__("ssat %0, #16, %1" : "=r"(r) : "r"(v));
    return r;
}
#endif

static inline __attribute__((always_inline)) uint16_t pc16(const uint8_t* p) {
    return (uint16_t)((uint16_t)p[0] | (uint16_t)p[1] << 8);
}

// Direct immutable views avoid a block-sized copy on the DSP callback.
PC_CODE static bool pcBlock(CtrAdpcmPcm* c, uint32_t index, bool validate) {
    uint64_t offset;
    uint32_t bytes, frames;
    if (!CtrAdpcm_blockRange(&c->info, index, &offset, &bytes, &frames) ||
        offset > c->bytes || bytes > c->bytes - offset) return false;
    uint32_t payload = ((frames + 13u) / 14u) * 8u;
    const uint8_t* p = c->data + (size_t)offset;
    for (uint32_t ch = 0; ch < c->info.channels; ch++, p += payload + 8u) {
        if (validate) {
            if (pc16(p + 6) || pc16(p) != p[8] ||
                (index == 0 && (pc16(p + 2) || pc16(p + 4)))) return false;
            for (uint32_t i = 0; i < payload; i += 8u) if (p[8u + i] >= 0x80u) return false;
        }
        c->channel[ch] = p + 8;
        c->history[ch][0] = (int16_t)pc16(p + 2);
        c->history[ch][1] = (int16_t)pc16(p + 4);
    }
    c->blockFirst = index * CTR_ADPCM_BLOCK_FRAMES;
    c->blockFrames = frames;
    c->position = c->blockFirst;
    return true;
}

PC_EXPORT bool CtrAdpcmPcm_open(CtrAdpcmPcm* out, const void* data, uint32_t bytes) {
    if (out == NULL || data == NULL) return false;
    CtrAdpcmPcm c = {0};
    if (!CtrAdpcm_parse(data, bytes, bytes, &c.info)) return false;
    c.data = data;
    c.bytes = bytes;
    for (uint32_t index = 0; index < c.info.blocks; index++)
        if (!pcBlock(&c, index, true)) return false;
    if (!pcBlock(&c, 0, false)) return false;
    c.ready = true;
    *out = c;
    return true;
}

// One ADPCM frame (a header byte, then 14 nibbles) at a time: its predictor, scale and data are read once into
// registers, not once per sample (cbcut B, from audiofix item 3). The samples are those of the per-sample decoder
// this replaced, for every input (tools/audio/test_pcm.py; cbcut also diffed both on every UT pack sound):
// - w holds the frame's 14 nibbles from the top, high nibble of each byte first; its top 4 bits, shifted down with
//   their sign, are the residual the old code took from packed >> 4 or packed & 15, minus 16 from 8 up.
// - residual * 2^scale * 2048 is residual << (scale + 11), at most 2^29 in size, so it and + 1024 fit in 32 bits.
// - The old floor division (sum / 2048 rounded toward minus infinity, by sign) is sum >> 11. The history is always
//   16-bit (pcBlock's int16 values, then clamped samples), so |sum| < 2^32 and sum >> 11 fits in 32 bits before
//   the same clamp to -32768..32767 (ssat on the 3DS).
// - A skip (out NULL) writes each sample to a local that is never read: the history alone carries on.
PC_CODE static void pcFrames(CtrAdpcmPcm* c, uint32_t count, int16_t* out) {
    uint32_t first = c->position - c->blockFirst, channels = c->info.channels, step = out != NULL ? channels : 0;
    int16_t skipped;
    for (uint32_t ch = 0; ch < channels; ch++) {
        int16_t* o = out != NULL ? out + ch : &skipped;
        const uint8_t* f = c->channel[ch] + (first / 14u) * 8u;
        int32_t h0 = c->history[ch][0], h1 = c->history[ch][1];
        for (uint32_t nibble = first % 14u, left = count; left; f += 8, nibble = 0) {
            uint32_t n = left < 14u - nibble ? left : 14u - nibble;
            left -= n;
            const int16_t* k = &c->info.coefficients[ch][(f[0] >> 4) * 2u];
            int32_t c0 = k[0], c1 = k[1];
            uint32_t shift = (f[0] & 15u) + 11u;
            uint32_t a = (uint32_t)f[0] << 24 | (uint32_t)f[1] << 16 | (uint32_t)f[2] << 8 | f[3];
            uint32_t b = (uint32_t)f[4] << 24 | (uint32_t)f[5] << 16 | (uint32_t)f[6] << 8 | f[7];
            uint64_t w = (uint64_t)(a << 8 | b >> 24) << 32 | (uint32_t)(b << 8);
            w <<= nibble * 4u;
            do {
                int32_t residual = (int32_t)(uint32_t)(w >> 32) >> 28;
                w <<= 4;
                int64_t sum = (int64_t)c0 * h0 + (int64_t)c1 * h1 + (int32_t)(((uint32_t)residual << shift) + 1024u);
                int32_t value = (int32_t)(sum >> 11);
                value = PC_SAT16(value);
                h1 = h0;
                h0 = value;
                *o = (int16_t)value;
                o += step;
            } while (--n);
        }
        c->history[ch][0] = h0;
        c->history[ch][1] = h1;
    }
    c->position += count;
}

PC_EXPORT bool CtrAdpcmPcm_read(CtrAdpcmPcm* c, uint32_t first, uint32_t count,
                               int16_t* out, uint32_t capacity, uint32_t* decoded) {
    if (decoded != NULL) *decoded = 0;
    if (c == NULL || !c->ready || first > c->info.frames || count > c->info.frames - first ||
        count > capacity || (count && out == NULL)) return false;
    if (count == 0) return true;
    uint32_t index = first / CTR_ADPCM_BLOCK_FRAMES;
    if (c->position > first || c->blockFirst / CTR_ADPCM_BLOCK_FRAMES != index)
        if (!pcBlock(c, index, false)) return false;
    uint32_t work = first - c->position;
    if (work) pcFrames(c, work, NULL);
    while (count) {
        if (c->position == c->blockFirst + c->blockFrames)
            if (!pcBlock(c, c->position / CTR_ADPCM_BLOCK_FRAMES, false)) return false;
        uint32_t n = c->blockFirst + c->blockFrames - c->position;
        if (n > count) n = count;
        pcFrames(c, n, out);
        out += (size_t)n * c->info.channels;
        count -= n;
        work += n;
    }
    if (decoded != NULL) *decoded = work;
    return true;
}
