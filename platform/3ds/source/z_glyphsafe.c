// glyphsafe (change auditfixe, DEEP-02, both games): the FPS counter and the first-boot hint never read a font page or
// tile that isn't there.
//
// argui's painter draws its text with two samplers that read the font's texels straight from the texture cache:
// arguiSampleGlyph (ctr_argui.c, inlined into arguiDrawText, exported as CtrFps_drawText) and fps75Texel
// (ctr_optmenu.c, under CtrFpsbox_drawDigits). Each takes the page from CtrTextures_acquire and, for a tile that
// isn't resident, calls CtrTextures_ensureTiles, then reads the tile's texels without checking either. acquire returns
// null while a page's layout can't be loaded (out of memory: page->retryFrame; a bad page: page->failed), and a tile
// stays not resident when its load fails or the tile is fully transparent (never loaded): the painter then read
// through a null page or a null texel pointer (a data abort at the swap). optTexel, the options menu's copy, already
// checks both (ctr_optmenu.c).
//
// The samplers' code stays as it is (late code that must not move or change size). Their callers in other files
// (ctr_fps_clock.c, ctr_hintpos.c) reach them through the linker instead (-Wl,--wrap=CtrFps_drawText,
// --wrap=CtrFpsbox_drawDigits, CMakeLists.txt): first glyphsafeReady goes over every texel the sampler is about to
// read, char by char, row by row, as the sampler does, acquiring each page and loading each tile that isn't resident
// with the same calls in the same order; then it checks all of them again without loading anything (one load could
// have pushed out a tile an earlier char needs). Only when every page and tile is there does the text get drawn,
// and the sampler then loads nothing. Otherwise that text is left out of this one frame (each frame tries again; the
// sampler would have faulted). So when everything loads, the calls and the pixels are the ones the sampler made
// alone. Nothing here waits for anything the sampler didn't already wait for.
//
// The one exception: a frame in which loading one of the text's tiles pushed out another it needs (memory full)
// leaves the text out even where the sampler alone could have drawn it (it would have loaded the tile again), since
// that second load is the one that can fail.
//
// UNDERTALE reaches the samplers only through these two names. DELTARUNE's own options page (arguiDrawOptions,
// ctr_argui.c) also calls arguiDrawText directly inside ctr_argui.c, which this doesn't cover (DELTARUNE isn't built
// or tested here).
//
// Late code (late_reserve.ld: .text_glyphsafe after inisafe), named outside .text.late.* so no catch-all takes it
// first: glyphsafeReady, and two 8-instruction wrappers in assembly. No statics. Host tests build the C wrappers
// below instead (tools/analysis/test_glyph_fallback.py).
#include <stdbool.h>
#include <stdint.h>

#include "ctr_textures.h"
#include "data_win.h"

#define GLYPHSAFE_CODE __attribute__((noinline, optimize("Os"), section(".text_glyphsafe")))

// argui's state (ctr_argui.c, a global): the same layout (as ctr_optmenu.c and z_argbind.c declare it).
typedef struct {
    uint8_t cfg[3];
    bool menuIsOpen;
    uint8_t sx;
    uint8_t sy;
    uint8_t adv;
    bool rgb565;
    char fpsBuf[3];
    uint16_t hintFrames;
    uint16_t fpsFrames;
    int16_t assetIds[5]; // sndMove, sndSelect, fntSmall, fntTheme, sprHeartSmall
    uint32_t fpsVb;
    void* fb;
    CtrTextureCache* texCache;
    void* audio;
} ArguiState;

extern ArguiState CtrArgui_state;

void __real_CtrFps_drawText(int32_t x, int32_t y, const char* text, uint32_t colour);
void __real_CtrFpsbox_drawDigits(int32_t x, int32_t y, const char* text, uint32_t colour);

