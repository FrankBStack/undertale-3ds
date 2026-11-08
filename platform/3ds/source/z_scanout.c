// scanout (change scanout, 11-07; UNDERTALE only): a setup notice's page painted off the LCD, then copied at its vblank.
//
// main.c's setupNotices paints its page again every frame (after HOME or sleep the renderer may have cleared that
// screen): a clear of the whole page (libctru's consoleClear draws a space in all 1,200 cells), then the text. The
// notice's screen holds the consoles, RGB565 and single buffered, so both went into the buffer the LCD was scanning:
// wherever the scan passed between the clear and the text, that refresh showed those rows blank or half drawn.
// UNDERTALE shows the notice on the bottom (93 of its lines are blank between pictures, 3.7 ms), so that is every
// refresh whose paint outlasts the blank (3.2-3.4 ms on Azahar); on the top (13 blank lines) it would be every one.
//
// Now the clear and the text go into the screen's spare buffer, and at the screen's next vblank the page is copied onto
// the shown one: the copy starts at column 0 and outruns the scan (crispgap's rule, docs/3ds-hardware.md; menufirst
// does the same for the options menu's page, credwait for a moved Credits page). A page that hasn't changed is the
// same bytes written again, so nothing changes on the LCD. Each frame of the notice waits for that vblank (input is read
// after it), which a notice can afford.
//
// main.c's two calls in the loop (consoleClear, hidScanInput) come here by name: the same calls with other targets, so
// main.o's code and layout stay as they were. The code is in its own file because a body added to main.c, even at its
// end, changed the order GCC emits main's functions in (first build: setupNotices.part.0 moved by 84 B and main's switch
// tables were renumbered). Placed last in late text (late_reserve.ld, "scanout"), so nothing else moves. No constants,
// no statics in a release build. CMake leaves this file out of DELTARUNE, whose main.c keeps the original calls.

#include <3ds.h>
#include <stdbool.h>
#include <stddef.h>
#include <string.h>

#include "log.h"

#define SCANOUT_CODE __attribute__((noinline, noipa, optimize("Os"), section(".text_scanout")))

extern bool CtrScreens_consolesOnTop; // ctr_screens.c: the consoles' screen (main.c's moveConsoles sets it)

#ifdef CTRPORT_PLAYER_SHOTS // test builds: the page's paint time, the scan's line around the copy, what the LCD holds
static const char scanoutLog[] = "scanout: notice page on screen %u, painted %s in %lu us; copy at line %lu, done at "
                                 "line %lu; shown buffer %s the page, %lu of %lu pixels lit\n";
static const char scanoutWhyLog[] = "scanout: screen %u format %u window %d,%d %dx%d of %dx%d; console at %08lx, "
                                    "libctru's current %08lx, other %08lx; registers A %08lx B %08lx select %08lx\n";
static u64 scanoutPaintStart;
static u32 scanoutPaints;
#endif

// The console printing now: setupNotices selected its menu console just before each call. consoleSelect hands back the
// one it replaces; the log's writer, the only other printer, waits on the console lock setupNotices holds.
SCANOUT_CODE static PrintConsole* scanoutConsole(void) {
    PrintConsole* menu = consoleSelect(NULL);
    consoleSelect(menu);
    return menu;
}

// The other buffer of the screen's libctru pair that holds buf, or NULL if buf is neither. libctru answers its current
// buffer with double buffering off and the other one with it on (main.c's Loadgame_menuSpare asks the same way); the
// screen's setting is put back as it was.
SCANOUT_CODE static u16* scanoutPair(gfxScreen_t screen, const u16* buf) {
    u16* now = (u16*) gfxGetFramebuffer(screen, GFX_LEFT, NULL, NULL);
    gfxSetDoubleBuffering(screen, false);
    u16* current = (u16*) gfxGetFramebuffer(screen, GFX_LEFT, NULL, NULL);
    gfxSetDoubleBuffering(screen, true);
    u16* other = (u16*) gfxGetFramebuffer(screen, GFX_LEFT, NULL, NULL);
    gfxSetDoubleBuffering(screen, now == other && other != current);
    if (current == other) return NULL;
    return buf == current ? other : buf == other ? current : NULL;
}

