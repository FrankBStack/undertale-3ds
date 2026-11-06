"""CREDPOP-001 + CREDCLIP-002 (credclip): the options menu's Credits roll slides each line in and out at the screen's
own top and bottom edges, and stops with its last name in the middle of the page.

ctr_legal.c's luiDrawCredits draws a credits line only while all 12 of its rows are on the page (y 0 to 226), so as the
roll moves up a row at a time each line appeared whole 14 rows above the bottom and vanished whole at the top
(CREDPOP-001). The first fix kept the rows outside 12..225 black, which left bands the names vanished into and came
out of, and hid the roll's last line, the port's own credit (maintainer, 11-06). z_credclip.c now draws the whole Credits
page itself, the lines across the top and bottom edges a row at a time (CREDCLIP-002).
This compiles the shipping legalui section of ctr_legal.c (with stubs for the menu, the files and the console lock)
with a painter that sets a per-letter pattern of pixels in the 320 x 240 column-major page and reports any write past
a page edge (the console's painter has no clipping). The candidate routes the section's calls to z_credclip.c's
__wrap_CtrOptmenu_text, as -Wl,--wrap=CtrOptmenu_text does on the console; the base calls the painter directly. The
credits are 40 lines and tools/aot/credits.py's END_GAP empty lines. Each arm rolls them for 1700 frames (to the end
and on), pages back with L, holds Down, pages with R to the end, holds Up to the start and pages R again, keeping every
drawn page.
Checks: every candidate page equals the same text painted once on a tall canvas and cut at the page's roll position
(all 240 rows: lines meet both edges a row at a time, and nothing else is lit); the roll stops with the last line at
y 114 (rows 114..125, the middle of 240), both rolling and paging with R; held Down moves it 3 rows a frame; the
painter is called at most once per line on the page; no write leaves the page; the Legal page and the no-credits
message (credits NULL: z_credfail.c's page) are drawn exactly as the base draws them. The base must fail the canvas
check (else the test no longer tells the arms apart). Also pins the wiring: the UNDERTALE wrap in CMakeLists.txt, the
late sections (CREDPOP-001's retired wrap after wrapfix; the new code and state appended after pacealign), the
ctr_legal.c alias, credits.py's END_GAP, both manifests. Synthetic data only. Runs at -O0 and -O2.
Steps (R208): CREDPOP-001's retired wrap (kept in its slot, never called), through its CREDCLIP_NEXT hook, for every
line origin the old roll drew (y -11 to 226): every column step lands inside the page, and the rows it clears are the
line's rows outside its old window, in all 320 columns.
Run: py -3 -I tools/analysis/test_credclip.py
Needs a native C compiler (clang, else gcc) on PATH: without one the pytest test is skipped and the command line
prints SKIP; a compile or fixture error still fails.
"""
import importlib.util
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / 'platform/3ds/source'
NO_WINDOW = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
TOP, BOTTOM = 12, 226  # CREDPOP-001's window (the retired wrap's steps check)
NLINES = 40