// Whether the sampler can read every texel of text. arguiSampleGlyph (digits false) reads the counter's font
// (assetIds[2]) in cells of 6 columns, or with the options menu open the menu's (assetIds[3]) in cells of 9 columns
// that start 4 rows down the glyph; fps75Texel (digits true) always reads the counter's font in cells of 6. The cells
// are 12 rows; a texel outside the glyph, or a char with no glyph (the console font), reads no page. arguiSampleGlyph
// draws char 1 as the small heart sprite instead: only the options page draws it, which calls arguiDrawText inside
// ctr_argui.c, never through these names, so a heart here just leaves the text out.
__attribute__((used)) GLYPHSAFE_CODE static bool glyphsafeReady(const char* text, bool digits) {
    CtrTextureCache* cache = CtrArgui_state.texCache;
    if (cache == nullptr) return false;
    const DataWin* dw = cache->dataWin;
    uint32_t menu = digits ? 0u : CtrArgui_state.menuIsOpen;
    int32_t width = menu ? 9 : 6, rise = (int32_t) (menu << 2);
    int32_t fid = CtrArgui_state.assetIds[2u + menu];
    const Font* f = fid >= 0 ? &dw->font.fonts[fid] : nullptr; // none: every char is the console font's
    for (uint32_t pass = 0; 2u > pass; pass++) {
        for (const char* s = text; *s != '\0'; s++) {
            uint8_t ch = (uint8_t) *s;
            if (!digits && ch == 1u) return false;
            const FontGlyph* gl = f != nullptr ? f->glyphLUT[ch] : nullptr;
            if (gl == nullptr || f->tpagIndex < 0) continue;
            // The texels read, in the glyph's coordinates (inclusive).
            int32_t x0 = gl->offset < 0 ? -gl->offset : 0, x1 = width - 1 - gl->offset, y1 = 11 + rise;
            if (x1 > gl->sourceWidth - 1) x1 = gl->sourceWidth - 1;
            if (y1 > gl->sourceHeight - 1) y1 = gl->sourceHeight - 1;
            if (x0 > x1 || rise > y1) continue;
            const TexturePageItem* tpag = &dw->tpag.items[f->tpagIndex];
            CtrPage* page = CtrTextures_acquire(cache, (uint32_t) tpag->texturePageId);
            if (page == nullptr) return false;
            int32_t px = tpag->sourceX + gl->sourceX, py = tpag->sourceY + gl->sourceY;
            // The sampler meets the tiles in this order: row by row of texels, so tile row by tile row.
            for (int32_t ty = (py + rise) >> 8; (py + y1) >> 8 >= ty; ty++) {
                for (int32_t tx = (px + x0) >> 8; (px + x1) >> 8 >= tx; tx++) {
                    const CtrTile* tile = &page->tiles[ty * page->tilesX + tx];
                    if (!tile->valid && pass == 0u) CtrTextures_ensureTiles(cache, page, tx, ty, tx, ty);
                    if (!tile->valid) return false;
                }
            }
        }
    }
    return true;
}

#if defined(__arm__)
// Each wrapper keeps r0-r3 (x, y, text, colour) and lr as its caller left them, asks glyphsafeReady about the text
// (r2), and then returns or branches to the sampler's function. Six words pushed: sp stays 8-byte aligned. Declared
// without parameters: only the assembly reads them.
#define GLYPHSAFE_WRAP(name, digits)                                                                                  \
    void __wrap_##name(void);                                                                                         \
    __attribute__((naked, noinline, section(".text_glyphsafe"))) void __wrap_##name(void) {                          \
        __asm__("push {r0-r3, ip, lr}\n\t"                                                                            \
                "mov r0, r2\n\t"                                                                                      \
                "mov r1, #" #digits "\n\t"                                                                            \
                "bl glyphsafeReady\n\t"                                                                               \
                "cmp r0, #0\n\t"                                                                                      \
                "pop {r0-r3, ip, lr}\n\t"                                                                             \
                "bxeq lr\n\t"                                                                                         \
                "b __real_" #name "\n");                                                                              \
    }
#else
#define GLYPHSAFE_WRAP(name, digits)                                                                                  \
    void __wrap_##name(int32_t x, int32_t y, const char* text, uint32_t colour);                                     \
    void __wrap_##name(int32_t x, int32_t y, const char* text, uint32_t colour) {                                    \
        if (glyphsafeReady(text, digits)) __real_##name(x, y, text, colour);                                          \
    }
#endif
GLYPHSAFE_WRAP(CtrFps_drawText, 0)
GLYPHSAFE_WRAP(CtrFpsbox_drawDigits, 1)
