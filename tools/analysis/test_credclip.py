"""CREDPOP-001 (credclip): the options menu's Credits roll slides each line in and out at the page's edges.

ctr_legal.c's luiDrawCredits draws a credits line only while all 12 of its rows are on the page (y 0 to 226), so as the
roll moves up a row at a time each line appeared whole 14 rows above the bottom and vanished whole at the top. This
compiles the shipping legalui section of ctr_legal.c (with stubs for the menu, the files and the
console lock) with a painter that sets a per-letter pattern of pixels in the 320 x 240 column-major page and
reports any write past a page edge (the console's painter has no clipping). The candidate routes the section's calls
to z_credclip.c's __wrap_CtrOptmenu_text, as -Wl,--wrap=CtrOptmenu_text does on the console; the base calls the
painter directly. It rolls 40 lines of credits for 1400 frames and keeps every drawn page.
Checks, for every pair of pages one roll row apart: each row an arm shows text in (the base: the whole page; the
candidate: the window, rows 12 to 225) shows what the row below it showed one page before, so no line appears or
vanishes inside the rows shown; only the bottom row takes new pixels. The
candidate's rows outside the window are black on every page, its window rows equal the base's, no write leaves the
page, and the Legal page (framed) is drawn exactly as the base draws it. The base must fail the motion check (else
the test no longer tells the arms apart). Also pins the wiring: the UNDERTALE wrap in CMakeLists.txt, the late
section after wrapfix, both manifests. Synthetic data only. Runs at -O0 and -O2.
Steps (R208): the wrapper alone, through its CREDCLIP_NEXT hook, for every line origin the roll draws (y -11 to 226).
Every column step must land on an element inside the page: no pointer past it is ever formed, not even one never
stored through. The rows cleared must be exactly the line's rows outside the window, in all 320 columns.
Run: py -3 -I tools/analysis/test_credclip.py
Needs a native C compiler (clang, else gcc) on PATH: without one the pytest test is skipped and the command line
prints SKIP; a compile or fixture error still fails.
"""
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
TOP, BOTTOM = 12, 226

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

