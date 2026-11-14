// Product unit: only the queue's final destination lookup enters destination().
// releaseReady has admitted Bottom after the previous held/pending flip drained.
#if defined(ENABLE_WAD16) || defined(FPSGHOST_HINTPAGE_HOST)
#ifndef FPSGHOST_HINTPAGE_HOST
#include <3ds.h>
#include "ctr_frame_pacer.h"
#define HP_CODE __attribute__((noinline, noipa, optimize("Os"), section(".text_fpsghost_hintpage")))
#else
#define HP_CODE
#endif

extern bool CtrTap_hintBottom(void);
extern u8 CtrScreens_pacerGame;
void CtrScreens_pacerWaitShown(gfxScreen_t, bool);
u8* CtrBlank_settledShown(gfxScreen_t, gfx3dSide_t, u16*, u16*);
void CtrTap_realSwap(gfxScreen_t, bool) __asm__("__real_gfxScreenSwapBuffers");
#ifndef FPSGHOST_HINTPAGE_HOST
// An underscore section name needs explicit NOBITS, as the port's other late state does (z_battletouch.c's BT_BSSM).
static u8* hpPage __attribute__((section(".bss_fpsghost_hintpage,\"aw\",%nobits @")));
#else
static u8* hpPage __attribute__((section(".bss_fpsghost_hintpage")));
#endif

HP_CODE u8* CtrTap_destination(gfxScreen_t screen, gfx3dSide_t side) {
    if (screen == GFX_BOTTOM && CtrTap_hintBottom()) {
        gfxSetDoubleBuffering(screen, true);
        u8* page = CtrPacer_backFramebuffer(screen, side);
        __atomic_store_n(&hpPage, page, __ATOMIC_RELEASE);
        return page;
    }
    return CtrPacer_backFramebuffer(screen, side);
}

// Retain the actual transfer destination, including while the pacer holds it.
HP_CODE u8* CtrTap_paintFramebuffer(gfxScreen_t screen, gfx3dSide_t side) {
    // The hint may have appeared after destination selection. Defer its first
    // paint rather than falling back to the shown single-buffer page.
    if (screen == GFX_BOTTOM) return __atomic_load_n(&hpPage, __ATOMIC_ACQUIRE);
    return CtrPacer_backFramebuffer(screen, side);
}

// Options may borrow the spare only after a held AND pending flip has drained.
// Retarget OPT_SHOWN, before either page is chosen; optPlace itself is unchanged.
HP_CODE u8* CtrTap_optionsShown(gfxScreen_t screen, gfx3dSide_t side, u16* width, u16* height) {
    for (;;) {
        if (screen == GFX_BOTTOM)
            while (!CtrPacer_screenReady(screen)) CtrScreens_pacerWaitShown(screen, true);
        u8* page = CtrBlank_settledShown(screen, side, width, height);
        // blankSettle can finish an in-flight transfer into a HELD flip.
        // Drain that too, then reselect; never loan a provisional page.
        if (screen != GFX_BOTTOM || CtrPacer_screenReady(screen)) return page;
    }
}

// Reached at the real swap, NOT the queue-finish request that the pacer may hold.
HP_CODE void CtrTap_finalSwap(gfxScreen_t screen, bool stereo) {
    bool ours = screen == GFX_BOTTOM && __atomic_load_n(&hpPage, __ATOMIC_ACQUIRE) != NULL;
    if (ours) gfxSetDoubleBuffering(screen, true);
    CtrTap_realSwap(screen, stereo);
    if (ours) {
        __atomic_store_n(&hpPage, NULL, __ATOMIC_RELEASE);
        // libctru's software front is now the submitted page. CPU-only writers
        // address it; screenReady holds the next transfer until it is displayed.
        if (CtrScreens_pacerGame == GFX_TOP) gfxSetDoubleBuffering(screen, false);
    }
}
#endif
