// Ordinary closes submit black Top through the existing native frame. No GPU
// drain, LCD adoption wait, CPU clear or console lock is added there. Ownership
// remains until the next existing blocking boundary. An adopted black page
// may become single buffered sooner, without waiting or clearing either page.
#define DLGTOP_RETIRE_CODE __attribute__((section(".text_dlgretire_late"), noinline, noclone, used, optimize("Os")))

void CtrDlgtop_bindConsoles(void* shown);
#undef dlgtopReturn
DLGTOP_RETIRE_CODE static void dlgtopDrain(void) {
    if (dlgtopLease.target != nullptr &&
        CtrLayout_dialogueLease((Renderer*) dlgtopLease.owner, dlgtopLease.target, 1)) {
        dlgtopReturn(); // original detach + blocking two-page retirement
        // That retirement may have flipped away from the consoles' old page.
        // Rebind before Options' first painter, under the existing writer lock.
        CtrLog_beginConsole();
        CtrDlgtop_bindConsoles(CtrPacer_backFramebuffer(GFX_TOP, GFX_LEFT));
        CtrLog_endConsole();
    }
    dlgtopLease.target = nullptr;
    dlgtopLease.parked = 0;
}
#define dlgtopReturn dlgtopDrain

DLGTOP_RETIRE_CODE static void dlgtopClose(void) {
    CtrRenderer* r = dlgtopLease.owner;
    if (r != nullptr && !dlgtopWants(r)) {
        dlgtopReturn(); // settings/yield boundary, not an ordinary close
        return;
    }
    if (dlgtopLease.target == nullptr ||
        !CtrLayout_dialogueLease((Renderer*) r, dlgtopLease.target, 0)) {
        dlgtopLease.target = nullptr; // revoked: never touch the old pages
        return;
    }
    // prepare() may notice destruction before any black was submitted (or
    // on a skipped frame). Do not expose that still-text page to consoles.
    if (dlgtopLease.parked == 0 && !r->dlg.shown && r->magnifier.blankSent == 2)
        dlgtopLease.parked = 1;
}

DLGTOP_RETIRE_CODE static C3D_RenderTarget* dlgtopWake(CtrRenderer* r) {
    C3D_RenderTarget* target = dlgtopBorrowed(r);
    if (target == nullptr) return nullptr;
    // Empty replay may still submit the close's black transfer, without
    // waking Other screen Off. Only a reopened box reclaims the light.
    bool wake = dlgtopLease.parked && dlgtopBoxOpen(r);
    if (!CtrLayout_dialogueLease((Renderer*) r, target, wake ? 1 : -1)) {
        dlgtopLease.target = nullptr;
        return nullptr;
    }
    if (wake) dlgtopLease.parked = false;
    // Once the blank is adopted and consoles rebound, don't relink or turn
    // double buffering on for empty frames. Reopen redraws before reuse.
    if (!wake && dlgtopLease.parked == 2 && !dlgtopBoxOpen(r)) return nullptr;
    return target;
}

bool CtrBottomPaint_claimConsole(void);
void CtrLayout_chain18(Renderer*);
DLGTOP_RETIRE_CODE static void CtrDlgtop_idleChain(Renderer* renderer) {
    // Before native frame begin. Never wait for the GPU, a flip or a writer.
    // Until this succeeds the shown-query keeps ordinary painters paused.
    if (dlgtopLease.owner == (CtrRenderer*) renderer && dlgtopLease.parked == 1 &&
        dlgtopLease.target != nullptr && !dlgtopBoxOpen((CtrRenderer*) renderer) &&
        CtrLayout_dialogueLease(renderer, dlgtopLease.target, -1) &&
        !CtrGpu_busy() && CtrPacer_screenReady(GFX_TOP) && CtrBottomPaint_claimConsole()) {
        u8* shown = CtrPacer_shownFramebuffer(GFX_TOP, GFX_LEFT, nullptr, nullptr);
        if (shown != nullptr) {
            // One page is already black. The old spare remains private to
            // DIALOGUE until the draining boundary; no CPU clear/copy needed.
            gfxSetDoubleBuffering(GFX_TOP, false);
            CtrDlgtop_bindConsoles(shown);
            dlgtopLease.parked = 2;
        }
        CtrLog_endConsole();
    }
    CtrLayout_chain18(renderer);
}

bool CtrBlank_dialogueShown(void* renderer);
DLGTOP_RETIRE_CODE bool CtrDlgtop_consoleShown(void* renderer) {
    if (dlgtopLease.owner == (CtrRenderer*) renderer &&
        dlgtopLease.target != nullptr &&
        CtrLayout_dialogueLease((Renderer*) renderer, dlgtopLease.target, -1)) {
        // The old blank query settles/clears physical Bottom. Top dialogue
        // uses its own adoption above; never send its close into that path.
        return ((CtrRenderer*) renderer)->dlg.shown || dlgtopLease.parked == 1;
    }
    return CtrBlank_dialogueShown(renderer);
}

#include "ctr_menu.h"
void Upd1_menuOpen(CtrMenu*, PrintConsole*, const CtrDisplaySettings*, CtrDisplayCaps);
DLGTOP_RETIRE_CODE void CtrDlgtop_menuOpen(CtrMenu* menu, PrintConsole* console,
                                        const CtrDisplaySettings* settings, CtrDisplayCaps caps) {
    // Optmenu paints before main yields. Drain before even optPlace can bind
    // or copy the page. The later yield cannot erase any new menu painter.
    dlgtopReturn();
    Upd1_menuOpen(menu, console, settings, caps);
}
#undef DLGTOP_RETIRE_CODE
