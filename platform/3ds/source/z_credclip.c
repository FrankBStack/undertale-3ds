// credclip (change auditfixe, CREDPOP-001, UNDERTALE): the options menu's Credits roll slides its lines in and out at
// the page's edges instead of popping them.
//
// ctr_legal.c's luiDrawCredits draws a line only while the whole line is on the page (y from 0 to 226; a glyph is 12
// rows, and the menu font's painter has no clipping: past the page's top or bottom it would write into the next
// column). As the roll moves up half a pixel a frame (3 px with Up/Down), each line therefore appeared all at once 14
// rows above the bottom edge and vanished all at once at the top. Now the rows of the page outside 12..225 are kept
// black: a line still appears at y 226 and vanishes below y 0 as before, but both happen where none of its rows show,
// and in between it moves a row at a time across the window's edge.
// The menu font's painter is wrapped for the calls from other objects (-Wl,--wrap=CtrOptmenu_text, CMakeLists.txt):
// after each line it blacks that line's rows outside the window when the page being drawn is the Credits roll, which
// is the only page drawn bare (luiClear with bare set: no frame, so its first pixel is black; every other page has
// the frame there) while credits are loaded (CtrLegalui_credits, ctr_legal.c's alias of lui.credits). Lines are 14
// rows apart and 12 tall, so a line's rows hold no other line's pixels. Every other page draws as before.
// Late code only (late_reserve.ld: .text_credclip and this file's text, after wrapfix); ctr_legal.c is unchanged.
#include <stdint.h>

#if defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)
#ifndef CREDCLIP_CODE
#define CREDCLIP_CODE __attribute__((noinline, section(".text_credclip")))
#endif

#ifndef CREDCLIP_NEXT
// One column right. test_credclip.py replaces it to check that every step stays inside the page.
#define CREDCLIP_NEXT(p, fb) ((void) (fb), (p) += 240)
#endif

enum { CREDCLIP_TOP = 12, CREDCLIP_BOTTOM = 226, CREDCLIP_GLYPH_ROWS = 12 };

void __real_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
void __wrap_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
extern char* CtrLegalui_credits; // lui.credits (ctr_legal.c's alias): set only while the Credits roll is open

// Compiled -Os (CMakeLists.txt): it runs only while a menu page draws, once per line.
CREDCLIP_CODE void __wrap_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col) {
    __real_CtrOptmenu_text(fb, x, y, s, col);
    if (fb[0] != 0 || CtrLegalui_credits == 0) return;
    // The page is 320 x 240 RGB565, column-major, each column bottom row first (row r at 239 - r). Only the line's
    // rows above the window or below it on the page are cleared (r is unsigned: a row above the page is huge).
    uint32_t r = (uint32_t) y, end = r + CREDCLIP_GLYPH_ROWS;
    do {
        if (r < CREDCLIP_TOP || r - CREDCLIP_BOTTOM < 240u - CREDCLIP_BOTTOM) {
            uint16_t* p = fb + (239u - r);
            for (uint32_t n = 319;; n--) {
                *p = 0;
                if (n == 0) break; // no step after the last column: p + 240 there would point past the page (R208)
                CREDCLIP_NEXT(p, fb);
            }
        }
    } while (++r != end);
}
#endif