// The physical address of the buffer the screen scans: its framebuffer registers (0x68 buffer A, 0x6C buffer B, 0x78
// bit 0 which one), as menufirst and dlgblank read them. 0 if unreadable.
SCANOUT_CODE static u32 scanoutScanned(gfxScreen_t screen) {
    u32 regs[5];
    if (R_FAILED(GSPGPU_ReadHWRegs(screen == GFX_TOP ? 0x400468u : 0x400568u, regs, sizeof(regs)))) return 0;
    return (regs[4] & 1u) != 0 ? regs[1] : regs[0];
}

// For setupNotices' consoleClear: the page goes to the spare buffer until CtrScanout_noticeScan, when the console is on
// the buffer the LCD scans, of an RGB565 screen, with its window the whole page (libctru counts the window from 1, 1).
// Otherwise it is painted as before.
void CtrScanout_noticeClear(void);
SCANOUT_CODE void CtrScanout_noticeClear(void) {
    gfxScreen_t screen = CtrScreens_consolesOnTop ? GFX_TOP : GFX_BOTTOM;
    PrintConsole* menu = scanoutConsole();
#ifdef CTRPORT_PLAYER_SHOTS // test builds: the first answers' inputs
    if (menu != NULL && 3u > scanoutPaints) {
        u32 r[5] = { 0 };
        GSPGPU_ReadHWRegs(screen == GFX_TOP ? 0x400468u : 0x400568u, r, sizeof(r));
        u16* pair = scanoutPair(screen, menu->frameBuffer);
        logInfo(scanoutWhyLog, (unsigned) screen, (unsigned) gfxGetScreenFormat(screen), menu->windowX, menu->windowY,
                menu->windowWidth, menu->windowHeight, menu->consoleWidth, menu->consoleHeight,
                (unsigned long) osConvertVirtToPhys(menu->frameBuffer),
                (unsigned long) osConvertVirtToPhys(gfxGetFramebuffer(screen, GFX_LEFT, NULL, NULL)),
                (unsigned long) (pair != NULL ? osConvertVirtToPhys(pair) : 0u), (unsigned long) r[0],
                (unsigned long) r[1], (unsigned long) r[4]);
    }
#endif
    if (menu != NULL && gfxGetScreenFormat(screen) == GSP_RGB565_OES && menu->windowX == 1 && menu->windowY == 1 &&
        menu->windowWidth == menu->consoleWidth && menu->windowHeight == menu->consoleHeight) {
        u32 scanned = scanoutScanned(screen);
        u16* spare = scanoutPair(screen, menu->frameBuffer);
        if (scanned != 0 && scanned == osConvertVirtToPhys(menu->frameBuffer) && spare != NULL) menu->frameBuffer = spare;
    }
#ifdef CTRPORT_PLAYER_SHOTS
    scanoutPaintStart = svcGetSystemTick();
#endif
    consoleClear();
}

// For setupNotices' hidScanInput, once the page is printed: if it went to the spare (the console is on the other buffer
// of libctru's current one), the console back on the current buffer, the page copied there at the screen's next vblank
// and written back for the LCD; then the input, as before. No register read here: whatever the screens did since the
// clear, the console ends on the buffer it was given, as before.
void CtrScanout_noticeScan(void);
SCANOUT_CODE void CtrScanout_noticeScan(void) {
    gfxScreen_t screen = CtrScreens_consolesOnTop ? GFX_TOP : GFX_BOTTOM;
    PrintConsole* menu = scanoutConsole();
    u16* page = menu != NULL ? menu->frameBuffer : NULL;
    u16* shown = page != NULL ? scanoutPair(screen, page) : NULL;
    bool moved = shown != NULL && shown == (u16*) gfxGetFramebuffer(screen, GFX_LEFT, NULL, NULL);
#ifdef CTRPORT_PLAYER_SHOTS
    u32 painted = (u32) ((svcGetSystemTick() - scanoutPaintStart) / 268u);
    u32 first = 0, last = 0;
#endif
    if (moved) {
        u32 bytes = (u32) menu->consoleWidth * 8u * 240u * 2u; // the page's columns, 240 RGB565 pixels each
        menu->frameBuffer = shown;
        gspWaitForEvent(screen == GFX_TOP ? GSPGPU_EVENT_VBlank0 : GSPGPU_EVENT_VBlank1, true);
#ifdef CTRPORT_PLAYER_SHOTS
        GSPGPU_ReadHWRegs(screen == GFX_TOP ? 0x400454u : 0x400554u, &first, sizeof(first));
#endif
        memcpy(shown, page, bytes);
        GSPGPU_FlushDataCache(shown, bytes);
#ifdef CTRPORT_PLAYER_SHOTS
        GSPGPU_ReadHWRegs(screen == GFX_TOP ? 0x400454u : 0x400554u, &last, sizeof(last));
#endif
    }
#ifdef CTRPORT_PLAYER_SHOTS
    if (60u > scanoutPaints || scanoutPaints % 300u == 0) {
        u16* lcd = moved ? shown : page;
        u32 pixels = menu != NULL ? (u32) menu->consoleWidth * 8u * 240u : 0u, lit = 0;
        bool same = moved && memcmp(shown, page, pixels * 2u) == 0;
        for (u32 i = 0; lcd != NULL && pixels > i; i++) lit += lcd[i] != 0;
        logInfo(scanoutLog, (unsigned) screen, moved ? "off the LCD" : "on the LCD", (unsigned long) painted,
                (unsigned long) first, (unsigned long) last, same ? "holds" : "does not hold", (unsigned long) lit,
                (unsigned long) pixels);
    }
    scanoutPaints++;
#endif
    hidScanInput();
}

