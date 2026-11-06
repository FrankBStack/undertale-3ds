// credclip (change auditfixe, CREDPOP-001; change creddodge, CREDCLIP-002, UNDERTALE): the options menu's Credits roll
// slides its lines in and out at the screen's own top and bottom edges.
//
// ctr_legal.c's luiDrawCredits draws a line only while the whole line is on the page (y from 0 to 226; a glyph is 12
// rows, and the menu font's painter has no clipping: past the page's top or bottom it would write into the next
// column). As the roll moves up half a pixel a frame (3 px with Up/Down), each line therefore appeared all at once 14
// rows above the bottom edge and vanished all at once at the top (CREDPOP-001). The first fix kept the page's rows
// outside 12..225 black, so a line's pop happened where none of its rows show; that left a black band 12 rows tall at
// the top and 14 at the bottom that the names vanished into and came out of, short of the screen's edges, and the
// roll's last line (the port's own credit, its end at y 226) sat wholly inside the bottom band (maintainer, 11-06).
//
// Now (CREDCLIP-002) the Credits roll is drawn here, whole, with every line that has any row on the page: lines with
// all 12 rows on it (y 0 to 228) through the painter as before, and the one line across the top edge and the one
// across the bottom edge drawn a row at a time. A line across an edge is painted where all its rows fit (y 0, or y
// 228) before any other line is, then its rows on the page are moved to where they belong and the rest cleared, so
// nothing is written outside the page and no other line's pixels are touched. Lines are 14 rows apart and 12 tall,
// so at most one line crosses each edge. Every line keeps luiDrawCredits' text, colour and x (luiLine's ASCII copy,
// centred on 7 px letters), so a line wholly on the page is drawn exactly as before.
// Where the roll stops is the credits text's: tools/aot/credits.py ends it with 8 empty lines, so the roll's end
// (ctr_legal.c's lui.height - 112, with the last line at y 226 then) leaves the last name, the port's own credit, at
// y 114, the middle of the page.
//
// Hook: the menu font's painter is wrapped for the calls from other objects (-Wl,--wrap=CtrOptmenu_text,
// CMakeLists.txt). While the Credits page is up with credits loaded (ctr_legal.c's CtrLegalui_state, an exact alias
// of its lui), the first call of a draw (a new page, a new roll position, or a line no lower than the last one: the
// lines of one draw come top to bottom) draws the whole page and the draw's other calls do nothing. Every other page,
// and the no-credits message (z_credfail.c, credits NULL), draws through the painter as before; so does any call on
// a framed page (its border in the page's first pixel, as CREDPOP-001 told them apart), in case lui is ever left
// on the Credits page with the menu showing another (CtrLegal_close clears legal.active but not lui).
// Late code only (late_reserve.ld): CREDPOP-001's wrap keeps its slot in .text_credclip, byte for byte, under the
// name credclipRetired_text (never called); the new code is appended (.text_credroll) with its three words of state
// (.bss.credroll_late). ctr_legal.c gains only the zero-byte alias and its offset checks at its end.
#include <stdbool.h>
#include <stdint.h>

#if defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)
#ifndef CREDCLIP_CODE
#define CREDCLIP_CODE __attribute__((noinline, section(".text_credclip")))
#endif
#ifndef CREDROLL_CODE
#define CREDROLL_CODE __attribute__((noinline, section(".text_credroll")))
#endif
#ifndef CREDROLL_BSS
#define CREDROLL_BSS __attribute__((section(".bss.credroll_late")))
#endif
#ifndef CREDWAIT_CODE
#define CREDWAIT_CODE __attribute__((noinline, section(".text_credwait")))
#endif
#ifndef CREDWAIT_FOR_VBLANK // the menu's screen: the one the game isn't on (ctr_optmenu.c's optPlace)
#include <3ds.h>
extern bool CtrScreens_onBottom;
#define CREDWAIT_FOR_VBLANK() gspWaitForEvent(CtrScreens_onBottom ? GSPGPU_EVENT_VBlank0 : GSPGPU_EVENT_VBlank1, true)
#endif
#ifndef CREDROLL_COLS
#include "ctr_release_contract.h"
#define CREDROLL_COLS CTR_RELEASE_LEGAL_COLUMNS // ctr_legal.c's LUI_COLS
#endif

