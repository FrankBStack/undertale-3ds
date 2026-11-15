// Game-over presentation only. Compiled independently by utwindow_compile.py;
// its ordinary renderer bodies and data are discarded. Keep the unit removable.
#if defined(ENABLE_WAD16) && defined(CTRPORT_GAMEOVERSCREEN_HELPER)
#include "instance.h"
#include "vm.h"
#include "stb_ds.h"
#include "ctr_battletouch.h"
#include "ctr_bottom_view.h"
#include "ctr_place.h"

#define GO_CODE __attribute__((noinline, noipa, used, optimize("Os"), section(".text_gameoverscreen")))
enum { GO_ROOM, GO_HEART, GO_FAKE, GO_DEFEATED, GO_SHARD, GO_LOGO, GO_UNFADER, GO_FADER };
enum { GO_ACTIVE=1, GO_ENTER=2, GO_DELTA=4, GO_FAKE_SEEN=8, GO_GAME=16, GO_GIVEN=32 };
static struct {
    DataWin* dw;
    uint16_t id[8];
    float shownX, shownY, dx, dy;
    int32_t frame;
    uint32_t display, flags;
} go __attribute__((section(".bss_gameoverscreen,\"aw\",%nobits @")));
_Static_assert(sizeof(go)==48, "approved game-over state ceiling");
static const char goNames[120] __attribute__((section(".rodata_gameoverscreen"))) =
    "room_gameover\0obj_heart\0obj_fakeheart\0obj_heartdefeated\0obj_heartshard\0obj_gameoverbg\0obj_unfader\0obj_persistentfader";

bool CtrBattlesplit_gameoverOther(void);
void CtrBattlesplit_gameoverReturn(Renderer* renderer);
bool CtrLayout_gameoverRole(Renderer* renderer, bool below);
void CtrLayout_chain18(Renderer* renderer);
void CtrLayout_display18(Renderer* renderer, const CtrDisplaySettings* settings);
void __real_CtrRenderer_chainDisplayInputlate(Renderer* renderer, const CtrDisplaySettings* settings);
void CtrLayout_yield8(Renderer* renderer, bool yield);
void __real_Runner_handlePendingRoomChange(Runner* runner);
void CtrDlgtop_begin(Renderer* renderer);
extern bool CtrScreens_gameGiven;
void __real_CtrMenutime_open(void* menu, PrintConsole* console,
                           const CtrDisplaySettings* settings, CtrDisplayCaps caps);

static GO_CODE void goResolve(Runner* runner) {
    if (go.dw == runner->dataWin) return;
    // Every ID and every live pose/display field is overwritten before use.
    // Retire the old session without clearing unused storage or calling memset.
    go.flags = 0;
    go.dw = runner->dataWin;
    go.frame = -4;
    const char* name = goNames;
    for (unsigned i=0; i<8; i++) {
        // WAD16 asset IDs fit uint16_t; the missing-name value -1 becomes 65535.
        go.id[i] = (uint16_t) shget(runner->assetsByName, (char*) name);
        name += strlen(name)+1;
    }
}

// Same sprite ABI, below the logical draw hash and all smoothing dispatch.
// No VM field, instance coordinate, alarm or RNG state is written.
static GO_CODE void goDrawSprite(bool coarse, Renderer* renderer, int32_t tpag, float x, float y, float ox, float oy,
                                    float sx, float sy, float angle, uint32_t color, float alpha) {
    Runner* runner = renderer->runner;
    Instance* inst = runner != nullptr && runner->vmContext != nullptr ? runner->vmContext->currentInstance : nullptr;
    if (inst != nullptr && go.dw == runner->dataWin) {
        int32_t obj = inst->objectIndex;
        if ((go.flags & GO_ACTIVE) != 0) {
            if (obj == go.id[GO_DEFEATED] || obj == go.id[GO_SHARD]) {
                if ((go.flags & GO_DELTA) == 0) {
                    go.dx = go.shownX-x;
                    go.dy = go.shownY-y;
                    go.flags |= GO_DELTA;
                }
                x += go.dx;
                y += go.dy;
            }
        } else if ((obj == go.id[GO_HEART] || obj == go.id[GO_FAKE]) && alpha > 0.0f) {
            CtrBottomView view;
            if (!CtrBattlesplit_gameoverOther()) go.frame = -4;
            else if (CtrLayout_bottomView(runner, &view) &&
                (go.frame != runner->frameCount || (go.flags & GO_FAKE_SEEN) == 0 || obj == go.id[GO_FAKE])) {
                go.shownX = (x-view.roomX0)/view.roomPerPx*2.0f;
                go.shownY = (y-view.roomY0)/view.roomPerPx*2.0f;
                int32_t seam, lift;
                if (CtrLayout_bottomSeam(&seam, &lift) && go.shownY*0.5f+(float) lift >= (float) seam)
                    go.shownY += 2.0f*(float) lift;
                go.frame = runner->frameCount;
                go.flags = obj == go.id[GO_FAKE] ? GO_FAKE_SEEN : 0;
            }
        }
    }
    if (coarse && (go.flags & GO_ACTIVE) == 0)
        utkDrawSpriteBody(renderer, tpag, x, y, ox, oy, sx, sy, angle, color, alpha);
    else
        ctrDrawSprite(renderer, tpag, x, y, ox, oy, sx, sy, angle, color, alpha);
}