#ifdef CTRPORT_PLAYER_SHOTS
// ===[ Test builds: what each refresh reads during a Game screen change (ctr_renderer.c's scanoutMove) ]===
//
// A thread above the main one polls citro3d's per-screen vblank counts and, at each screen's vblank, copies the buffer
// its framebuffer registers select, with the format they give: what that refresh reads (Azahar draws a screen from
// memory at its vblank). A picture the same as that screen's last one (address, format, bytes) is recorded without its
// bytes. The screens before and after the move are taken too. All of it goes to CTRPORT_GAME_DIR/scanout_move_NN.bin
// for a host decoder to compare byte for byte.
#include <stdio.h>
#include <stdlib.h>

u32 __real_C3D_FrameCounter(int id);
#define SCANOUT_TRACE_MAX 48u
typedef struct {
    u32 screen, vblank, format, phys, bytes, tag; // tag: 0 before, 1 a vblank, 2 after; +16 same as the last, +32 no memory
} ScanoutShot;
static struct {
    Thread thread;
    volatile bool run;
    u32 count, moves, phys[2][2];
    u8* virt[2][2];
    ScanoutShot shot[SCANOUT_TRACE_MAX];
    u8* data[SCANOUT_TRACE_MAX];
} scanoutTrace;

static void scanoutGrab(u32 screen, u32 vblank, u32 tag) {
    if (scanoutTrace.count >= SCANOUT_TRACE_MAX) return;
    u32 r[5] = { 0 };
    GSPGPU_ReadHWRegs(screen == GFX_TOP ? 0x400468u : 0x400568u, r, sizeof(r));
    u32 phys = (r[4] & 1u) != 0 ? r[1] : r[0], format = r[2] & 7u;
    u32 bytes = (screen == GFX_TOP ? 400u : 320u) * 240u * (format == 0u ? 4u : format == 1u ? 3u : 2u);
    u8* from = NULL;
    for (u32 i = 0; 2u > i; i++) if (scanoutTrace.phys[screen][i] == phys) from = scanoutTrace.virt[screen][i];
    if (from == NULL || bytes > (screen == GFX_TOP ? 400u : 320u) * 240u * 3u) tag |= 64u; // not a buffer of libctru's
    u32 n = scanoutTrace.count++;
    scanoutTrace.shot[n] = (ScanoutShot) { screen, vblank, format, phys, bytes, tag };
    scanoutTrace.data[n] = NULL;
    if ((tag & 64u) != 0) return;
    GSPGPU_InvalidateDataCache(from, bytes);
    s32 prev = -1;
    for (s32 i = (s32) n - 1; i >= 0 && prev < 0; i--) if (scanoutTrace.shot[i].screen == screen && scanoutTrace.data[i] != NULL) prev = i;
    if (prev >= 0 && scanoutTrace.shot[prev].phys == phys && scanoutTrace.shot[prev].format == format &&
        memcmp(scanoutTrace.data[prev], from, bytes) == 0) {
        scanoutTrace.shot[n].tag |= 16u;
        return;
    }
    u8* to = malloc(bytes);
    if (to == NULL) {
        scanoutTrace.shot[n].tag |= 32u;
        return;
    }
    memcpy(to, from, bytes);
    scanoutTrace.data[n] = to;
}

