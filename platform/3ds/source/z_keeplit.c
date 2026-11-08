// Other screen Off with dialogue on the bottom keeps that screen lit (change dlglight, maintainer 11-07; UNDERTALE only).
//
// A backlight power-on shows about 3 refreshes after the call, with a one-refresh sweep across the panel
// (docs/3ds-hardware.md, "A backlight power-on lights late and sweeps across the panel"), and no order of light and box
// hides that: the light stays on instead, over a black screen between boxes. Off with dialogue on top, or the game on the
// bottom (no dialogue there, the settings wrap says), stays truly off. The original 2DS is left out: its Off is already no
// power-off, and fps75Configure asks the same question and would clear its screen. No brightness calls.
//
// CMake points CtrArgui_keepLit at CtrKeeplit_keepLit in ctr_screens.c and ctr_renderer.c, and the settings wrap's next
// link at CtrKeeplit_setDisplay: the same calls, other targets, so no instruction there changes. This is its own file
// because code added to ctr_renderer.c, even at its end, changes the inlining of functions far above it (in the first
// build, ctr_renderer.o's CtrRenderer_selfTest grew 4 B and relocateVram shrank 8 B, moving all later text by -8 B).
// The renderer's fields are private to that file, so their offsets come from CMake and static asserts there check them.

#include <3ds.h>
#include <stdbool.h>
#include "ctr_renderer.h"

extern bool CtrScreens_otherOff, CtrScreens_sharedBacklight;
bool CtrArgui_keepLit(u32 screen);
void CtrRenderer_chainDisplayInputlate(Renderer* renderer, const CtrDisplaySettings* settings);
bool CtrKeeplit_keepLit(u32 screen);
void CtrKeeplit_setDisplay(Renderer* renderer, const CtrDisplaySettings* settings);

static bool keeplitWanted;

bool CtrKeeplit_keepLit(u32 screen) {
    return CtrArgui_keepLit(screen) | (keeplitWanted && screen == GSPLCD_SCREEN_BOTTOM);
}

// settings is the wrap's narrowed copy. applyBottomBacklight only calls when its off/on answer changes, and the answer
// leaves the dialogue setting out, so a change here makes the next set-up ask: its power-off lights or darkens the screen
// by the new answer. A changed setting dirties the display anyway; a first call with the settings in place doesn't.
void CtrKeeplit_setDisplay(Renderer* renderer, const CtrDisplaySettings* settings) {
    bool wanted = CtrScreens_otherOff && !CtrScreens_sharedBacklight && settings->dialogueBottom;
    if (wanted != keeplitWanted) {
        keeplitWanted = wanted;
        *((bool*) renderer + CTRPORT_KEEPLIT_BACKLIGHT_AT) = false;
        *((bool*) renderer + CTRPORT_KEEPLIT_DIRTY_AT) = true;
    }
    CtrRenderer_chainDisplayInputlate(renderer, settings);
}
