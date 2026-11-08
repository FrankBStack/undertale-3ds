// change thinrule (first update, UNDERTALE): whole rows for shrunken fine sprites.
//
// Smart smoothing averages a fine sprite only at exactly two texels a pixel; any other shrink fell back to a linear
// blur, so Madjick's one-texel white hem (his robe sprite, drawn 0.8-1.0 pixels a texel as he breathes) was grey.
// Between 2/3 and 1 pixel a texel the fallback now draws the items the build lists sharp and nearest, as PC does, and
// gives a listed row (bright detail its neighbours lack) the pixel of its dimmer neighbour on the frames whose shrink
// would skip it (ctr_renderer.c, "Whole rows"). The build works the list out from the game data
// (tools/aot/thinrule.py, through fontverdict.py's build mode) into romfs:/fonts/<data.win folder>.dttr: "DTTR",
// version 2, the CtrPackKey, the entry count, the rescue byte count and a CRC-32 of the rest of the file; then 4 bytes
// per item (u16 item, u16 offset of its rescues, 0xFFFF for none), then the rescue bytes.
//
// Read once per data.win under Smart smoothing into Thinrule_table (z_thinrule.h), with each item's page and source
// corner from this data.win's own TPAG as its key: right after the font verdicts at a room change, and when the
// options menu opens or closes with changes (the same two wrap chains as z_itemverdict.c, ctr_wrap_chain.h, each the
// link after itemverdict's). A switch away from Smart lets the table go. Any failure leaves no table (every fallback
// draw blurred, as before); a missing, stale, short or damaged (CRC-32) file is tried once per data.win (a damaged one
// logged once a session: a changed rescue byte can still be in range), and without memory for the read
// the next chance tries again. Late code only (platform/3ds/late_reserve.ld): .text_thinrule, its constants in
// .rodata.thinrule_in_text, its statics in .bss.thinrule_late, all named outside the late catch-alls and appended.
#include <3ds.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "common.h"
#include "ctr_benchromfs.h"
#include "ctr_memory.h"
#include "ctr_texture_pack.h"
#include "ctr_wrap_chain.h"
#include "data_win.h"
#include "log.h"
#include "renderer.h"
#include "z_thinrule.h"

#define TR_LATE __attribute__((noinline, section(".text_thinrule")))
#define TR_RODATA __attribute__((aligned(4), section(".rodata.thinrule_in_text")))
#define TR_MAGIC 0x52545444u // "DTTR"
#define TR_VERSION 2u
#define TR_HEADER 36

// z_itemverdict.c's: ctr_renderer.c's Smartiv_layout, for display.smoothing and SMOOTHING_SMART.
enum { TRL_SMOOTHING = 8, TRL_SMART = 9 };
extern const uint32_t Smartiv_layout[10];

static const char trPath[] TR_RODATA = "romfs:/fonts/%s.dttr";
static const char trMount[] TR_RODATA = "romfs";
static const char trMode[] TR_RODATA = "rb";
static const char trLog[] TR_RODATA = "Smart smoothing: %lu whole-row items (%lu B) from %s in %lu ms\n";
static const char trBadSum[] TR_RODATA = "Smart smoothing: %s fails its CRC-32, whole rows off\n";
// CRC-32 (zlib's, reflected 0xEDB88320) a nibble at a time.
static const uint32_t trCrcNibble[16] TR_RODATA = { 0x00000000u, 0x1DB71064u, 0x3B6E20C8u, 0x26D930ACu, 0x76DC4190u, 0x6B6B51F4u,
                                                    0x4DB26158u, 0x5005713Cu, 0xEDB88320u, 0xF00F9344u, 0xD6D6A3E8u, 0xCB61B38Cu,
                                                    0x9B64C2B0u, 0x86D3D2D4u, 0xA00AE278u, 0xBDBDF21Cu };

bool CtrPack_romfsName(char* name, size_t size);
void Thinrule_fontVerdicts(Renderer* renderer);
uint32_t Thinrule_caps(Renderer* renderer);
void __real_CtrRenderer_loadFontVerdicts(Renderer* renderer);
uint32_t __real_CtrRenderer_getDisplayCaps(Renderer* renderer);

ThinruleTable Thinrule_table __attribute__((section(".bss.thinrule_late")));