// Both entry points keep the original sprite ABI. The coarse guard records a
// Crisp SOUL too; during death it bypasses batching so every shard is translated.
GO_CODE void CtrGameover_drawSprite(Renderer* renderer, int32_t tpag, float x, float y, float ox, float oy,
                                    float sx, float sy, float angle, uint32_t color, float alpha) {
    goDrawSprite(false, renderer, tpag, x, y, ox, oy, sx, sy, angle, color, alpha);
}
GO_CODE void CtrGameover_coarseSprite(Renderer* renderer, int32_t tpag, float x, float y, float ox, float oy,
                                      float sx, float sy, float angle, uint32_t color, float alpha) {
    goDrawSprite(true, renderer, tpag, x, y, ox, oy, sx, sy, angle, color, alpha);
}

// The bottom already contains the SOUL. Change the other screen's role using
// its spare only; never carry the old top battle over the bottom SOUL.
static GO_CODE void goEnter(CtrRenderer* r) {
    CtrGpu_waitIdle();
    while (!CtrPacer_screenReady(GFX_TOP)) CtrScreens_pacerWaitShown(GFX_TOP, true);
    while (!CtrPacer_screenReady(GFX_BOTTOM)) CtrScreens_pacerWaitShown(GFX_BOTTOM, true);
    CtrLog_setConsoleEnabled(false);
    CtrLog_beginConsole();
    u8* spare = CtrPacer_backFramebuffer(GFX_TOP, GFX_LEFT);
    memset(spare, 0, 400u*240u*2u);
    GSPGPU_FlushDataCache(spare, 400u*240u*2u);
    CtrRenderer_bsLeave8(&r->base, false);
    CtrLayout_gameoverRole(&r->base, true);
    gfxSetScreenFormat(GFX_TOP, GSP_RGB565_OES);
    gfxSetScreenFormat(GFX_BOTTOM, GSP_BGR8_OES);
    gfxSetDoubleBuffering(GFX_BOTTOM, true);
    CtrScreens_pacerShow(GFX_TOP);
    while (!CtrPacer_screenReady(GFX_TOP)) CtrScreens_pacerWaitShown(GFX_TOP, true);
    gfxSetDoubleBuffering(GFX_TOP, false);
    CtrScreens_moveConsoles(true);
    CtrPacer_setGameScreen(GFX_BOTTOM);
    CtrScreens_onBottom = true;
    go.display = CtrRenderer_bsMoveGame(&r->base, true, 0);
    CtrScreens_game = 1;
    CtrScreens_gameGiven = true;
    CtrLog_endConsole();
    go.flags &= ~GO_ENTER;
}

GO_CODE void CtrGameover_beginFrame(Renderer* renderer) {
    if (renderer->runner != nullptr && renderer->runner->dataWin != nullptr) goResolve(renderer->runner);
    if ((go.flags & GO_ACTIVE) == 0) {
        CtrLayout_chain18(renderer);
        return;
    }
    CtrRenderer* r = (CtrRenderer*) renderer;
    if ((go.flags & GO_ENTER) != 0) goEnter(r);
    r->displayDirty = false;
    r->bottomYielded = false;
    CtrDlgtop_begin(renderer);
    r->dlg.shown = true;
}

// Gate both main callers before timing, page composition, sound or audio hold.
// Nothing is queued: this request is consumed, not replayed after hand-back.
GO_CODE void __wrap_CtrMenutime_open(void* menu, PrintConsole* console,
                                   const CtrDisplaySettings* settings, CtrDisplayCaps caps) {
    if ((go.flags & GO_ACTIVE)==0) __real_CtrMenutime_open(menu, console, settings, caps);
}

// Real beginFrame takes the screenshot before dirty setup. Keep that readback
// and notice lifetime, but never interpret this held role as a Game pick.
GO_CODE void CtrGameover_configure(CtrRenderer* renderer) {
    if ((go.flags & GO_ACTIVE)==0) configureScreens(renderer);
}