#ifndef CREDCLIP_NEXT
// One column right. test_credclip.py replaces it to check that every step stays inside the page.
#define CREDCLIP_NEXT(p, fb) ((void) (fb), (p) += 240)
#endif

enum { CREDCLIP_TOP = 12, CREDCLIP_BOTTOM = 226, CREDCLIP_GLYPH_ROWS = 12 };

void __real_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
void __wrap_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
extern char* CtrLegalui_credits; // lui.credits (ctr_legal.c's alias): set only while the Credits roll is open

// CREDPOP-001's wrap, kept byte for byte in its slot so no late address moves (RULES 3adf7ac34); nothing calls it.
void credclipRetired_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
CREDCLIP_CODE __attribute__((used)) void credclipRetired_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col) {
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

// ctr_legal.c's lui (its offsets checked there, next to the CtrLegalui_state alias).
typedef struct {
    uint8_t view;   // 2: the Credits page (LUI_CREDITS)
    uint8_t row;
    uint8_t held;
    bool dirty;
    int32_t top;    // the roll's position in pixels
    int32_t rows;
    int32_t height;
    int32_t idle;
    char* credits;  // romfs:/credits.txt, NUL-terminated; NULL without credits
} CredrollLui;
#ifndef CREDROLL_LUI
extern CredrollLui CtrLegalui_state;
#define CREDROLL_LUI (&CtrLegalui_state)
#endif

enum { CREDROLL_PITCH = 14, CREDROLL_FIRST = 240 - CREDROLL_PITCH * 8, CREDROLL_LAST_WHOLE = 240 - CREDCLIP_GLYPH_ROWS };

// The page drawn last: its buffer, its roll position and the y of the latest line of that draw.
static struct {
    uint16_t* fb;
    int32_t top;
    int32_t y;
} credroll CREDROLL_BSS;

// Moves the rows of every column: rows to..to+n-1 take rows from..from+n-1, then rows clear0..clear0+nclear-1 are
// cleared (indices only, so no pointer outside the page is formed).
CREDROLL_CODE static void credrollRows(uint16_t* fb, int32_t to, int32_t from, int32_t n, int32_t clear0, int32_t nclear) {
    for (uint32_t c = 0; c < 320u; c++) {
        uint16_t* col = fb + c * 240u;
        if (to < from) {
            for (int32_t i = 0; i < n; i++) col[239 - (to + i)] = col[239 - (from + i)];
        } else {
            for (int32_t i = n - 1; i >= 0; i--) col[239 - (to + i)] = col[239 - (from + i)];
        }
        for (int32_t i = 0; i < nclear; i++) col[239 - (clear0 + i)] = 0;
    }
}

// One line of credits.txt (s: its colour letter, n bytes before its newline) at y, as luiDrawCredits and luiLine draw
// it; a line across the top or bottom edge drawn a row at a time (see the top of the file).
CREDROLL_CODE static void credrollLine(uint16_t* fb, int32_t y, const char* s, int32_t n) {
    char buf[CREDROLL_COLS + 5];
    int32_t w = n - 1 > CREDROLL_COLS + 4 ? CREDROLL_COLS + 4 : n - 1, k = 0;
    for (int32_t i = 0; i < w && s[1 + i] != '\0' && k < CREDROLL_COLS + 4; i++) {
        uint8_t c = (uint8_t) s[1 + i];
        if ((c & 0xC0u) == 0x80u) continue; // a continuation byte: its lead byte drew the '?'
        buf[k++] = c < 32u ? ' ' : c < 127u ? (char) c : '?';
    }
    buf[k] = '\0';
    uint32_t col = s[0] == 'Y' ? 0xFFE0u : s[0] == 'G' ? 0x8410u : 0xFFFFu;
    int32_t x = (320 - 7 * w) / 2;
    if (x < 0) x = 0;
    if (y < 0) { // across the top edge: rows -y..11 of the line show, in rows 0..11+y
        __real_CtrOptmenu_text(fb, x, 0, buf, col);
        credrollRows(fb, 0, -y, CREDCLIP_GLYPH_ROWS + y, CREDCLIP_GLYPH_ROWS + y, -y);
    } else if (y > CREDROLL_LAST_WHOLE) { // across the bottom edge: rows 0..239-y of the line show, in rows y..239
        __real_CtrOptmenu_text(fb, x, CREDROLL_LAST_WHOLE, buf, col);
        credrollRows(fb, y, CREDROLL_LAST_WHOLE, 240 - y, CREDROLL_LAST_WHOLE, y - CREDROLL_LAST_WHOLE);
    } else {
        __real_CtrOptmenu_text(fb, x, y, buf, col);
    }
}

// The whole Credits page at roll position top onto luiDrawCredits' cleared page: first the lines across the edges
// (each painted in rows no other line has yet), then every line wholly on the page.
CREDROLL_CODE static void credrollDraw(uint16_t* fb, const char* text, int32_t top) {
    for (int32_t pass = 0; pass < 2; pass++) {
        int32_t y = CREDROLL_FIRST - top;
        for (const char* s = text; *s != '\0' && y < 240; y += CREDROLL_PITCH) {
            int32_t n = 0;
            while (s[n] != '\0' && s[n] != '\n') n++;
            int32_t edge = y < 0 || y > CREDROLL_LAST_WHOLE;
            if (n > 1 && y > -CREDCLIP_GLYPH_ROWS && edge == (pass == 0)) credrollLine(fb, y, s, n);
            s += n;
            if (*s == '\n') s++;
        }
    }
}

// Compiled -Os (CMakeLists.txt): it runs only while a menu page draws, once per line.
CREDROLL_CODE void __wrap_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col) {
    const CredrollLui* lui = CREDROLL_LUI;
    // fb[0] (column 0, the bottom row) is black on the bare Credits page and never lit by a centred line; the framed
    // pages (Controls, the options) have their border there, so a stale lui can't take their text.
    if (lui->view != 2u || lui->credits == 0 || fb[0] != 0u) {
        __real_CtrOptmenu_text(fb, x, y, s, col);
        return;
    }
    // The Credits roll: its first line of a draw draws the page; the draw's later lines (lower, same page) are on it.
    if (fb == credroll.fb && lui->top == credroll.top && y > credroll.y) {
        credroll.y = y;
        return;
    }
    credroll.fb = fb;
    credroll.top = lui->top;
    credroll.y = y;
    credrollDraw(fb, lui->credits, lui->top);
}