// The data.win the table (or the last failed try) was for; tried is false while no try counts (none yet, after a
// switch away from Smart, or without memory last time).
static struct {
    uint64_t timestamp;
    uint32_t gameId, dataWinSize;
    bool tried;
    bool warned; // a damaged table was logged (once a session)
} trDone __attribute__((section(".bss.thinrule_late")));

static TR_LATE void trDrop(void) {
    void* block = (void*) Thinrule_table.bits;
    Thinrule_table.count = 0;
    Thinrule_table.bits = nullptr;
    Thinrule_table.entries = nullptr;
    Thinrule_table.bytes = nullptr;
    Thinrule_table.size = 0;
    free(block);
}

// The file's entries, read into the second half of the entry array, become the runtime entries in place (entry i is
// read before it is written, and its 8 bytes never reach file entry i + 1), then are sorted by key: the build writes
// them in key order, so the insertion sort only checks that unless the TPAG differs; each sets its bit in bits (cleared
// first). Returns false for a bad file.
static TR_LATE bool trEntries(DataWin* dw, uint32_t* bits, uint8_t* block, uint32_t count, uint32_t size) {
    ThinruleEntry* e = (ThinruleEntry*) block;
    const uint8_t* file = block + count * 4;
    const uint8_t* bytes = block + count * sizeof(ThinruleEntry);
    for (uint32_t i = 0; count > i; i++) {
        uint16_t item, off;
        memcpy(&item, file + i * 4, 2);
        memcpy(&off, file + i * 4 + 2, 2);
        ThinruleEntry out = { 0xFFFFFFFFu, THINRULE_NONE, 0, 0 };
        if (dw->tpag.count > item) {
            const TexturePageItem* t = &dw->tpag.items[item];
            if (0 <= t->texturePageId && 256 > t->texturePageId && 4096 > t->sourceX && 4096 > t->sourceY && 256 > t->sourceWidth &&
                256 > t->sourceHeight) {
                out.key = (uint32_t) t->texturePageId << 24 | (uint32_t) t->sourceY << 12 | t->sourceX;
                out.w = (uint8_t) t->sourceWidth;
                out.h = (uint8_t) t->sourceHeight;
                uint32_t bit = thinruleHash((uint32_t) t->sourceX, (uint32_t) t->sourceY);
                bits[bit >> 5] |= 1u << (bit & 31);
            }
        }
        if (off != THINRULE_NONE) {
            if ((uint32_t) off + 2 > size || (uint32_t) off + 2 + bytes[off] + bytes[off + 1] > size) return false;
            out.off = off;
        }
        e[i] = out;
    }
    for (uint32_t i = 1; count > i; i++) {
        ThinruleEntry v = e[i];
        uint32_t j = i;
        for (; j > 0 && e[j - 1].key > v.key; j--) e[j] = e[j - 1];
        e[j] = v;
    }
    return true;
}

// The running CRC-32 (not inverted) after n more bytes.
static TR_LATE uint32_t trCrc(uint32_t crc, const uint8_t* p, uint32_t n) {
    for (uint32_t i = 0; n > i; i++) {
        crc ^= p[i];
        crc = (crc >> 4) ^ trCrcNibble[crc & 15];
        crc = (crc >> 4) ^ trCrcNibble[crc & 15];
    }
    return crc;
}