GO_CODE void CtrGameover_display(Renderer* renderer, const CtrDisplaySettings* settings) {
    if ((go.flags & GO_ACTIVE) == 0) {
        CtrLayout_display18(renderer, settings);
        return;
    }
    // The frame's input still goes in (battletouch's game-over tap is a stylus sample): inputlate's link, as
    // CtrLayout_display18 calls it inside a frame, given the renderer's own display, so its real setDisplay is a no-op.
    CtrRenderer* r = (CtrRenderer*) renderer;
    if (r->inFrame) __real_CtrRenderer_chainDisplayInputlate(renderer, &r->display);
    r->displayDirty = false;
}

GO_CODE void CtrGameover_yield(Renderer* renderer, bool yield) {
    if ((go.flags & GO_ACTIVE) == 0) {
        CtrLayout_yield8(renderer, yield);
        return;
    }
    CtrRenderer* r = (CtrRenderer*) renderer;
    r->bottomYielded = false;
    r->displayDirty = false;
    r->dlg.shown = true;
}

// utfade has already queued the game's black outgoing fade before this link.
// Return physical ownership before initRoom, not on the first revealed frame.
GO_CODE void CtrGameover_pendingRoom(Runner* runner) {
    int32_t to = runner->pendingRoom;
    if (to != -1 && to != runner->currentRoomIndex) {
        if ((go.flags & GO_ACTIVE) != 0) {
            CtrRenderer* r = (CtrRenderer*) runner->renderer;
            CtrScreens_game = (go.flags & GO_GAME) != 0;
            CtrScreens_gameGiven = (go.flags & GO_GIVEN) != 0;
            CtrBattlesplit_gameoverReturn(runner->renderer);
            CtrRenderer_bsMoveGame(runner->renderer, false, go.display);
            CtrLayout_gameoverRole(runner->renderer, CtrScreens_gameBelow());
            r->dlg.shown = false;
            go.flags = 0;
            go.frame = -4;
        } else if (to == go.id[GO_ROOM] && go.dw == runner->dataWin && CtrLayout_targetsHeld() &&
                   (unsigned) (runner->frameCount-go.frame) <= 2u) {
            go.flags = GO_ACTIVE | GO_ENTER | (CtrScreens_game ? GO_GAME : 0) | (CtrScreens_gameGiven ? GO_GIVEN : 0);
            // The other LCD becomes black. Keep room-load messages on SD;
            // queuing them for its retiring console makes goEnter drain them
            // while the player is still looking at the last SOUL frame.
            CtrLog_setConsoleEnabled(false);
        }
    }
    __real_Runner_handlePendingRoomChange(runner);
}

// asgsmart F1u (11-14): utkDrawSprite and this unit's two sprite entries as one call. utwindow_compile.py points the
// alpha stub's target word for utkDrawSprite (abqTargets slot 25) here, so the stub's alpha adaptation still comes
// first. Whatever game over could act on (its active state, or the current object being either heart) goes to
// utkDrawSprite whole, before the gate counts. Otherwise goDrawSprite would only hand the call on unchanged, so this
// makes its two calls direct: utkDrawSprite's rejection branch as it is, and its plain body. The renderer's gate and
// draws are reached by their assembler names in the combined assembly; utwindow_compile.py checks each one.
// Timing and forced-split builds keep the old path (their utaTakes differs, or UTK_DRAW_SPRITE is ctrDrawSprite).
#if !defined(CTRPORT_RENDER_TIMING) && ASG_FORCE_SPLIT == 0
__attribute__((noinline, noipa, used)) UT_COLD_TEXT(asgfuse)
void CtrGameover_fuseSprite(Renderer* renderer, int32_t tpagIndex, float x, float y, float originX, float originY,
                            float xscale, float yscale, float angleDeg, uint32_t color, float alpha) {
    const CtrRenderer* r = (const CtrRenderer*) renderer;
    Runner* runner = renderer->runner;
    Instance* inst = runner != nullptr && runner->vmContext != nullptr ? runner->vmContext->currentInstance : nullptr;
    if ((go.flags & GO_ACTIVE) != 0 || (inst != nullptr && (inst->objectIndex == go.id[GO_HEART] || inst->objectIndex == go.id[GO_FAKE]))) {
        utkDrawSprite(renderer, tpagIndex, x, y, originX, originY, xscale, yscale, angleDeg, color, alpha);
        return;
    }
    if (0 > tpagIndex || (uint32_t) tpagIndex >= r->originalTpagCount ||
        (r->smart.active && r->smart.itemState != nullptr && (r->smart.itemState[tpagIndex] & ITEM_FINE) != 0) || !utkPlainState(r)) {
        if (utaTakes(r)) aslFineSprite(renderer, tpagIndex, x, y, originX, originY, xscale, yscale, angleDeg, color, alpha);
        else ctrDrawSprite(renderer, tpagIndex, x, y, originX, originY, xscale, yscale, angleDeg, color, alpha);
        return;
    }
    utkDrawSpriteBody(renderer, tpagIndex, x, y, originX, originY, xscale, yscale, angleDeg, color, alpha);
}
#endif
#endif
