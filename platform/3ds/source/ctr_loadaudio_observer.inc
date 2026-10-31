// Diagnostic only: observe the unchanged transport, including a flowhitch spare.
// The experimental clock/room gate is retained in history and its frozen builds.
// No physical pause, game clock/query substitution, source preparation or seek.
#define CTRPORT_LOADAUDIO_OBSERVER_ONLY 1
// The control skips preparation itself, never reads an already advanced spare
// without its first buffer. Both arms retain the same reader, layout and cache.
LAT_CODE static bool latPreparationOn(void) {
#ifdef CTRPORT_LOADAUDIO_CONTROL
    return false;
#else
    return true;
#endif
}

LAT_CODE static void latClock(unsigned id, uint32_t* words) {
    (void) id;
    memset(words, 0, 6 * sizeof(*words));
}
#include "ctr_loadaudio_trace.inc"

LAT_CODE void CtrLoadaudio_boundary(Runner* runner, bool loaded) {
    latBoundary(runner, loaded);
}

LAT_CODE void CtrLoadaudio_chainEndFrame(Renderer* renderer) {
    bool skipped = CtrRenderer_frameSkipped(renderer);
    bool ready = lat.frameReady && renderer->runner == lat.runner;
    CTR_ENDFRAME_AFTER_LOADAUDIO(renderer);
    if (ready && !skipped) latPresented(renderer);
    latFrame(renderer, skipped);
    latDrain();
}
