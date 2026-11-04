// symkeep (change auditfixe, SCOURT5-003, R193, UNDERTALE): symmetric halving's copies never move while a batch draws
// them.
//
// ctr_renderer.c keeps symmetric halving's half-width copies in one growing array (CtrRenderer.symTex, stb_ds), and
// symCopy hands out &symTex[k]. The pending batch keeps that pointer (batchTex, batchTexes, held batches) until it is
// drawn. A sprite drawn from a copy followed by the first draw of another symmetric item, with nothing between that
// draws the batch, grew the array while the batch still pointed into it: at the 5th, 9th, 17th, ... 129th copy,
// symMakeCopy's CTR_ARRAY_PUT reallocates, the block can move, and the next emitQuad's flushBatch set the filter of
// and bound the texture through the freed block. UNDERTALE leaves 294 of its 6550 items to symCopy (the build's table,
// z_symverdict.c), so a long session crosses those counts.
//
// Two parts, both late code only (late_reserve.ld: .text_symkeep, .bss.symkeep_late); ctr_renderer.c is unchanged:
// - symCopy makes at most SYM_COPIES_MAX copies (a renderer at that count draws every new item plain), so an array
//   that holds that many from the start never grows. At each room change (the CtrRenderer_loadFontVerdicts chain's
//   symverdict link, reached through -Wl,--wrap=CtrRenderer_chainFontVerdictsSymverdict), a renderer whose array is
//   still empty gets that capacity: 256 x 24 B, once per renderer. The copies, their order and every draw are as
//   before; only where the array lives changes.
// - Wherever the array would still grow (that reserve found no memory, or copies were made before the first room
//   change, R193 1), the renderer's batches are drawn first: CtrArray_add (ctr_array.c, -Wl,--wrap=CtrArray_add) sees
//   an append to this renderer's symTex that needs more than its capacity and calls the renderer's flush entry
//   (ctrFlush: flushBatch, which draws the held batches first, then the pending one, as draw_flush does) before the
//   array moves. Nothing then holds a copy's address; the draws keep their order, so the picture is the same. Every
//   other append pays one compare. The renderer is the one the display caps query names (its itemverdict link,
//   -Wl,--wrap=CtrRenderer_chainCapsItemverdict): main.c asks right after CtrRenderer_create, before any draw, and
//   UNDERTALE makes one renderer, kept until the process ends.
// The field is the one after symState (Symverdict_layout), which tools/analysis/test_symtex_stable.py checks in
// ctr_renderer.c's source.
#include <citro3d.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "ctr_array.h"
#include "ctr_memory.h"
#include "renderer.h"

#if defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)
#ifndef SYMKEEP_CODE
#define SYMKEEP_CODE __attribute__((noinline, section(".text_symkeep")))
#endif
#ifndef SYMKEEP_BSS
#define SYMKEEP_BSS __attribute__((section(".bss.symkeep_late")))
#endif
// ctr_renderer.c: SYM_COPIES_MAX.
#define SYMKEEP_COPIES 256u

extern const uint32_t Symverdict_layout[3]; // offsetof(CtrRenderer, symState), ... (z_symverdict.c)
void __real_CtrRenderer_chainFontVerdictsSymverdict(Renderer* renderer);
void __wrap_CtrRenderer_chainFontVerdictsSymverdict(Renderer* renderer);
uint32_t __real_CtrRenderer_chainCapsItemverdict(Renderer* renderer);
uint32_t __wrap_CtrRenderer_chainCapsItemverdict(Renderer* renderer);
void* __real_CtrArray_add(void* address, size_t elem, size_t count);
void* __wrap_CtrArray_add(void* address, size_t elem, size_t count);

// The renderer seen last and the address of its symTex.
static struct {
    Renderer* renderer;
    C3D_Tex** copies;
} symkeep SYMKEEP_BSS;

// symTex, declared right after symState.
static SYMKEEP_CODE C3D_Tex** symkeepSee(Renderer* renderer) {
    symkeep.renderer = renderer;
    return symkeep.copies = (C3D_Tex**) ((char*) renderer + Symverdict_layout[0] + sizeof(uint16_t*));
}

SYMKEEP_CODE uint32_t __wrap_CtrRenderer_chainCapsItemverdict(Renderer* renderer) {
    if (renderer != nullptr) symkeepSee(renderer);
    return __real_CtrRenderer_chainCapsItemverdict(renderer);
}

SYMKEEP_CODE void __wrap_CtrRenderer_chainFontVerdictsSymverdict(Renderer* renderer) {
    __real_CtrRenderer_chainFontVerdictsSymverdict(renderer);
    if (renderer == nullptr) return;
    C3D_Tex** copies = symkeepSee(renderer);
    if (arrlen(*copies) != 0) return; // copies made before: they grow, drawn first (below)
    // Without the reliever, as z_symverdict.c's symState: no packed texture is let go for this.
    bool relief = CtrMemory_allowRelief(false);
    CTR_ARRAY_RESERVE(*copies, SYMKEEP_COPIES);
    CtrMemory_allowRelief(relief);
}

SYMKEEP_CODE void* __wrap_CtrArray_add(void* address, size_t elem, size_t count) {
    if (address == symkeep.copies) {
        C3D_Tex* a = *symkeep.copies;
        if ((size_t) arrlen(a) + count > (size_t) arrcap(a)) symkeep.renderer->vtable->flush(symkeep.renderer);
    }
    return __real_CtrArray_add(address, elem, count);
}
#endif
