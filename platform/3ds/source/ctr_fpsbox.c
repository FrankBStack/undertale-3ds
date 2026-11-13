// Count accepted game-screen flips over elapsed display vblanks, not calls to
// the painter (which also runs for the other screen). No wall-clock timer.
#include "ctr_fpsbox.h"
#include "ctr_frame_pacer.h"
#include <citro3d.h>
#include <string.h>

#define FPSBOX_CODE __attribute__((noinline, optimize("Os"), section(".text.late.fpsbox")))

// The physical game-screen selection used by the pacer's flip totals. Read
// its own vblank clock: bottom presents latch on VBlank1, not VBlank0.
extern uint8_t CtrScreens_pacerGame;

static struct {
    uint32_t vblank, flips;
    bool ready;
    uint8_t screen;
} sample __attribute__((section(".bss.late.fpsbox")));

FPSBOX_CODE void CtrFpsbox_update(char* digits) {
    uint32_t screen = CtrScreens_pacerGame;
    uint32_t now = C3D_FrameCounter((int) screen);
    bool sameScreen = sample.ready && sample.screen == screen;
    uint32_t elapsed = now - sample.vblank;
    if (sameScreen && elapsed < 60u) return;
    CtrFlipStats total;
    CtrPacer_getFlipTotals(&total);
    uint32_t rate = 0;
    if (sameScreen) {
        // Physical display rate, 59.831 Hz; nearest whole fps.
        // Unsigned subtraction handles both counters' wraparound. Include time
        // spent holding the current picture, even if no flip completed at all.
        uint64_t denominator = (uint64_t) elapsed * 1000u;
        rate = (uint32_t) (((uint64_t) (total.flips - sample.flips) * 59831u + denominator / 2u) / denominator);
    }
    if (rate > 99u) rate = 99u;
    digits[0] = (char) ('0' + rate / 10u);
    digits[1] = (char) ('0' + rate % 10u);
    digits[2] = '\0';
    sample.vblank = now;
    sample.flips = total.flips;
    sample.ready = true;
    sample.screen = (uint8_t) screen;
}

FPSBOX_CODE void CtrFpsbox_restoreMenu(uint16_t* shown, const uint16_t* page, bool top) {
    // A top menu occupies the middle 320 columns. Its counter is wholly in
    // the black left border. A bottom menu has no border: restore its pixels
    // from the composed page, preserving the menu's own lines and lettering.
    if (top) shown -= 40u * 240u;
    for (uint32_t x = 2; x < 35u; x++) {
        uint32_t offset = x * 240u + 202u; // y=2..37, largest two-digit cell
        if (top) memset(shown + offset, 0, 36u * sizeof(*shown));
        else memcpy(shown + offset, page + offset, 36u * sizeof(*shown));
    }
}

// The old restore slot stays intact. Its caller now leaves live pixels alone;
// the digit painter composites the menu backdrop and glyph in a single pass.
__attribute__((noinline, noipa, optimize("Os"), section(".text.fpsbox75zm_late")))
void CtrFpsbox_menuNoErase(uint16_t* shown, const uint16_t* page, bool top) {
    (void) shown; (void) page; (void) top;
}

#if defined(__3DS__) && defined(ENABLE_WAD17) && defined(CTRPORT_TARGET_N3DS)
// Retain DR New's existing ARM-to-Thumb veneer before the appended counter.
// caDraw still branches to the exact old address. 3dsxtool also relocates the
// word at veneer +8 by name, even for an explicit stub: give that slot a real,
// unused ABS32 pointer, never an instruction or unrelocated glyph constant.
__asm__(".pushsection .text.fpsbox75zm_veneer,\"ax\",%progbits\n"
        ".arm\n.balign 8\n"
        ".type ____wrap_Crispart_drawTexture_from_arm,%function\n"
        "____wrap_Crispart_drawTexture_from_arm:\n"
        ".global CtrFpsbox_crispVeneer\n"
        ".type CtrFpsbox_crispVeneer,%function\n"
        "CtrFpsbox_crispVeneer:\n"
        "ldr pc,[pc,#-4]\n"
        ".word __wrap_Crispart_drawTexture\n"
        ".size ____wrap_Crispart_drawTexture_from_arm,8\n"
        ".size CtrFpsbox_crispVeneer,8\n"
        ".global CtrFpsbox_veneerReloc\n"
        ".type CtrFpsbox_veneerReloc,%object\n"
        "CtrFpsbox_veneerReloc:\n"
        ".word CtrFpsbox_crispVeneer\n"
        ".size CtrFpsbox_veneerReloc,4\n"
        ".popsection\n");
#endif