# The legalui section's harness: stub headers and the prelude its code expects (ctr_legal.c's file statics, key bits,
# fopen routed to the driver).
STUB_MENU = r'''
#pragma once
#include <stdbool.h>
#include <stdint.h>
typedef uint32_t u32;
typedef int32_t Result;
typedef struct { void* frameBuffer; } PrintConsole;
typedef struct { PrintConsole* console; } CtrMenu;
// ctr_menu.h's Old 3DS mapping (the legal page's LUI_PREV/LUI_NEXT use these since item 8; unused before).
#define CTR_MENU_PAD_RIGHT KEY_CPAD_RIGHT
#define CTR_MENU_PAD_LEFT KEY_CPAD_LEFT
#define CTR_MENU_PAD_UP KEY_CPAD_UP
#define CTR_MENU_PAD_DOWN KEY_CPAD_DOWN
void CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col);
'''
STUB_LOG = 'void CtrLog_beginConsole(void);\nvoid CtrLog_endConsole(void);\n'
PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include "ctr_menu.h"
#include "ctr_log.h"
#define CTR_RELEASE_LEGAL_COLUMNS 38
#define CTR_RELEASE_LEGAL_LINES 24
#define R_SUCCEEDED(r) ((r) >= 0)
#define KEY_A (1u << 0)
#define KEY_B (1u << 1)
#define KEY_SELECT (1u << 2)
#define KEY_DRIGHT (1u << 4)
#define KEY_DLEFT (1u << 5)
#define KEY_DUP (1u << 6)
#define KEY_DDOWN (1u << 7)
#define KEY_R (1u << 8)
#define KEY_L (1u << 9)
#define KEY_CPAD_RIGHT (1u << 28)
#define KEY_CPAD_LEFT (1u << 29)
#define KEY_CPAD_UP (1u << 30)
#define KEY_CPAD_DOWN (1u << 31)
#define LATE_TEXT
#define CTRPORT_COMMIT "0123456789ab"
u32 hidKeysHeld(void);
Result CtrLegal_mountSelf(const char* name);
FILE* test_fopen(const char* path, const char* mode);
#define fopen test_fopen
static struct {
    bool selected;
    bool active;
    bool mountTried;
    int document;
    uint32_t page;
    uint32_t pages;
    char lines[CTR_RELEASE_LEGAL_LINES][CTR_RELEASE_LEGAL_COLUMNS + 1];
} legal;
static const char documentPaths[][48] = { "romfs:/legal/LICENSE.pages", "romfs:/legal/THIRD_PARTY_NOTICES.pages" };
static const char summary[] = "Summary line one.\nSummary line two.\n\n";
static const char sourceHeading[] = "Development source:";
static const char sourceUrl[] = "https://example.invalid/src";
static const char buildHeading[] = "Build:";
static const char unofficial[] = "\nUnofficial.";
static const char unavailable[] = "Bundled legal text is unavailable.\nRebuild or reinstall this package.\nB returns to the legal summary.";
static const char fileMode[] = "rb";
static const char romfsName[] = "romfs";
bool Test_active(void) { return legal.active; }
'''

SUFFIX = '\nchar** Test_creditsRef = &lui.credits;\nint32_t* Test_top = &lui.top;\nvoid* Test_lui = &lui;\n'

# The candidate's z_credclip.c, its lui (ctr_legal.c's CtrLegalui_state alias on the console) the section's own.
CAND = r'''
#include <stdint.h>
extern void* Test_lui;
extern char** Test_creditsRef;
#define CREDCLIP_CODE
#define CREDROLL_CODE
#define CREDROLL_BSS
#define CREDWAIT_CODE
#define CREDWAIT_FOR_VBLANK() ((void) 0)
#define CREDROLL_COLS 38
#define CREDROLL_LUI ((const CredrollLui*) Test_lui)
#define CtrLegalui_credits (*Test_creditsRef)
#include "z_credclip.c"
void __real_CtrLegalui_update(struct CtrMenu* menu, uint32_t down) { (void) menu; (void) down; }
'''

DRIVER = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_menu.h"
#define KEY_B (1u << 1)
#define KEY_DUP (1u << 6)
#define KEY_DDOWN (1u << 7)
#define KEY_R (1u << 8)
#define KEY_L (1u << 9)
void CtrLegalui_open(CtrMenu* menu, bool credits);
void CtrLegalui_update(CtrMenu* menu, u32 down);
void PAINTER(uint16_t* p, int32_t x, int32_t y, const char* s, uint32_t col);
extern int32_t* Test_top;
enum { MAXPAGES = 2600, NLINES = NLINES_, GAP = END_GAP_, PITCH = 14, FIRST = 128, CANVAS = 240 + FIRST + NLINES * PITCH + 240 };
static uint16_t fb[320 * 240];
static PrintConsole console = { fb };
static CtrMenu menu = { &console };
static int outside, calls, pageCalls, worstCalls;
static u32 heldKeys;
static char tmpPath[512];
static char credits[8192];
static char lines[NLINES][64];
static uint16_t* pages[MAXPAGES];
static int32_t tops[MAXPAGES];
static int npages;
static uint16_t canvas[320][CANVAS]; // the text once: canvas row 240 + Y holds the text's row Y (line i at 128 + 14 i)
void CtrLog_beginConsole(void) { pageCalls = 0; }
void CtrLog_endConsole(void) {
    if (pageCalls > worstCalls) worstCalls = pageCalls;
    if (npages < MAXPAGES) {
        pages[npages] = malloc(sizeof fb);
        memcpy(pages[npages], fb, sizeof fb);
        tops[npages++] = *Test_top;
    }
}
u32 hidKeysHeld(void) { return heldKeys; }
Result CtrLegal_mountSelf(const char* name) { (void) name; return -1; }
FILE* test_fopen(const char* path, const char* mode) {
    if (strcmp(path, "romfs:/credits.txt") != 0) return NULL;
    FILE* f = fopen(tmpPath, "wb");
    if (f == NULL) return NULL;
    fwrite(credits, 1, strlen(credits), f);
    fclose(f);
    return fopen(tmpPath, mode);
}
static int lit(unsigned char c, int gx, int gy) { return ((unsigned) c + gx * 3 + gy * 5) % 4 != 0; }
// The painter: a pattern per letter, 6 x 12 in a 7-pixel cell, every write checked against the page.
void PAINTER(uint16_t* p, int32_t x, int32_t y, const char* s, uint32_t col) {
    calls++;
    pageCalls++;
    for (; *s != '\0'; s++, x += 7) {
        for (int32_t gy = 0; gy < 12; gy++) {
            for (int32_t gx = 0; gx < 6; gx++) {
                if (!lit((unsigned char) *s, gx, gy)) continue;
                int32_t px = x + gx, py = y + gy;
                if (px < 0 || px > 319 || py < 0 || py > 239) { outside++; continue; }
                p[px * 240 + (239 - py)] = (uint16_t) col;
            }
        }
    }
}
static uint16_t px(const uint16_t* p, int x, int r) { return p[x * 240 + (239 - r)]; }
static unsigned long hashRows(const uint16_t* p, int r0, int r1) {
    unsigned long h = 2166136261u;
    for (int x = 0; x < 320; x++) for (int r = r0; r < r1; r++) h = (h ^ px(p, x, r)) * 16777619u;
    return h;
}
static void step(u32 down, u32 held) { heldKeys = held; CtrLegalui_update(&menu, down); heldKeys = 0; }
int main(int argc, char** argv) {
    (void) argc;
    snprintf(tmpPath, sizeof tmpPath, "%s", argv[1]);
    char* w = credits;
    for (int i = 0; i < NLINES; i++) {
        snprintf(lines[i], sizeof lines[i], "%c%s line %d%s", "WYG"[i % 3], i % 2 ? "Someone" : "A longer credits name", i,
                 i % 5 ? "" : " and more");
        w += sprintf(w, "%s\n", lines[i]);
    }
    for (int i = 0; i < GAP; i++) *w++ = '\n';
    *w = '\0';
    // The text once on the canvas, as luiDrawCredits places it (x = (320 - 7 n) / 2 for n letters).
    for (int i = 0; i < NLINES; i++) {
        const char* s = lines[i] + 1;
        int n = (int) strlen(s), x = (320 - 7 * n) / 2, Y = 240 + FIRST + PITCH * i;
        uint16_t col = (uint16_t) (lines[i][0] == 'Y' ? 0xFFE0u : lines[i][0] == 'G' ? 0x8410u : 0xFFFFu);
        for (int k = 0; k < n; k++)
            for (int gy = 0; gy < 12; gy++)
                for (int gx = 0; gx < 6; gx++)
                    if (lit((unsigned char) s[k], gx, gy)) canvas[x + 7 * k + gx][Y + gy] = col;
    }
    CtrLegalui_open(&menu, true);
    for (int i = 0; i < 1400; i++) step(0, 0);
    int rollEnd = *Test_top;
    for (int i = 0; i < 300; i++) step(0, 0);
    int rollEnd2 = *Test_top;
    for (int i = 0; i < 5; i++) step(KEY_L, 0);
    int afterL = *Test_top;
    for (int i = 0; i < 40; i++) step(0, KEY_DDOWN);
    int afterDown = *Test_top;
    for (int i = 0; i < 6; i++) step(KEY_R, 0);
    int pageEnd = *Test_top;
    for (int i = 0; i < 300; i++) step(0, KEY_DUP);
    int afterUp = *Test_top;
    for (int i = 0; i < 4; i++) step(KEY_R, 0);
    // Every page against the canvas cut at its roll position: page row r is canvas row 240 + r + top.
    long bad = 0;
    int badPages = 0;
    for (int i = 0; i < npages; i++) {
        long b = 0;
        for (int x = 0; x < 320; x++)
            for (int r = 0; r < 240; r++) {
                int cr = 240 + r + tops[i];
                uint16_t want = cr >= 0 && cr < CANVAS ? canvas[x][cr] : 0;
                b += px(pages[i], x, r) != want;
            }
        bad += b;
        badPages += b != 0;
    }
    printf("PAGES %d BAD %ld BADPAGES %d OUTSIDE %d WORST %d END %d %d L %d DOWN %d R %d UP %d\n", npages, bad,
           badPages, outside, worstCalls, rollEnd, rollEnd2, afterL, afterDown, pageEnd, afterUp);
    CtrLegalui_update(&menu, KEY_B);
    npages = 0;
    CtrLegalui_open(&menu, false);
    printf("LEGAL %08lx pages %d\n", hashRows(fb, 0, 240), npages);
    CtrLegalui_update(&menu, KEY_B);
    // A framed page (its border in the page's first pixel) drawn while lui is still on the Credits roll with credits
    // loaded, as after CtrLegal_close (it clears legal.active, not lui): its lines go straight to the painter.
    CtrLegalui_open(&menu, true);
    for (int i = 0; i < 100; i++) step(0, 0);
    memset(fb, 0, sizeof fb);
    for (int x = 0; x < 320; x++) fb[x * 240] = fb[x * 240 + 239] = 0x7BEFu;
    int before = calls;
    CtrOptmenu_text(fb, 24, 30, "Controls", 0xFFFFu);
    CtrOptmenu_text(fb, 24, 44, "A  Confirm", 0xFFFFu);
    printf("FRAMED %d %08lx\n", calls - before, hashRows(fb, 0, 240));
    CtrLegalui_update(&menu, KEY_B);
    // No credits (an empty credits.txt): lui.credits stays NULL, and z_credfail.c's message goes straight to the painter.
    credits[0] = '\0';
    CtrLegalui_open(&menu, true);
    memset(fb, 0, sizeof fb);
    before = calls;
    CtrOptmenu_text(fb, 24, 30, "Credits are unavailable.", 0xFFFFu);
    CtrOptmenu_text(fb, 24, 44, "B returns.", 0xFFFFu);
    printf("NOCRED %d %08lx\n", calls - before, hashRows(fb, 0, 240));
    return 0;
}
'''


