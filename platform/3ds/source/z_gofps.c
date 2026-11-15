// gofps (change hiscase, 11-15; UNDERTALE only): the FPS counter stays on its own screen when the game moves back up.
//
// maintainer's o3DS, Split, counter on Top: after a game over the counter flashed on the bottom screen for a moment and went
// back. With the game below, the stats and log consoles and the menu's page are the top screen's single RGB565 buffer
// (main.c's CtrScreens_moveConsoles(true)), and the counter paints its digits into that same buffer
// (ctr_argui.c's flush wrapper, arguiPaintScreen). The move back up copies the menu's page to the bottom screen
// (moveConsoles(false), through CtrLayout_restoreMenu18), the counter's digits with it, so the bottom showed them until
// something drew over that cell (Azahar gofps-split-o3ds/n3ds: frame 925, the frame after the move).
//
// After that copy, the counter's own rectangle on the top page (fps75Rect[GFX_TOP], ctr_optmenu.c; empty unless its
// last paint there was the RGB565 one) is cleared in the copy to black, what the page holds there with the counter off:
// the counter never paints over the consoles while they show (ctr_argui.c's gate on CtrLog_consoleEnabled), and every
// paint clears its old rectangle to black on this page (a menu backdrop only over a menu on the bottom). Only when the
// consoles leave the top (CtrScreens_consolesOnTop) and don't show, and only when the copy's source IS that page: the
// top's buffer on screen, the one the counter's RGB565 paint writes (gfxGetFramebuffer with the top single buffered;
// neither move swaps the top before this copy). With Options open on top the source is the menu's composed spare
// (ctr_optmenu.c's optPlace: the top's other buffer, 40 columns in), which the counter never paints and whose every
// pixel is copied as it is (c26rev6 GOFPS-1). CtrPacer_shownFramebuffer leaves the top double buffered, as the move
// makes it next anyway (scanoutMove's own call already has; screensMoveGame's screensShowCarried right after).
// The game's carried frame (ctr_renderer.c's screensCarry) is untouched: parked until a capture shows stale digits
// after a carry (lead 11-15).
// Code last in late text (late_reserve.ld).
#if defined(ENABLE_WAD16) || defined(GOFPS_HOST)
#ifndef GOFPS_HOST
#include <3ds.h>
#define GOFPS_CODE __attribute__((noinline, noipa, optimize("Os"), section(".text_gofps_late")))
#else
#define GOFPS_CODE
#endif
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

extern bool CtrScreens_consolesOnTop; // ctr_screens.c
bool CtrLog_consoleEnabled(void);
extern uint8_t CtrFpsbox_rect[2][4]; // ctr_optmenu.c's fps75Rect: left, top, right, bottom per screen
void* CtrLayout_restoreMenu18(void* dst, const void* src, size_t n);
#ifndef GOFPS_HOST
u8* CtrPacer_shownFramebuffer(gfxScreen_t screen, gfx3dSide_t side, u16* width, u16* height); // ctr_frame_pacer.c
#endif
void* CtrFpsbox_moveCopy(void* dst, const void* src, size_t n);

GOFPS_CODE void* CtrFpsbox_moveCopy(void* dst, const void* src, size_t n) {
    void* out = CtrLayout_restoreMenu18(dst, src, n);
    if (!CtrScreens_consolesOnTop || CtrLog_consoleEnabled() || n < 320u * 240u * 2u) return out;
    u16 w = 0, h = 0;
    if ((const void*) CtrPacer_shownFramebuffer(GFX_TOP, GFX_LEFT, &w, &h) != src) return out;
    const uint8_t* r = CtrFpsbox_rect[0]; // GFX_TOP
    uint16_t* page = (uint16_t*) dst;
    for (uint32_t x = r[0]; x < r[2]; x++) {
        for (uint32_t y = r[1]; y < r[3]; y++) page[x * 240u + 239u - y] = 0;
    }
    return out;
}
#endif