SUFFIX = '\nchar** Test_creditsRef = &lui.credits;\nint32_t* Test_top = &lui.top;\n'
DRIVER = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_menu.h"
#define KEY_B (1u << 1)
void CtrLegalui_open(CtrMenu* menu, bool credits);
void CtrLegalui_update(CtrMenu* menu, u32 down);
extern int32_t* Test_top;
static uint16_t fb[320 * 240];
static PrintConsole console = { fb };
static CtrMenu menu = { &console };
static int outside;
static char tmpPath[512];
static char credits[4096];
enum { MAXPAGES = 1600 };
static uint16_t* pages[MAXPAGES];
static int32_t tops[MAXPAGES];
static int npages;
void CtrLog_beginConsole(void) { }
void CtrLog_endConsole(void) {
    if (npages < MAXPAGES) {
        pages[npages] = malloc(sizeof fb);
        memcpy(pages[npages], fb, sizeof fb);
        tops[npages++] = *Test_top;
    }
}
u32 hidKeysHeld(void) { return 0; }
Result CtrLegal_mountSelf(const char* name) { (void) name; return -1; }
FILE* test_fopen(const char* path, const char* mode) {
    if (strcmp(path, "romfs:/credits.txt") != 0) return NULL;
    FILE* f = fopen(tmpPath, "wb");
    if (f == NULL) return NULL;
    fwrite(credits, 1, strlen(credits), f);
    fclose(f);
    return fopen(tmpPath, mode);
}
// The painter: a pattern per letter, 6 x 12 in a 7-pixel cell, every write checked against the page.
void PAINTER(uint16_t* p, int32_t x, int32_t y, const char* s, uint32_t col) {
    for (; *s != '\0'; s++, x += 7) {
        for (int32_t gy = 0; gy < 12; gy++) {
            for (int32_t gx = 0; gx < 6; gx++) {
                if (((unsigned char) *s + gx * 3 + gy * 5) % 4 == 0) continue;
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
int main(int argc, char** argv) {
    (void) argc;
    snprintf(tmpPath, sizeof tmpPath, "%s", argv[1]);
    char* w = credits;
    for (int i = 0; i < 40; i++) w += sprintf(w, "%c%s line %d%s\n", "WYG"[i % 3], i % 2 ? "Someone" : "A longer credits name", i, i % 5 ? "" : " and more");
    CtrLegalui_open(&menu, true);
    for (int i = 0; i < 1400; i++) CtrLegalui_update(&menu, 0);
    // The rows this arm shows text in: the whole page (base), or the window (candidate).
    int shownTop = atoi(argv[2]), shownBottom = atoi(argv[3]);
    int pairs = 0, viol = 0, edge = 0;
    for (int i = 1; i < npages; i++) {
        if (tops[i] != tops[i - 1] + 1) continue;
        pairs++;
        for (int r = shownTop; r + 1 < shownBottom; r++) {
            for (int x = 0; x < 320; x++) viol += px(pages[i], x, r) != px(pages[i - 1], x, r + 1);
        }
    }
    for (int i = 0; i < npages; i++) {
        for (int x = 0; x < 320; x++) for (int r = 0; r < 240; r++) if (r < TOP || r >= BOTTOM) edge += px(pages[i], x, r) != 0;
        printf("H %d %08lx\n", (int) tops[i], hashRows(pages[i], TOP, BOTTOM));
    }
    printf("PAGES %d PAIRS %d VIOL %d EDGE %d OUTSIDE %d\n", npages, pairs, viol, edge, outside);
    CtrLegalui_update(&menu, KEY_B);
    npages = 0;
    CtrLegalui_open(&menu, false);
    printf("LEGAL %08lx pages %d\n", hashRows(fb, 0, 240), npages);
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
char* CtrLegalui_credits = "credits";
void __real_CtrOptmenu_text(uint16_t* fb, int32_t x, int32_t y, const char* s, uint32_t col) {
    (void) fb; (void) x; (void) y; (void) s; (void) col;
}
#include "z_credclip.c"
static uint16_t fb[320 * 240];
int main(void) {
    for (int32_t y = -11; y <= 226; y++) {
        for (uint32_t i = 0; i < 320u * 240u; i++) fb[i] = 0x1234;
        fb[0] = 0;
        __wrap_CtrOptmenu_text(fb, 0, y, "", 0);
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
    a, b = ld.find('*z_wrapfix.o(.text .text.* .rodata .rodata.*)'), ld.find('*(.text_credclip)')
    if a < 0 or b < a or '*z_credclip.o(.text .text.* .rodata .rodata.*)' not in ld or ld.find('*(.repack_test)') < b:
        errors.append('late_reserve.ld: credclip is not appended after wrapfix (before the repack test lines)')
    # UNDERTALE's manifest always; DELTARUNE's only where the tree ships one (the public UNDERTALE tree has none).
    for name in ('manifest-ut.txt', 'manifest-dr.txt'):
        manifest = REPO / 'tools/release' / name
        if name != 'manifest-ut.txt' and not manifest.exists():
            continue
        if not manifest.exists() or 'platform/3ds/source/z_credclip.c' not in manifest.read_text(encoding='utf-8'):
            errors.append('%s: z_credclip.c is not listed' % name)
    legal = (SOURCE / 'ctr_legal.c').read_text(encoding='utf-8')
    if 'luiClear(menu, true)' not in legal.split('static LUI_CODE void luiDrawCredits', 1)[-1].split('}', 1)[0]:
        errors.append('ctr_legal.c: the Credits roll is no longer drawn bare (credclip tells it by its black corner)')
    return errors


def main():
    clang = compiler()
    if clang is None:
        print('SKIP: no native C compiler (clang or gcc) on PATH')
        return 0
    errors = wiring()
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / 'inc').mkdir()
        (tmp / 'inc/ctr_menu.h').write_text(STUB_MENU, encoding='utf-8')
        (tmp / 'inc/ctr_log.h').write_text(STUB_LOG, encoding='utf-8')
        (tmp / 'driver.c').write_text(DRIVER.replace('BOTTOM', str(BOTTOM)).replace('TOP', str(TOP)), encoding='utf-8')
        (tmp / 'z_credclip.c').write_bytes((SOURCE / 'z_credclip.c').read_bytes())
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
                errors.append('%s steps: the wrapper never used CREDCLIP_NEXT (its column steps are not checked)' % opt)
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
                            '-DENABLE_WAD16', '-DCREDCLIP_CODE=', '-DCtrLegalui_credits=(*Test_creditsRef)']
                    srcs.append(str(tmp / 'z_credclip.c'))
                r = subprocess.run([clang, '-std=gnu2x', opt, '-w', '-I', str(tmp / 'inc'), *defs, *srcs, '-o', str(exe)],
                                   capture_output=True, text=True, creationflags=NO_WINDOW, timeout=300)
                if r.returncode != 0:
                    print(r.stdout + r.stderr)
                    return 2
                shown = ['0', '240'] if arm == 'base' else [str(TOP), str(BOTTOM)]
                r = subprocess.run([str(exe), str(tmp / 'credits.txt'), *shown], capture_output=True, text=True, timeout=120,
                                   creationflags=NO_WINDOW)
                if r.returncode != 0:
                    print('EXIT', r.returncode, r.stdout[-2000:], r.stderr[-2000:])
                    return 2
                results[(opt, arm)] = r.stdout
    for opt in ('-O0', '-O2'):
        stats = {}
        for arm in ('base', 'cand'):
            out = results[(opt, arm)]
            m = re.search(r'PAGES (\d+) PAIRS (\d+) VIOL (\d+) EDGE (\d+) OUTSIDE (\d+)', out)
            stats[arm] = dict(zip(('pages', 'pairs', 'viol', 'edge', 'outside'), map(int, m.groups())))
            print('%s %-4s %s' % (opt, arm, stats[arm]))
        b, c = stats['base'], stats['cand']
        if c['pairs'] < 300:
            errors.append('%s: the roll moved only %d rows (the test needs a long roll)' % (opt, c['pairs']))
        if c['viol']:
            errors.append('%s cand: %d window pixels did not move up one row with the roll (a line popped)' % (opt, c['viol']))
        if c['edge']:
            errors.append('%s cand: %d pixels lit outside the window rows %d..%d' % (opt, c['edge'], TOP, BOTTOM - 1))
        if c['outside'] or b['outside']:
            errors.append('%s: the painter was asked to write past the page (%d base, %d cand)' % (opt, b['outside'], c['outside']))
        hb = re.findall(r'^H (-?\d+) (\w+)$', results[(opt, 'base')], re.M)
        hc = re.findall(r'^H (-?\d+) (\w+)$', results[(opt, 'cand')], re.M)
        if hb != hc:
            errors.append('%s: the candidate window rows differ from the base' % opt)
        lb = re.search(r'^LEGAL .*$', results[(opt, 'base')], re.M).group()
        lc = re.search(r'^LEGAL .*$', results[(opt, 'cand')], re.M).group()
        if lb != lc:
            errors.append('%s: the Legal page is drawn differently (%s vs %s)' % (opt, lb, lc))
        if not b['viol']:
            errors.append('%s: the base passes the motion check; the test no longer tells the arms apart' % opt)
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