STEPS = r'''
#include <stdint.h>
#include <stdio.h>
static unsigned long steps, bad, wrong, calls;
static uintptr_t maxOff;
// Integer offsets only, so the check itself forms no pointer outside the page.
static uint16_t* credclipNext(uint16_t* p, uint16_t* fb) {
    uintptr_t off = ((uintptr_t) p - (uintptr_t) fb) / sizeof *p + 240u;
    steps++;
    if (off > maxOff) maxOff = off;
    if (off >= 320u * 240u) { bad++; return p; }
    return fb + off;
}
#define CREDCLIP_NEXT(p, fb) ((p) = credclipNext((p), (fb)))
#define CREDCLIP_CODE
#define CREDROLL_CODE
#define CREDROLL_BSS
#define CREDWAIT_CODE
#define CREDWAIT_FOR_VBLANK() ((void) 0)
#define CREDROLL_COLS 38
static long long testLui[3];
#define CREDROLL_LUI ((const CredrollLui*) (void*) testLui)
char* CtrLegalui_credits = "credits";
void __real_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col) {
    (void) fb; (void) x; (void) y; (void) s; (void) col;
}
#include "z_credclip.c"
void __real_CtrLegalui_update(struct CtrMenu* menu, uint32_t down) { (void) menu; (void) down; }
static uint16_t fb[320 * 240];
int main(void) {
    for (int32_t y = -11; y <= 226; y++) {
        for (uint32_t i = 0; i < 320u * 240u; i++) fb[i] = 0x1234;
        fb[0] = 0;
        credclipRetired_text(fb, 0, y, "", 0);
        calls++;
        for (uint32_t c = 0; c < 320; c++)
            for (int32_t r = 0; r < 240; r++) {
                int cleared = r >= y && r < y + 12 && (r < TOP || r >= BOTTOM);
                uint16_t v = fb[c * 240u + (uint32_t) (239 - r)];
                if (c * 240u + (uint32_t) (239 - r) == 0) continue;
                if (v != (cleared ? 0 : 0x1234)) wrong++;
            }
    }
    printf("STEPS %lu MAX %lu BAD %lu WRONG %lu CALLS %lu\n", steps, (unsigned long) maxOff, bad, wrong, calls);
    return 0;
}
'''


