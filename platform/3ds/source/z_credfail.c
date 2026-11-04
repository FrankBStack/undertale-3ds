// credfail (change auditfixe, DEEP-11, UNDERTALE): the Credits page says so when it has no credits to show.
//
// The options menu's Credits row opens ctr_legal.c's legalui page, which reads romfs:/credits.txt (luiLoadCredits)
// and rolls it up. build.sh only warns when tools/aot/credits.py fails ("the Credits page is empty in this build"),
// and luiLoadCredits leaves the text NULL when the file is missing or empty, cannot be read, is 64 KB or more, or
// finds no memory. luiDrawCredits then drew a bare black page: no text, and nothing saying that B or SELECT goes back.
// Now, once CtrLegalui_open (reached through -Wl,--wrap=CtrLegalui_open, CMakeLists.txt) has drawn the Credits page
// with no text, three lines go on it in the Legal reader's own error style (luiDrawDoc's: white, from x 24, y 30,
// 14 px apart): the credits are missing, how to get them back, and what B does. The page then stays as drawn: with
// no text its height is 0, so CtrLegalui_update holds the roll at 0 and never draws it again before B or SELECT
// closes it. A page with credits, and the Legal page, are drawn as before.
// Late code only (late_reserve.ld: .text_credfail and this file's text); ctr_legal.c gains only a zero-byte alias of
// lui.credits (CtrLegalui_credits), so its code keeps its bytes and addresses.
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "ctr_log.h"
#include "ctr_menu.h"

#if defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)
#ifndef CREDFAIL_CODE
#define CREDFAIL_CODE __attribute__((noinline, section(".text_credfail")))
#endif
#ifndef CREDFAIL_RO
#define CREDFAIL_RO __attribute__((section(".rodata.credfail_in_text")))
#endif

void CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
void __real_CtrLegalui_open(CtrMenu* menu, bool credits);
extern char* CtrLegalui_credits; // lui.credits (ctr_legal.c's alias): NULL when the page has no text

// NUL-separated, one per line (each at most the reader's 40 columns).
static const char credfailLines[] CREDFAIL_RO =
    "The bundled credits are unavailable.\0"
    "Rebuild or reinstall this package.\0"
    "B returns to the options.";

CREDFAIL_CODE void __wrap_CtrLegalui_open(CtrMenu* menu, bool credits) {
    __real_CtrLegalui_open(menu, credits);
    if (!credits || CtrLegalui_credits != NULL) return;
    uint16_t* fb = (uint16_t*) menu->console->frameBuffer;
    CtrLog_beginConsole();
    const char* s = credfailLines;
    for (int32_t y = 30; y <= 58; y += 14) {
        CtrOptmenu_text(fb, 24, y, s, 0xFFFFu);
        s += strlen(s) + 1;
    }
    CtrLog_endConsole();
}
#endif
