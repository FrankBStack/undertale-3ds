// UNDERTALE room-load transport gate. Included only by ctr_audio_system.c's tail,
// or by the host fixture. The logical voices and stream/feeder implementations
// are shared with ordinary playback; only the physical pause bit is combined.
#define LA_TEXT __attribute__((noinline, noipa, optimize("Os"), section(".text.late.loadaudio")))
#define LA_BSS __attribute__((section(".bss.late.loadaudio")))
#define LA_COLLECTING (1u << VOICE_COUNT)

// The assembly-defined table adds no compiler call-graph/variable edges to the
// old audio object. New direct edges would reorder its original code and BSS.
typedef struct {
    CtrAudioSystem** target;
    void (*apply)(CtrAudioSystem*, int);
} LaLegacy;
extern const LaLegacy CtrLoadaudio_legacy;

static struct {
    CtrAudioSystem* audio; // release/acquire publication to the opener
    Runner* runner;
    uint32_t first; // first serial assigned by the current room's events
    uint32_t mask;
    uint32_t serial[VOICE_COUNT]; // identity, so a reused logical slot is safe
    bool ready; // game thread only: Draw and audio update have completed
} la LA_BSS;

LA_TEXT static void laReset(void) {
    // NULL publishes no other state; it only disables the physical gate.
    __atomic_store_n(&la.audio, NULL, __ATOMIC_RELAXED);
}

LA_TEXT static bool laPaused(int id, bool paused) {
#ifdef CTR_AUDIO_PCM_HASH
    if (!latGateOn()) return paused;
#endif
    if (paused) return true;
    if (laClockPaused(id)) return true;
    CtrAudioSystem* ca = __atomic_load_n(&la.audio, __ATOMIC_ACQUIRE);
    if (ca == NULL || (unsigned) id >= VOICE_COUNT) return paused;
    Voice* v = &ca->voices[id];
    uint32_t mask = __atomic_load_n(&la.mask, __ATOMIC_ACQUIRE);
    if (mask & LA_COLLECTING) {
        uint32_t first = __atomic_load_n(&la.first, __ATOMIC_RELAXED);
        if ((uint32_t) (v->serial - first) <
            (uint32_t) (__atomic_load_n(&ca->serialCounter, __ATOMIC_RELAXED) - first)) return true;
    }
    return paused || ((mask & (1u << id)) && la.serial[id] == v->serial);
}

// Called before pending room events, after them, and (loaded=false) after the
// ordinary frame's Draw/update. The prefetch contains no new game play requests.
// Close the serial interval after events so a later menu's UI starts can sound.
LA_TEXT void CtrLoadaudio_boundary(Runner* runner, bool loaded) {
    CtrAudioSystem* ca = *CtrLoadaudio_legacy.target;
    if (ca == NULL || !ca->ndspReady) return;
    if (!loaded) laClockFrame(ca, runner);
#ifdef CTR_AUDIO_PCM_HASH
    latBoundary(runner, loaded);
#endif
    if (loaded) {
        uint32_t mask = __atomic_load_n(&la.mask, __ATOMIC_RELAXED) & ~LA_COLLECTING;
        uint32_t count = ca->serialCounter - la.first;
        for (unsigned i = 0; i < VOICE_COUNT; i++) {
            Voice* v = &ca->voices[i];
            if (v->kind != VOICE_FREE &&
                (uint32_t) (v->serial - la.first) < count) {
                la.serial[i] = v->serial;
                mask |= 1u << i;
            }
        }
        __atomic_store_n(&la.mask, mask, __ATOMIC_RELEASE);
    } else if (runner->pendingRoom != -1) {
        uint32_t mask = __atomic_load_n(&la.audio, __ATOMIC_RELAXED) == ca ? la.mask : 0;
        la.runner = runner;
        __atomic_store_n(&la.first, ca->serialCounter, __ATOMIC_RELAXED);
        la.ready = false;
        __atomic_store_n(&la.mask, mask | LA_COLLECTING, __ATOMIC_RELEASE);
        __atomic_store_n(&la.audio, ca, __ATOMIC_RELEASE);
    } else if (__atomic_load_n(&la.audio, __ATOMIC_RELAXED) == ca) {
        la.ready = true;
    }
}

// This chain is reached by menu and software-keyboard frames too. Only the
// completed game's Draw/update marker may release, and a skipped frame consumes
// that marker without releasing. The next game frame must mark itself ready.
LA_TEXT void CtrLoadaudio_chainEndFrame(Renderer* renderer) {
    CtrAudioSystem* ca = __atomic_load_n(&la.audio, __ATOMIC_ACQUIRE);
    bool release = false;
    if (ca != NULL && renderer->runner == la.runner && la.ready) {
        la.ready = false;
        release = !CtrRenderer_frameSkipped(renderer);
    }
#ifdef CTR_AUDIO_PCM_HASH
    bool traceSkipped = CtrRenderer_frameSkipped(renderer);
#endif
    CTR_ENDFRAME_AFTER_LOADAUDIO(renderer);
#ifdef CTR_AUDIO_PCM_HASH
    if (release) latPresented(renderer);
    latFrame(renderer, traceSkipped);
    latDrain();
#endif
    if (!release) return;
    laReset();
    for (unsigned i = 0; i < VOICE_COUNT; i++) {
        Voice* v = &ca->voices[i];
        if ((la.mask & (1u << i)) && v->kind != VOICE_FREE && v->serial == la.serial[i]) {
            CtrLoadaudio_legacy.apply(ca, (int) i);
        }
    }
}
