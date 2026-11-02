// redpix: UT cold conversion only. Both worker packing and uncached-image loads use this wrapper.
// The old converter remains in its original slot; there is no steady-state per-frame hook or allocation.
#include "ctr_texture_pack.h"

#if (defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)) || defined(CTRPORT_TEXPREP_REDPIX)
#include <string.h>
#ifdef CTRPORT_TEXPREP_REDPIX
extern bool texprepUtCache;
#endif

static inline uint32_t load32(const uint8_t* p) {
    uint32_t v;
    memcpy(&v, p, 4);
    return v;
}

static inline uint32_t mortonOffset(uint32_t x, uint32_t y) {
    return (x & 1) | ((y & 1) << 1) | ((x & 2) << 1) | ((y & 2) << 2) | ((x & 4) << 2) | ((y & 4) << 3);
}

// Steam and GOG 1.08 normal/hurt heads. Full source fingerprints guard every rectangle,
// including both pieces of Steam's hurt head across the x=1536 tile boundary.
static const struct { uint16_t x, y; uint32_t hash; } heads[]
    __attribute__((section(".rodata.late.redpix"))) = {
        {1562, 1142, 0x32bc35cfu}, {1506, 1138, 0x26712601u},
        {1630, 1118, 0x32bc35cfu}, {1222, 1402, 0x26712601u},
    };

__attribute__((noinline, section(".text.late.redpix")))
void CtrPack_convertTileRedpix(void* dst, const CtrPageLayout* layout, int32_t tx, int32_t ty, const uint8_t* rows) {
    CtrPack_convertTile(dst, layout, tx, ty, rows);
#ifdef CTRPORT_TEXPREP_REDPIX
    if (!texprepUtCache) return;
#endif
    // Mitigation only: the hardware mechanism exposing hidden RGB is still under investigation.
    // Other sprites, opaque texels, format selection and the source decode buffer remain unchanged.
    if (layout->width != 2048 || layout->height != 2048 || layout->tileW != 256 || layout->tileH != 256 ||
        (ty != 4 && ty != 5)) return;
    CtrTileFormat format = layout->formats[ty * layout->tilesX + tx];
    if (format != CTR_TILE_RGBA8 && format != CTR_TILE_RGBA5551) return;
    for (unsigned n = 0; n < sizeof(heads) / sizeof(heads[0]); n++) {
        int sx = heads[n].x, sy = heads[n].y;
        if (ty != sy / 256 || tx < sx / 256 || tx > (sx + 50) / 256) continue;
        uint32_t hash = 2166136261u;
        for (int y = sy % 256; y < sy % 256 + 38; y++) {
            const uint8_t* p = rows + ((size_t) y * 2048 + sx) * 4;
            for (int x = 0; x < 51; x++, p += 4) hash = (hash ^ load32(p)) * 16777619u;
        }
        if (hash != heads[n].hash) continue;
        int first = sx > tx * 256 ? sx - tx * 256 : 0;
        int end = sx + 51 < (tx + 1) * 256 ? sx + 51 - tx * 256 : 256;
        for (int y = sy % 256; y < sy % 256 + 38; y++) {
            for (int x = first; x < end; x++) {
                size_t i = ((size_t) (y >> 3) * 32 + (x >> 3)) * 64 + mortonOffset(x & 7, y & 7);
                if (format == CTR_TILE_RGBA8) {
                    uint32_t* p = (uint32_t*) dst + i;
                    if ((*p & 255u) == 0) *p = 0;
                } else {
                    uint16_t* p = (uint16_t*) dst + i;
                    if ((*p & 1u) == 0) *p = 0;
                }
            }
        }
    }
}
#endif
