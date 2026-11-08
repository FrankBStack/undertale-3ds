// Seam copies (change drawbatch; UNDERTALE only): one texture for a page draw whose texels span cache tiles.
// z_seamcopy.c keeps the copies; ctr_renderer.c's end draws from them (it says why). The copies live in their own
// translation unit so that ctr_renderer.c's code and static data keep their places (GCC compiles a unit's functions,
// and places their static guards, in an order its call graph decides).
#pragma once

#include <3ds.h>
#include <citro3d.h>
#include <stdbool.h>
#include <stdint.h>

#include "ctr_textures.h"

typedef struct {
    CtrPage* page; // nullptr: a free slot
    int32_t x0, y0, x1, y1; // the page texels it holds, each part's ring besides
    int32_t tx0, ty0, ntx, nty; // its tiles: ntx x nty (up to 2 x 2) from tile (tx0, ty0)
    const void* data[2][2]; // each tile's texels [row][column] when copied; nullptr for a clear tile, left out
    uint32_t usedFrame, builtFrame, bytes;
    uint32_t hitsFrame, hitsNow, hitsLast; // draws from it in frame hitsFrame, and in the frame before that one
    uint8_t format;
    bool stale; // a tile it copied changed, or VRAM is wanted: not drawn from again
    bool checked; // test builds: its VRAM is out of the CPU's cache
    C3D_Tex tex;
} SeamCopy;

// The copy holding page texels [x0, x1) x [y0, y1) (the draw's bounds, rounded out) for a draw in frame `frame`, made
// now if need be; nullptr if there is none to be had (then the draw goes as before).
SeamCopy* CtrSeam_lookup(CtrTextureCache* cache, CtrPage* page, uint32_t frame, float x0, float y0, float x1, float y1);

// Something else wants VRAM: no copy is drawn from again, and they all go within a few frames. ctr_renderer.c's VRAM
// wraps get to it through CtrSeam_texInit (when a VRAM texture finds no room) and CtrSeam_renderTarget.
void CtrSeam_vramWanted(void);
bool CtrSeam_texInit(C3D_Tex* tex, C3D_TexCube* cube, C3D_TexInitParams p);
C3D_RenderTarget* CtrSeam_renderTarget(int width, int height, GPU_COLORBUF colorFmt, C3D_DEPTHTYPE depthFmt);

// The most texture memory the copies have held at once, in bytes.
uint32_t CtrSeam_peakBytes(void);

// CtrTextures_beginFrame, then the copies' care at a frame's start: idle and changed ones freed. ctr_renderer.c calls it
// in CtrTextures_beginFrame's place.
void CtrSeam_beginFrame(CtrTextureCache* cache, uint32_t frame);

// Frees the copies of `cache`, then destroys it (the next link of CtrTextures_destroy's wrap chain).
void CtrSeam_destroy(CtrTextureCache* cache);

// A room change: frees the copies of `cache`, then CtrTextures_prefetchRoom. ctr_renderer.c calls it in that one's place.
void CtrSeam_prefetchRoom(CtrTextureCache* cache, Runner* runner);

// Whether a draw should be looked up (z_seamcopy.c says why): its region was drawn before in this frame, or a copy held
// covers it, and it isn't known to fit no copy. A draw asks once, just before its CtrSeam_lookup, with a key its region
// always gives: first CtrSeam_worthAsking, which most draws go no further than (the hook can tail-call on), then
// !CtrSeam_knownNoFit, then CtrSeam_demand, with (x, y) a page texel of its own. CtrSeam_noCopy: the hook found this
// region can have no copy, as CtrSeam_lookup does with others.
#define CTR_SEAM_SEEN 32u // regions remembered as drawn in this frame (a power of two)
#define CTR_SEAM_NOFIT 32u // regions remembered as fitting no copy (a power of two; the bss this takes keeps the program within its last page on S4)
#define CTR_SEAM_NOFIT_SHIFT 27 // a hash's top bits that choose among them
#define CTR_SEAM_NOFIT_FRAMES 32u // for this long
typedef struct {
    uint32_t* seenNow; // if the region of the draw last asked about was drawn before in this frame, its place in seen
    uint32_t* seenAt; // its place in seen, drawn before or not
    uint32_t keyNow; // that draw's key
    uint32_t held; // the bytes of copies held
    uint32_t seen[CTR_SEAM_SEEN]; // by hash of region and frame, that hash: regions drawn in this frame (last bit flipped: refused)
    struct {
        uint32_t key, frame; // this region (its key) was found to fit no copy in this frame
    } noFit[CTR_SEAM_NOFIT];
} CtrSeamDrawn;
extern CtrSeamDrawn CtrSeam_drawn;

static inline __attribute__((always_inline)) bool CtrSeam_worthAsking(uint32_t frame, uint32_t key) {
    uint32_t hash = (key ^ frame) * 0x9e3779b1u;
    uint32_t* seen = &CtrSeam_drawn.seen[hash >> 27];
    uint32_t was = *seen ^ hash; // 0: drawn before in this frame; 1: and refused
    if (was == 1u) return false;
    if (was != 0) {
        *seen = hash;
        if (CtrSeam_drawn.held == 0) return false;
    }
    CtrSeam_drawn.seenAt = seen;
    CtrSeam_drawn.seenNow = was == 0 ? seen : nullptr;
    CtrSeam_drawn.keyNow = key;
    return true;
}
static inline __attribute__((always_inline)) bool CtrSeam_knownNoFit(uint32_t frame) {
    uint32_t key = CtrSeam_drawn.keyNow;
    uint32_t i = (key * 0x9e3779b1u) >> CTR_SEAM_NOFIT_SHIFT;
    // The frame it was noted in, and any more than CTR_SEAM_NOFIT_FRAMES after it: asked about.
    if (CtrSeam_drawn.noFit[i].key != key || CTR_SEAM_NOFIT_FRAMES <= frame - CtrSeam_drawn.noFit[i].frame - 1u) return false;
    *CtrSeam_drawn.seenAt ^= 1u;
    return true;
}
bool CtrSeam_covered(int32_t x, int32_t y);
static inline __attribute__((always_inline)) bool CtrSeam_demand(int32_t x, int32_t y) {
    return CtrSeam_drawn.seenNow != nullptr || CtrSeam_covered(x, y);
}
static inline __attribute__((always_inline)) void CtrSeam_noCopy(uint32_t frame) {
    uint32_t key = CtrSeam_drawn.keyNow;
    uint32_t i = (key * 0x9e3779b1u) >> CTR_SEAM_NOFIT_SHIFT;
    CtrSeam_drawn.noFit[i].key = key;
    CtrSeam_drawn.noFit[i].frame = frame;
    if (CtrSeam_drawn.seenNow != nullptr) *CtrSeam_drawn.seenNow ^= 1u;
}
