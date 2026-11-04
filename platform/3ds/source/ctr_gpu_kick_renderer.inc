#include "ctr_gpu_kick.h"
#define KICK_RENDER_TEXT __attribute__((noinline, section(".text.cheaplevers_kick_late")))
void __real_CtrRenderer_beginFrame(Renderer* renderer);
void __real_CtrRenderer_endFrame(Renderer* renderer);
void __real_CtrRenderer_stopBackgroundWork(Renderer* renderer);
void kickOriginalEndEarly(CtrRenderer* renderer, CtrSuspendedFrame* suspended) __asm__("endFrameEarly");
void kickOriginalResume(CtrRenderer* renderer, const CtrSuspendedFrame* suspended) __asm__("resumeFrame");

// Same barrier as runFrameSoFar: don't flush the pending batch recursively
// from an allocation inside that batch. No screen transfer or presentation.
KICK_RENDER_TEXT static void kickDrainRenderer(void* context) {
    CtrRenderer* r = context;
    CtrSuspendedFrame suspended;
    kickOriginalEndEarly(r, &suspended);
    kickOriginalResume(r, &suspended); // FrameBegin waits for the whole early run
}

// The Knight history wrappers (z_knightnew_history.c) stay outermost: when
// that chain is built, the launcher (cheaplevers_kick_compile.py,
// renderer_history_route) renames these two in the assembly so that the
// chain's calls of the real renderer come through them.
#define KICK_BEGIN __wrap_CtrRenderer_beginFrame
#define KICK_END __wrap_CtrRenderer_endFrame
//
//
//

// Rev2: tiles loading now (this frame's loads so far, a fill of the room's
// wanted tiles, or a page being read whole in the background).
KICK_RENDER_TEXT static bool kickTextureBusy(void* context) {
    const CtrTextureCache* t = &((CtrRenderer*) context)->textures;
    return t->frameLoadNanos != 0 || t->fillPending || t->filling || t->wholeRead != nullptr;
}

KICK_RENDER_TEXT void KICK_BEGIN(Renderer* renderer) {
    CtrRenderer* r = (CtrRenderer*) renderer;
    // The frame before's load time, until the textures' begin resets it.
    CtrKick_frameBegin(r->textures.frameLoadNanos != 0);
    CtrKick_setTextureProbe(kickTextureBusy);
    CtrKick_setDrain(kickDrainRenderer, renderer);
    __real_CtrRenderer_beginFrame(renderer);
    CtrKick_setFrame(r->frame);
}

KICK_RENDER_TEXT void KICK_END(Renderer* renderer) {
    __real_CtrRenderer_endFrame(renderer);
    // No kicks during chapter teardown or the next renderer's initialization.
    // Internal early end/resume barriers leave this registration intact.
    CtrKick_setDrain(nullptr, nullptr);
}

KICK_RENDER_TEXT void __wrap_CtrRenderer_stopBackgroundWork(Renderer* renderer) {
    // A worker under linear-memory pressure may wait on this recording's
    // fence. Finish the recording before the main thread joins that worker.
    CtrKick_pressureWait(0);
    __real_CtrRenderer_stopBackgroundWork(renderer);
}