// credwait (change crispgap, maintainer 11-06: holding Down on the Credits page, its left letters look torn). The page is
// composed off screen, then optFlush copies it onto the buffer being scanned, column 0 first, with nothing tying the
// copy to the scan: a copy that starts after the scan has begun leaves the columns the scan already passed showing the
// last position, 3 px off while a key is held. So when the page has moved, wait here for the menu's screen's next
// vblank: this returns to the menu's update, whose next work is that copy, which then runs ahead of the scan. Only a
// moved page waits, and a paused frame's slot is two vblanks, so the roll keeps its speed. nextEvent true: the pacer's
// own wait passes false, and handles the event being left signalled (it reads the count again).
// Reached from ctr_legal.c's wrap of CtrLegalui_update, a call retargeted so that neither moves (RULES 3adf7ac34).
struct CtrMenu;
void __real_CtrLegalui_update(struct CtrMenu* menu, uint32_t down);
void CtrCredroll_update(struct CtrMenu* menu, uint32_t down);
CREDWAIT_CODE void CtrCredroll_update(struct CtrMenu* menu, uint32_t down) {
    const CredrollLui* lui = CREDROLL_LUI;
    int32_t before = lui->top;
    __real_CtrLegalui_update(menu, down);
    if (lui->top != before) CREDWAIT_FOR_VBLANK();
}
#endif
