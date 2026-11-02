// argbind (exitpanic, 2026-10-31; DELTARUNE only, empty in UNDERTALE): argui's per-load pointers follow a
// chapter switch from its first frame.
//
// Why: argui's state (ctr_argui.c's CtrArgui_state: the texture cache, the audio system and five asset indices) is
// set only in its CtrTextures_prefetchRoom wrap, and main.c calls that after a frame's end, when the room changed.
// After DELTARUNE's game_change the old renderer, texture cache, data.win and audio system are freed and new ones
// made, but until the new load's first prefetch the state still names the old ones. Anything that reads it on the new
// load's first frame read freed memory: argui's painter (first-boot hint, FPS counter) at that frame's swap, the
// options menu opened on that frame (optText, optGlyph, optTexel), and its sounds. A load whose first frame quits (a
// held SELECT+START chord) never prefetches at all, so every swap of its exit did the same: Azahar n3DS, frozen
// stage75zd ch5_flowcut quitting on the chapter select's frame 0, 4,710 unmapped reads from optText, optGlyph and the
// audio system's sound lookups (docs/3ds-hardware.md, "Options menu text and sounds read the freed chapter at a
// chapter switch").
//
// The old values must also go before the old load is freed: the new renderer's screen set-up (ctrInit's
// configureScreens, before its CtrTextures_init) swaps buffers, and with the game on the bottom screen and the FPS
// counter there argui's painter drew its digits through the freed cache (c26rev round 65 F1; Azahar n3DS, frozen
// stage75zf, 864 unmapped reads in arguiSampleGlyph during the chapter select's load). So main.c's
// CtrChapters_unloadGame call (renamed the same way) first empties the cache and audio pointers. The painter returns
// on an empty cache and optmenu's sound ignores an empty audio pointer, but menu drawing does not check the cache
// (optText's fallback reads it through optTexel): it is safe only because no menu can open or update between this
// unload and the session hook below. A menu reachable during a load would need its own check.
//
// What it does: the texture cache's set-up (ctr_renderer.c's one CtrTextures_init call, renamed by CMakeLists.txt)
// points the state at the new cache once it is set up, and the session's start (main.c's CtrBench_sessionStartedLate
// call, renamed the same way, after Runner_create and before the first room) gives it the new audio system and the
// new data.win's asset indices. These are the values argui's prefetch wrap sets one frame later; it still sets them
// at each room change as before. Nothing else changes. The first load gets them a frame earlier too (its state was
// empty until then: a menu opened on its first frame read through a null cache).
//
// All late (late_reserve.ld, last): code in .text.argbind_late, its names in late rodata (.rodata.argbind_late: the
// word 8 B after DELTARUNE New's ARM-to-Thumb veneer, which ld puts after the last late code, must stay padding).
// No statics.
#include <3ds.h>
#include <stdint.h>
#include <string.h>

#include "audio_system.h"
#include "ctr_chapters.h"
#include "ctr_benchmark.h"
#include "ctr_textures.h"
#include "data_win.h"
#include "runner.h"
#include "stb_ds.h"

#if defined(ENABLE_WAD17)

#define ARGBIND_CODE __attribute__((noinline, section(".text.argbind_late")))
#define ARGBIND_RO __attribute__((section(".rodata.argbind_late")))

// argui's state (ctr_argui.c, a global): the same layout (as ctr_optmenu.c declares it).
typedef struct {
    uint8_t cfg[3];
    bool menuIsOpen;
    uint8_t sx;
    uint8_t sy;
    uint8_t adv;
    bool rgb565;
    char fpsBuf[3];
    uint16_t hintFrames;
    uint16_t fpsFrames;
    int16_t assetIds[5]; // sndMove, sndSelect, fntSmall, fntTheme, sprHeartSmall
    uint32_t fpsVb;
    void* fb;
    CtrTextureCache* texCache;
    AudioSystem* audio;
} ArguiState;

extern ArguiState CtrArgui_state;

// ctr_argui.c's DELTARUNE names, in assetIds order, one after another.
static const char argbindNames[] ARGBIND_RO = "snd_menumove\0snd_select\0fnt_small\0fnt_main\0spr_heartsmall";

void CtrArgbind_texturesInit(CtrTextureCache* cache, DataWin* dw, FileSystem* fs, uint32_t budgetBytes);
void CtrArgbind_sessionStartedLate(const CtrBenchSession* session);
void CtrArgbind_unloadGame(Runner* runner);

ARGBIND_CODE void CtrArgbind_texturesInit(CtrTextureCache* cache, DataWin* dw, FileSystem* fs, uint32_t budgetBytes) {
    CtrTextures_init(cache, dw, fs, budgetBytes);
    CtrArgui_state.texCache = cache;
}

ARGBIND_CODE void CtrArgbind_sessionStartedLate(const CtrBenchSession* session) {
    Runner* runner = session->runner;
    CtrArgui_state.audio = runner->audioSystem;
    const char* name = argbindNames;
    for (uint32_t i = 0; 5u > i; i++) {
        CtrArgui_state.assetIds[i] = (int16_t) shget(runner->assetsByName, name);
        name += strlen(name) + 1u;
    }
    CtrBench_sessionStartedLate(session);
}

// Before the old load's audio system, renderer and texture cache are freed (ctr_chapters.c), argui forgets them.
ARGBIND_CODE void CtrArgbind_unloadGame(Runner* runner) {
    CtrArgui_state.texCache = nullptr;
    CtrArgui_state.audio = nullptr;
    CtrChapters_unloadGame(runner);
}

#endif

#if defined(ENABLE_WAD17)
// A null check alone does not retire an in-flight GSP-thread paint: its cache
// invalidate IPC can yield while the main thread nulls and frees the cache.
// Try-lock in the painter, so the GSP event thread never blocks on main. Only
// unload waits; it releases the lock before any renderer/GPU teardown waits.
// LightLock_Init in the installed libctru stores 1 (unlocked).
static LightLock fps75PaintLock __attribute__((section(".data.fpsbox75zm_late"))) = 1;
#define FPS75_LIFETIME __attribute__((noinline, noipa, optimize("Os"), section(".text.fpsbox75zm_late")))
bool CtrFpsbox_tryPaint(void);
void CtrFpsbox_endPaint(void);
void __real_CtrArgbind_unloadGame(Runner* runner);
void __wrap_CtrArgbind_unloadGame(Runner* runner);

FPS75_LIFETIME bool CtrFpsbox_tryPaint(void) {
    if (threadGetCurrent() == nullptr) return true; // only main can unload; do not exclude the swap painter
    if (LightLock_TryLock(&fps75PaintLock)) return false;
    if (CtrArgui_state.texCache != nullptr) return true;
    LightLock_Unlock(&fps75PaintLock);
    return false;
}

FPS75_LIFETIME void CtrFpsbox_endPaint(void) {
    if (threadGetCurrent() != nullptr) LightLock_Unlock(&fps75PaintLock);
}

FPS75_LIFETIME void __wrap_CtrArgbind_unloadGame(Runner* runner) {
    LightLock_Lock(&fps75PaintLock);
    CtrArgui_state.texCache = nullptr;
    CtrArgui_state.assetIds[2] = CtrArgui_state.assetIds[3] = CtrArgui_state.assetIds[4] = -1;
    LightLock_Unlock(&fps75PaintLock);
    __real_CtrArgbind_unloadGame(runner);
}
#endif