def legalui_section():
    text = (SOURCE / 'ctr_legal.c').read_text(encoding='utf-8')
    start = text.index('// ===[ legalui')
    end = text.index('// luiDrawHub joins heading', start)
    return text[start:end]


def end_gap():
    """credits.py's END_GAP (the empty lines after the last name), or None."""
    m = re.search(r'^END_GAP = (\d+)\b', (REPO / 'tools/aot/credits.py').read_text(encoding='utf-8'), re.M)
    return int(m.group(1)) if m else None


def gap_is_undertale_only():
    """credits.py's finish(): UNDERTALE's text ends with END_GAP empty lines, DELTARUNE's text gets none (z_credclip.c is
    linked into UNDERTALE only, and DELTARUNE's romfs text must stay as it was)."""
    spec = importlib.util.spec_from_file_location('credits_under_test', REPO / 'tools/aot/credits.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    lines = ['', 'Wa', '', 'Wb', '', '']
    errors = []
    if module.finish('undertale', lines) != 'Wa\n\nWb' + '\n' * (module.END_GAP + 1):
        errors.append('credits.py: the UNDERTALE text does not end with END_GAP empty lines')
    if module.finish('deltarune', lines) != 'Wa\n\nWb\n':
        errors.append('credits.py: the DELTARUNE text is no longer free of the end gap')
    return errors


def compiler():
    """The native C compiler: clang, else gcc, from PATH; None when neither is installed."""
    return shutil.which('clang') or shutil.which('gcc')


def wiring():
    errors = []
    cmake = (REPO / 'platform/3ds/CMakeLists.txt').read_text(encoding='utf-8')
    if not re.search(r'if\(CTRPORT_GAME STREQUAL "undertale"\)\s*\n\s*target_link_options\(ctrport PRIVATE '
                     r'-Wl,--wrap=CtrOptmenu_text\)\s*\nendif\(\)', cmake):
        errors.append('CMakeLists.txt: the UNDERTALE --wrap=CtrOptmenu_text is gone')
    ld = (REPO / 'platform/3ds/late_reserve.ld').read_text(encoding='utf-8')
    a, b = ld.find('*z_wrapfix.o(.text .text.* .rodata .rodata.*)'), ld.find('KEEP(*(.text_credclip))')
    if a < 0 or b < a or '*z_credclip.o(.text .text.* .rodata .rodata.*)' not in ld or ld.find('*(.repack_test)') < b:
        errors.append('late_reserve.ld: credclip is not kept (KEEP: its retired wrap has no caller) after wrapfix '
                      '(before the repack test lines)')
    p, c = ld.find('*(.rodata.pacealign_in_text)'), ld.find('*(.text_credroll)')
    if p < 0 or c < p or ld.find('*(.repack_test)') < c:
        errors.append('late_reserve.ld: credroll is not appended after pacealign (before the repack test lines; zq line: after utcredepi)')
    p, c = ld.find('*(.bss.pacealign_late)'), ld.find('*(.bss.credroll_late)')
    if p < 0 or c < p:
        errors.append('late_reserve.ld: credroll\'s state is not appended after pacealign\'s')
    # UNDERTALE's manifest always; DELTARUNE's only where the tree ships one (the public UNDERTALE tree has none).
    for name in ('manifest-ut.txt', 'manifest-dr.txt'):
        manifest = REPO / 'tools/release' / name
        if name != 'manifest-ut.txt' and not manifest.exists():
            continue
        if not manifest.exists() or 'platform/3ds/source/z_credclip.c' not in manifest.read_text(encoding='utf-8'):
            errors.append('%s: z_credclip.c is not listed' % name)
    legal = (SOURCE / 'ctr_legal.c').read_text(encoding='utf-8')
    if 'luiClear(menu, true)' not in legal.split('static LUI_CODE void luiDrawCredits', 1)[-1].split('}', 1)[0]:
        errors.append('ctr_legal.c: the Credits roll is no longer drawn on a cleared bare page')
    if '.set CtrLegalui_state,lui\\n' not in legal:
        errors.append('ctr_legal.c: the CtrLegalui_state alias of lui (z_credclip.c\'s view of the page) is gone')
    gap = end_gap()
    if gap != 8:
        errors.append('credits.py: END_GAP is %r, not 8 (the roll would not stop with the last name at y 114)' % gap)
    errors += gap_is_undertale_only()
    return errors


def main():
    clang = compiler()
    if clang is None:
        print('SKIP: no native C compiler (clang or gcc) on PATH')
        return 0
    errors = wiring()
    gap = end_gap() or 0
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'inc').mkdir()
        (tmp / 'inc/ctr_menu.h').write_text(STUB_MENU, encoding='utf-8')
        (tmp / 'inc/ctr_log.h').write_text(STUB_LOG, encoding='utf-8')
        (tmp / 'driver.c').write_text(DRIVER.replace('NLINES_', str(NLINES)).replace('END_GAP_', str(gap)),
                                      encoding='utf-8')
        (tmp / 'z_credclip.c').write_bytes((SOURCE / 'z_credclip.c').read_bytes())
        (tmp / 'cand.c').write_text(CAND, encoding='utf-8')
        (tmp / 'legal.c').write_text(PRELUDE + legalui_section() + SUFFIX, encoding='utf-8')
        (tmp / 'steps.c').write_text(STEPS.replace('BOTTOM', str(BOTTOM)).replace('TOP', str(TOP)), encoding='utf-8')
        for opt in ('-O0', '-O2'):
            exe = tmp / ('steps%s.exe' % opt)
            r = subprocess.run([clang, '-std=gnu2x', opt, '-w', '-DENABLE_WAD16', '-I', str(tmp), str(tmp / 'steps.c'),
                                '-o', str(exe)], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=300)
            if r.returncode != 0:
                print(r.stdout + r.stderr)
                return 2
            r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120, creationflags=NO_WINDOW)
            m = re.search(r'STEPS (\d+) MAX (\d+) BAD (\d+) WRONG (\d+) CALLS (\d+)', r.stdout)
            if r.returncode != 0 or not m:
                print('EXIT', r.returncode, r.stdout[-2000:], r.stderr[-2000:])
                return 2
            st = dict(zip(('steps', 'max', 'bad', 'wrong', 'calls'), map(int, m.groups())))
            print('%s steps %s' % (opt, st))
            if st['steps'] == 0:
                errors.append('%s steps: the retired wrap never used CREDCLIP_NEXT (its column steps are not checked)' % opt)
            if st['bad']:
                errors.append('%s steps: %d column steps would point past the page' % (opt, st['bad']))
            if st['wrong']:
                errors.append('%s steps: %d pixels cleared or kept wrongly' % (opt, st['wrong']))
        for opt in ('-O0', '-O2'):
            for arm in ('base', 'cand'):
                exe = tmp / ('%s%s.exe' % (arm, opt))
                srcs = [str(tmp / 'legal.c'), str(tmp / 'driver.c')]
                if arm == 'base':
                    defs = ['-DPAINTER=CtrOptmenu_text', '-DENABLE_WAD16']
                else:
                    defs = ['-DPAINTER=__real_CtrOptmenu_text', '-DCtrOptmenu_text=__wrap_CtrOptmenu_text',
                            '-DENABLE_WAD16']
                    srcs.append(str(tmp / 'cand.c'))
                r = subprocess.run([clang, '-std=gnu2x', opt, '-w', '-I', str(tmp / 'inc'), '-I', str(tmp), *defs, *srcs,
                                    '-o', str(exe)], capture_output=True, text=True, creationflags=NO_WINDOW, timeout=300)
                if r.returncode != 0:
                    print(r.stdout + r.stderr)
                    return 2
                r = subprocess.run([str(exe), str(tmp / 'credits.txt')], capture_output=True, text=True, timeout=120,
                                   creationflags=NO_WINDOW)
                if r.returncode != 0:
                    print('EXIT', r.returncode, r.stdout[-2000:], r.stderr[-2000:])
                    return 2
                results[(opt, arm)] = r.stdout
    end = (NLINES + gap) * 14 - 14 * 8  # ctr_legal.c's roll end: lui.height - 112
    last_y = 128 + 14 * (NLINES - 1) - end
    if last_y != 114:
        errors.append('the roll ends with the last line at y %d, not 114 (the middle of the page)' % last_y)
    keys = ('pages', 'bad', 'badpages', 'outside', 'worst', 'end', 'end2', 'l', 'down', 'r', 'up')
    pat = (r'PAGES (\d+) BAD (\d+) BADPAGES (\d+) OUTSIDE (\d+) WORST (\d+) END (-?\d+) (-?\d+) L (-?\d+) '
           r'DOWN (-?\d+) R (-?\d+) UP (-?\d+)')
    for opt in ('-O0', '-O2'):
        stats = {}
        for arm in ('base', 'cand'):
            m = re.search(pat, results[(opt, arm)])
            if not m:
                print(results[(opt, arm)][-2000:])
                return 2
            stats[arm] = dict(zip(keys, map(int, m.groups())))
            print('%s %-4s %s' % (opt, arm, stats[arm]))
        b, c = stats['base'], stats['cand']
        if c['pages'] < end + 100:  # the roll alone draws every position 0..end once
            errors.append('%s: only %d pages were drawn (the test needs the whole roll)' % (opt, c['pages']))
        if c['bad']:
            errors.append('%s cand: %d pixels on %d pages differ from the text cut at the roll position'
                          % (opt, c['bad'], c['badpages']))
        if c['outside'] or b['outside']:
            errors.append('%s: the painter was asked to write past the page (%d base, %d cand)' % (opt, b['outside'], c['outside']))
        if c['worst'] > 240 // 14 + 2:
            errors.append('%s cand: %d painter calls on one page (at most one per line on it)' % (opt, c['worst']))
        for k, want in (('end', end), ('end2', end), ('l', 0), ('down', 120), ('r', end), ('up', 0)):
            if c[k] != want or b[k] != want:
                errors.append('%s: roll position %s is %d (cand) / %d (base), not %d' % (opt, k, c[k], b[k], want))
        for tag in ('LEGAL', 'FRAMED', 'NOCRED'):
            lb = re.search(r'^%s .*$' % tag, results[(opt, 'base')], re.M).group()
            lc = re.search(r'^%s .*$' % tag, results[(opt, 'cand')], re.M).group()
            if lb != lc:
                errors.append('%s: %s drawn differently (%s vs %s)' % (opt, tag, lb, lc))
        if not b['bad']:
            errors.append('%s: the base passes the canvas check; the test no longer tells the arms apart' % opt)
    for e in errors:
        print('ERROR: ' + e)
    print('PASS' if not errors else 'FAIL')
    return 1 if errors else 0


# The release gate (tools/release/undertale_release_day.py) runs pytest -q tools: this is the test it collects.
# main() runs as from the command line (no arguments); a FAIL return or exit fails it. No compiler: skipped.
def test_credclip(monkeypatch):
    import pytest
    if compiler() is None:
        pytest.skip('no native C compiler (clang or gcc) on PATH')
    monkeypatch.setattr(sys, 'argv', [__file__])
    try:
        rc = main()
    except SystemExit as stop:
        rc = stop.code
    assert rc in (None, 0), rc

if __name__ == '__main__':
    sys.exit(main())
