// utfade (UNDERTALE): a door's room change shows black while the new room loads, as the Switch 2 release does.
//
// main.c doesn't present the frame that calls room_goto (its Draw never ran), so the screen keeps the last fade-out
// frame through the whole room load: on a plain door that frame is only 56 % dark (one obj_unfader, +0.08 a step for
// 7 steps), and on the Old 3DS a first visit holds it 130 to 760 ms (change utfade, utfade-ft1 console rows). PC holds
// it 4 vblanks, then shows the new room at 92 % dark.
//
// Here, when that frame belongs to a door's fade to black, the room change first queues one black picture on the game
// screen (CtrPacer_utfadeBlack, ctr_frame_pacer.c's end): the screen's spare buffer filled black and flipped through
// the frames' own swap, held to the end of the room change frame's slot, the vblank that frame would have shown on.
// So the last fade-out frame keeps its 2 vblanks, black follows, and the room loads behind it. After the load the
// room change waits until the hold's last vblank has begun: the frame end's forced release of held flips
// (CtrPacer_frameEnding, "anything still held belongs to an earlier frame") would otherwise show the black early after
// a short load. The next frame waits for the vblank after that one anyway (CtrPacer_waitForSlot: its slot starts
// there; the frame end doesn't take the black for a late flip, CtrPacer_utfadeBlack sets this frame's catchUp), so the
// new room's first frame shows on the same vblank as before. Nothing is added to the game: no step, no event, no RNG
// call.
//
// A door's fade: obj_unfader in the room (the fade-out, made when the door is touched) and obj_persistentfader made
// (the fade-in every door makes in the step that calls room_goto: obj_doorA's Alarm 2 and the other doors', shops,
// game over), and the change goes to another room. The runner calls the room change every frame; with no change
// pending (pendingRoom -1) the test stops at its first compare. A room restart, the white naming fade
// (obj_whitefader), a battle's entry (obj_fader and the soul screen) and its exit (no persistent fader) keep the held
// frame as before.
//
// Hook (CMakeLists.txt, UNDERTALE only): CtrLoadmix_handleRoomChange's call of the real Runner_handlePendingRoomChange
// (ctr_loadaudio_mix.inc, which freebies' wrap calls) comes here, and this file's call goes on to utwindow's
// CtrUtWindow_pendingRoom, which calls the real one (tools/analysis/test_utwindow_chain.py checks the chain). Late
// code, constants and statics only (late_reserve.ld): nothing that existed before moves.
#if defined(ENABLE_WAD16) && defined(__3DS__)
#include "ctr_frame_pacer.h"
#include "ctr_gpu_queue.h"
#include "instance.h"
#include "runner.h"
#include "stb_ds.h"

#define UF_TEXT __attribute__((noinline, section(".text_utfade")))
// The two objects' names, one after the other (as z_argbind.c's).
static const char ufNames[] __attribute__((section(".rodata.utfade_late"))) = "obj_unfader\0obj_persistentfader";

void CtrPacer_utfadeBlack(bool fill);
void __real_Runner_handlePendingRoomChange(Runner* runner);
void CtrUtfade_pendingRoom(Runner* runner);

// A door's fade: the change goes to another room, and both objects have an instance in the room.
static UF_TEXT bool ufDoor(Runner* runner) {
    int32_t to = runner->pendingRoom;
    if (0 > to || to == runner->currentRoomIndex) return false;
    const char* name = ufNames;
    for (uint32_t i = 0; 2u > i; i++, name += sizeof("obj_unfader")) {
        uint32_t obj = (uint32_t) shget(runner->assetsByName, (char*) name); // missing: -1, so past the count
        if (obj >= runner->dataWin->objt.count || arrlen(runner->instancesByObject[obj]) == 0) return false;
    }
    return true;
}

#ifdef CTRPORT_UTFADE_PROBE
#include <stdio.h>
#include "log.h"
static void ufProbe(Runner* runner, int32_t from, int32_t to, bool armed);
static int8_t ufProbeOff = -1;
#endif

UF_TEXT void CtrUtfade_pendingRoom(Runner* runner) {
    bool armed = ufDoor(runner);
#ifdef CTRPORT_UTFADE_PROBE
    int32_t from = runner->currentRoomIndex, to = runner->pendingRoom;
    if (0 > ufProbeOff) {
        FILE* f = fopen("sdmc:/3ds/undertale-3ds/utfade_off.txt", "rb");
        ufProbeOff = f != NULL;
        if (f != NULL) fclose(f);
    }
    if (ufProbeOff) armed = false;
#endif
    if (armed) CtrPacer_utfadeBlack(true);
    __real_Runner_handlePendingRoomChange(runner);
    if (armed) CtrPacer_utfadeBlack(false);
#ifdef CTRPORT_UTFADE_PROBE
    ufProbe(runner, from, to, armed);
#endif
}

#ifdef CTRPORT_UTFADE_PROBE
// TEST ONLY (build.sh utfadeprobe, never Release): after every room change's load, once the game screen shows what
// it will show until the new room's first frame (the GPU idle, no flip held or pending), that picture is written as
// it sits in memory to uf_<frame>_<from>_<to>_<armed>_<W>x<H>x3.bin in the game folder (a small script turns
// them into PNGs). utfade_off.txt in the game folder turns the black off, for the same build's picture without it.
// The waits and the write make room changes slower in this build alone.
extern uint8_t CtrScreens_pacerGame;
void CtrScreens_pacerWaitShown(gfxScreen_t screen, bool nextEvent);
static void ufProbe(Runner* runner, int32_t from, int32_t to, bool armed) {
    if (0 > to) return; // no change this frame (handlePendingRoomChange runs every frame), or a restart
    gfxScreen_t screen = (gfxScreen_t) CtrScreens_pacerGame;
    CtrGpu_waitIdle();
    while (!CtrPacer_screenReady(screen)) CtrScreens_pacerWaitShown(screen, true);
    u16 w = 0, h = 0;
    u8* fb = CtrPacer_shownFramebuffer(screen, GFX_LEFT, &w, &h);
    if (fb == NULL) return;
    u32 bytes = (u32) w * h * 3u;
    GSPGPU_InvalidateDataCache(fb, bytes);
    uint32_t lit = 0, fnv = 2166136261u;
    for (u32 i = 0; bytes > i; i++) {
        lit += fb[i] != 0;
        fnv = (fnv ^ fb[i]) * 16777619u;
    }
    logInfo("utfadeprobe: frame %d room %ld -> %ld armed %d screen %d %ux%u: %lu nonzero bytes, fnv %08lx\n",
            runner->frameCount, (long) from, (long) to, armed ? 1 : 0, (int) screen, (unsigned) w, (unsigned) h,
            (unsigned long) lit, (unsigned long) fnv);
    char path[128];
    snprintf(path, sizeof(path), "sdmc:/3ds/undertale-3ds/uf_%05d_%ld_%ld_%d_%ux%ux3.bin", runner->frameCount,
             (long) from, (long) to, armed ? 1 : 0, (unsigned) w, (unsigned) h);
    FILE* f = fopen(path, "wb");
    if (f == NULL) return;
    fwrite(fb, 1, bytes, f);
    fclose(f);
}
#endif
#endif