static void scanoutWatch(void* arg) {
    (void) arg;
    u32 last[2] = { __real_C3D_FrameCounter(0), __real_C3D_FrameCounter(1) };
    while (scanoutTrace.run) {
        for (u32 s = 0; 2u > s; s++) {
            u32 now = __real_C3D_FrameCounter((int) s);
            if (now != last[s]) scanoutGrab(s, now, 1u);
            last[s] = now;
        }
        svcSleepThread(100000);
    }
}

static void scanoutBuffers(void) {
    for (u32 s = 0; 2u > s; s++) {
        u8* now = (u8*) gfxGetFramebuffer((gfxScreen_t) s, GFX_LEFT, NULL, NULL);
        gfxSetDoubleBuffering((gfxScreen_t) s, false);
        u8* current = (u8*) gfxGetFramebuffer((gfxScreen_t) s, GFX_LEFT, NULL, NULL);
        gfxSetDoubleBuffering((gfxScreen_t) s, true);
        u8* other = (u8*) gfxGetFramebuffer((gfxScreen_t) s, GFX_LEFT, NULL, NULL);
        gfxSetDoubleBuffering((gfxScreen_t) s, now == other && other != current);
        scanoutTrace.virt[s][0] = current;
        scanoutTrace.virt[s][1] = other;
        for (u32 i = 0; 2u > i; i++) scanoutTrace.phys[s][i] = osConvertVirtToPhys(scanoutTrace.virt[s][i]);
    }
}

void CtrScanout_traceBegin(void);
void CtrScanout_traceBegin(void) {
    scanoutTrace.count = 0;
    scanoutBuffers();
    scanoutGrab(GFX_TOP, __real_C3D_FrameCounter(0), 0u);
    scanoutGrab(GFX_BOTTOM, __real_C3D_FrameCounter(1), 0u);
    scanoutTrace.run = true;
    s32 prio = 0x30;
    svcGetThreadPriority(&prio, CUR_THREAD_HANDLE);
    scanoutTrace.thread = threadCreate(scanoutWatch, NULL, 8192, prio > 0x19 ? prio - 8 : 0x18, -2, false);
}

void CtrScanout_traceEnd(void);
void CtrScanout_traceEnd(void) {
    for (u32 i = 0; 4u > i; i++) gspWaitForVBlank();
    scanoutTrace.run = false;
    if (scanoutTrace.thread != NULL) {
        threadJoin(scanoutTrace.thread, U64_MAX);
        threadFree(scanoutTrace.thread);
        scanoutTrace.thread = NULL;
    }
    scanoutGrab(GFX_TOP, __real_C3D_FrameCounter(0), 2u);
    scanoutGrab(GFX_BOTTOM, __real_C3D_FrameCounter(1), 2u);
    char name[96];
    snprintf(name, sizeof(name), "%s/scanout_move_%02lu.bin", CTRPORT_GAME_DIR, (unsigned long) scanoutTrace.moves++);
    FILE* f = fopen(name, "wb");
    u32 kept = 0;
    for (u32 i = 0; scanoutTrace.count > i; i++) {
        bool data = scanoutTrace.data[i] != NULL;
        if (!data) scanoutTrace.shot[i].bytes = 0;
        if (f != NULL) {
            fwrite(&scanoutTrace.shot[i], sizeof(ScanoutShot), 1, f);
            if (data) fwrite(scanoutTrace.data[i], 1, scanoutTrace.shot[i].bytes, f);
        }
        kept += data;
        free(scanoutTrace.data[i]);
        scanoutTrace.data[i] = NULL;
    }
    if (f != NULL) fclose(f);
    logInfo("scanout: Game screen change traced, %lu refreshes (%lu pictures) in %s\n", (unsigned long) scanoutTrace.count,
            (unsigned long) kept, name);
    scanoutTrace.count = 0;
}
#endif