// Returns true when the try counts (loaded, or no usable table for this data.win), false to try again later.
static TR_LATE bool trLoad(DataWin* dw) {
    char file[96], folder[64];
    if (!CtrPack_romfsName(folder, sizeof(folder))) return true;
    snprintf(file, sizeof(file), trPath, folder);
    FILE* f = R_SUCCEEDED(CtrRomfs_init(trMount)) ? fopen(file, trMode) : nullptr;
    if (f == nullptr) return true;
    uint64_t t0 = svcGetSystemTick();
    setvbuf(f, nullptr, _IONBF, 0);
    uint8_t head[TR_HEADER];
    uint32_t magic = 0, version = 0, winSize = 0, gameId = 0, count = 0, size = 0, sum = 0;
    uint64_t timestamp = 0;
    bool ok = fread(head, 1, sizeof(head), f) == sizeof(head), counts = true;
    if (ok) {
        memcpy(&magic, head, 4);
        memcpy(&version, head + 4, 4);
        memcpy(&winSize, head + 8, 4);
        memcpy(&gameId, head + 12, 4);
        memcpy(&timestamp, head + 16, 8);
        memcpy(&count, head + 24, 4);
        memcpy(&size, head + 28, 4);
        memcpy(&sum, head + 32, 4);
        CtrPackKey key = CtrPack_keyFor(dw);
        ok = magic == TR_MAGIC && version == TR_VERSION && winSize == key.dataWinSize && gameId == key.gameId && timestamp == key.timestamp &&
             count != 0 && 0x10000 > count && 0x10000 > size;
    }
    uint8_t* block = nullptr;
    if (ok) {
        // Without the reliever or linear memory, as the item verdicts' read: no packed texture is let go for this.
        bool relief = CtrMemory_allowRelief(false);
        block = malloc(THINRULE_BIT_BYTES + count * sizeof(ThinruleEntry) + size);
        CtrMemory_allowRelief(relief);
        counts = block != nullptr;
        uint8_t* entries = counts ? block + THINRULE_BIT_BYTES : nullptr;
        if (counts) memset(block, 0, THINRULE_BIT_BYTES);
        ok = counts && fread(entries + count * 4, 4, count, f) == count &&
             (size == 0 || fread(entries + count * sizeof(ThinruleEntry), 1, size, f) == size);
        // The header before the CRC, the file's entries, the rescues: as written, before trEntries converts them.
        uint32_t crc = ok ? trCrc(0xFFFFFFFFu, head, 32) : 0;
        if (ok) crc = trCrc(trCrc(crc, entries + count * 4, count * 4), entries + count * sizeof(ThinruleEntry), size);
        if (ok && ~crc != sum) {
            if (!trDone.warned) logInfo(trBadSum, file);
            trDone.warned = true;
            ok = false;
        }
        ok = ok && trEntries(dw, (uint32_t*) block, entries, count, size);
    }
    fclose(f);
    if (!ok) {
        free(block);
        return counts;
    }
    Thinrule_table.bytes = block + THINRULE_BIT_BYTES + count * sizeof(ThinruleEntry);
    Thinrule_table.size = size;
    Thinrule_table.entries = (const ThinruleEntry*) (block + THINRULE_BIT_BYTES);
    Thinrule_table.count = count;
    Thinrule_table.bits = (const uint32_t*) block;
    logInfo(trLog, (unsigned long) count, (unsigned long) (THINRULE_BIT_BYTES + count * sizeof(ThinruleEntry) + size), file,
            (unsigned long) ((svcGetSystemTick() - t0) / (SYSCLOCK_ARM11 / 1000)));
    return true;
}

static TR_LATE void trEnsure(Renderer* renderer) {
    if (renderer == nullptr) return;
    DataWin* dw = renderer->dataWin;
    if (dw == nullptr || *((const uint8_t*) renderer + Smartiv_layout[TRL_SMOOTHING]) != Smartiv_layout[TRL_SMART]) {
        // Not under Smart: nothing draws from the table.
        if (Thinrule_table.entries != nullptr) trDrop();
        trDone.tried = false;
        return;
    }
    CtrPackKey key = CtrPack_keyFor(dw);
    if (trDone.tried && key.timestamp == trDone.timestamp && key.dataWinSize == trDone.dataWinSize && key.gameId == trDone.gameId) return;
    if (Thinrule_table.entries != nullptr) trDrop();
    trDone.timestamp = key.timestamp;
    trDone.dataWinSize = key.dataWinSize;
    trDone.gameId = key.gameId;
    trDone.tried = trLoad(dw);
}

// The CtrRenderer_loadFontVerdicts chain's link after itemverdict's (ctr_wrap_chain.h), at each room change.
TR_LATE void Thinrule_fontVerdicts(Renderer* renderer) {
    __real_CtrRenderer_loadFontVerdicts(renderer);
    trEnsure(renderer);
}

// The display caps query's link after itemverdict's (ctr_wrap_chain.h): when the options menu opens, and when it
// closes with changes.
TR_LATE uint32_t Thinrule_caps(Renderer* renderer) {
    uint32_t caps = __real_CtrRenderer_getDisplayCaps(renderer);
    trEnsure(renderer);
    return caps;
}
