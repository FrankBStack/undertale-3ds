// Hidden room loads: request on the game thread, apply on the DSP callback.
// No wait, source walk, vtable replacement or per-voice clock on the requester.
#define LM_BSS __attribute__((section(".bss.late.loadaudio")))
// File-name lookup hashes only. The existing phase-song spare opens the next
// intro/fight song at its quiet second; flowhitch prepares its first buffer.
// No new decoder, PCM store, play request or source-position change.
const uint32_t CtrLoadmix_songs[2][2]
    __attribute__((aligned(4), section(".rodata.late.loadaudio"))) = {
        {0x7CDAE4A4u, 0x407AC0B1u}, {0x407AC0B1u, 0x14354745u}
    };
extern const struct {
    CtrAudioSystem** target;
    void (*callback)(void*);
    ndspCallback* engine;
    LightLock* lock;
    UtaChan* channels;
    int8_t* inverse;
    volatile bool* mapped;
} CtrLoadmix_legacy;
#ifndef LM_HOST
__asm__(".pushsection .rodata.late.loadaudio,\"a\",%progbits\n.p2align 2\n"
        ".global CtrLoadmix_legacy\n.type CtrLoadmix_legacy,%object\nCtrLoadmix_legacy:\n"
        ".word gShutdownTarget,utaFrameCallback,utaEngineCallback,utaLock,utaChan,utaInv,utaMapped\n"
        ".size CtrLoadmix_legacy,.-CtrLoadmix_legacy\n.popsection\n");
#endif

static struct {
    // command: bit 0 is an open load window, bit 1 publishes its fields.
    // Totals wrap together; their signed difference is only one DSP update.
    uint32_t command, applied, dirty, goal, start;
    uint32_t frame; // game thread only, at the outgoing Step/Draw boundary
    uint32_t lastTick, heldTicks; // DSP thread only, actual physical hold time
    uint32_t watchCommand, emptyTick, unusedTicks, creditTicks; // DSP thread only
    Runner* runner;
    bool rampHeld; // decode thread only
    uint8_t waiting; // DSP: 1 initial, 2 last update empty, 3 unknown, 0 decided
} lm LM_BSS;

// Two real display vblanks per 30 Hz game frame, as in ctr_music_clock.h.
// Count in ARM11 ticks: no rounded milliseconds or per-load rounding loss.
#define LM_FRAME_TICKS 8962272u

#ifdef CTR_AUDIO_PCM_HASH
// Frozen diagnostic twins change only this slot: the load hold and the two
// additional song guesses. Rev 3m's original preparation stays on in both.
static volatile const uint32_t lmdEnabled
    __attribute__((used, section(".rodata.late.loadaudio"))) = 1;
LM_CODE bool CtrLoadmix_preparing(void) { return lmdEnabled != 0; }
typedef struct {
    u64 tick;
    uint32_t kind, command, applied, vblank, detail, frame;
    uint32_t voice[24], sequence[24], position[24];
    bool ready, printed;
} LmdEvent;
static struct {
    LmdEvent events[256];
    uint32_t count, overflow, generation, remaining;
    bool held, overflowPrinted;
} lmd LM_BSS;
static const char lmdHeader[] __attribute__((section(".rodata.late.loadaudio"))) =
    "[loadmix] %lu %lu %lu %lu %llu %lu %lu %lu\n";
// One fixed record format: kind 1..9 is an event; 10 is a physical cursor
// (channel, voice, sequence, position, 0, 0); 11 marks an incomplete ring.

LM_CODE static void lmdEvent(uint32_t kind, uint32_t detail) {
    uint32_t index = __atomic_fetch_add(&lmd.count, 1, __ATOMIC_RELAXED);
    if (index >= 256) { __atomic_store_n(&lmd.overflow, 1, __ATOMIC_RELEASE); return; }
    LmdEvent* row = &lmd.events[index];
    row->tick = svcGetSystemTick();
    row->kind = kind; row->detail = detail;
    row->command = __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE);
    row->applied = __atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE);
    row->vblank = C3D_FrameCounter(0);
    row->frame = lat.runner != NULL ? (uint32_t) lat.runner->frameCount : 0;
    // Only game/DSP-thread events sample channels. Swap callbacks just stamp
    // their event; no extra channel walk is introduced on the GSP thread.
    if (kind <= 6 || kind == 9) for (unsigned p = 0; p < 24; p++) {
        int id = *CtrLoadmix_legacy.mapped ? CtrLoadmix_legacy.inverse[p] : (int) p;
        row->voice[p] = id >= 0 && id < VOICE_COUNT
            ? __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE) : 0;
        uint32_t seq = UTA_PHYS_SEQ(p);
        row->position[p] = UTA_PHYS_POS(p);
        bool same = seq == UTA_PHYS_SEQ(p) &&
            id == (*CtrLoadmix_legacy.mapped ? CtrLoadmix_legacy.inverse[p] : (int) p);
        if (id >= 0 && id < VOICE_COUNT)
            same = same && row->voice[p] == __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE);
        row->sequence[p] = same ? seq : 0;
    }
    __atomic_store_n(&row->ready, true, __ATOMIC_RELEASE);
}

// DSP thread only: two updates after each request generation/release. These
// raw cursor snapshots are observations, not an assumed DSP acknowledgment.
LM_CODE static void lmdCallback(void) {
    uint32_t command = __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE);
    bool held = __atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE) != 0;
    if ((command & ~3u) != lmd.generation || held != lmd.held) {
        lmd.generation = command & ~3u; lmd.held = held; lmd.remaining = 2;
    } else if (lmd.remaining && --lmd.remaining == 0) {
        lmdEvent(held ? 4 : 6, (uint32_t) lmdEnabled);
    }
}

LM_CODE static void lmdDrain(void) {
    if (lat.runner == NULL) return;
    uint32_t frame = (uint32_t) lat.runner->frameCount;
    uint32_t count = __atomic_load_n(&lmd.count, __ATOMIC_ACQUIRE);
    if (count > 256) count = 256;
    for (uint32_t i = 0; i < count; i++) {
        LmdEvent* row = &lmd.events[i];
        if (!__atomic_load_n(&row->ready, __ATOMIC_ACQUIRE) || row->printed ||
            frame < row->frame || frame - row->frame < 60) continue;
        row->printed = true;
        logQuiet(lmdHeader, (unsigned long) i, (unsigned long) row->kind,
                 (unsigned long) row->command, (unsigned long) row->applied,
                 (unsigned long long) row->tick, (unsigned long) row->vblank,
                 (unsigned long) row->detail, (unsigned long) row->frame);
        if (row->kind <= 6 || row->kind == 9) for (unsigned p = 0; p < 24; p++)
            if (row->voice[p] || row->sequence[p])
                logQuiet(lmdHeader, (unsigned long) i, 10ul, (unsigned long) p,
                         (unsigned long) row->voice[p], (unsigned long long) row->sequence[p],
                         (unsigned long) row->position[p], 0ul, 0ul);
    }
    if (__atomic_load_n(&lmd.overflow, __ATOMIC_ACQUIRE) && !lmd.overflowPrinted) {
        lmd.overflowPrinted = true;
        logQuiet(lmdHeader, 0ul, 11ul, 0ul, 0ul, 0ull, 0ul, 0ul, 0ul);
    }
}
#define LMD_EVENT(kind, detail) lmdEvent(kind, detail)
#else
#define LMD_EVENT(kind, detail) ((void) 0)
#endif

#include "ctr_audio_transport_mix.inc"

LM_CODE static bool lmHeld(void) {
#ifdef CTR_AUDIO_PCM_HASH
    if (!lmdEnabled) return false;
#endif
    return __atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE);
}

LM_CODE static void lmPaused(int p, bool paused) {
    bool held = lmHeld();
    UTA_PHYS_PAUSED(p, paused || held);
    // Publish AFTER the physical write, even if the sampled hold was false.
    // Entry/release may have consumed the preceding repair before this write.
    __atomic_store_n(&lm.dirty, 1, __ATOMIC_RELEASE);
}

LM_CODE static void lmReset(void) {
    __atomic_store_n(&lm.command, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&lm.applied, 0, __ATOMIC_RELEASE);
    __atomic_store_n(&lm.dirty, 0, __ATOMIC_RELEASE);
    lm.runner = NULL;
    lm.goal = lm.start = lm.frame = lm.lastTick = lm.heldTicks = 0;
    lm.watchCommand = lm.emptyTick = lm.unusedTicks = lm.creditTicks = 0;
    lm.waiting = 0;
    __atomic_store_n(&lm.rampHeld, false, __ATOMIC_RELEASE);
}

#ifndef LM_HOST
LM_CODE static void lmRegister(ndspCallback callback, void* data) {
    lmReset();
    UTA_PHYS_CALLBACK(callback != NULL ? lmCallback : NULL, data);
}
#endif

// Is there a source queued for this mix? 1 empty, 0 ready, -1 busy/unknown.
// A cached voice or feeder tail conservatively counts as ready. Stream
// status is read under its existing producer lock, never by waiting on it.
// Called only until the first ready observation of an open load window.
LM_CODE static int lmEmpty(CtrAudioSystem* ca) {
    if (LightLock_TryLock(CtrLoadmix_legacy.lock) != 0) return -1;
    bool ready = false;
    for (unsigned p = 0; p < VOICE_COUNT; p++)
        if (CtrLoadmix_legacy.channels[p].state != UTA_IDLE || ca->voices[p].kind == VOICE_SFX) ready = true;
    LightLock_Unlock(CtrLoadmix_legacy.lock);
    if (ready) return 0;
    for (unsigned i = 0; i < STREAM_CONTEXTS; i++) {
        StreamContext* s = &ca->streams[i];
        if (LightLock_TryLock(&s->lock) != 0) return -1;
        for (unsigned b = 0; b < STREAM_BUFFERS; b++) {
            unsigned status = s->bufs[b].wb.status;
            if (status == NDSP_WBUF_QUEUED || status == NDSP_WBUF_PLAYING) ready = true;
        }
        LightLock_Unlock(&s->lock);
        if (ready) return 0;
    }
    return 1;
}

LM_CODE static void lmCallback(void* data) {
    CtrAudioSystem* ca = (CtrAudioSystem*) data;
    uint32_t now = (uint32_t) svcGetSystemTick();
    if (__atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE))
        lm.heldTicks += now - lm.lastTick;
    lm.lastTick = now;
    uint32_t command = __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE);
    uint32_t goal = __atomic_load_n(&lm.goal, __ATOMIC_RELAXED);
    uint32_t start = __atomic_load_n(&lm.start, __ATOMIC_RELAXED);
    // A publishing game thread never makes the DSP callback wait or spin.
    if ((command & 2u) || command != __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE)) {
        (*CtrLoadmix_legacy.engine)(data);
        return;
    }
    if (command != lm.watchCommand) {
        lm.watchCommand = command;
        lm.waiting = command & 1u ? 1 : 0;
        lm.unusedTicks = 0;
    }
    if (lm.waiting) {
        int empty = lmEmpty(ca);
        if (command != __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE)) {
            (*CtrLoadmix_legacy.engine)(data);
            return;
        }
        if (empty > 0) {
            if (lm.waiting == 2) {
                uint32_t elapsed = lm.unusedTicks + now - lm.emptyTick;
                lm.unusedTicks = elapsed < LM_FRAME_TICKS ? elapsed : LM_FRAME_TICKS;
            }
            lm.emptyTick = now;
            lm.waiting = 2;
        } else if (empty == 0) {
            // Restore only the observed unused allowance, at most one frame,
            // once a source exists in this SAME window. An entirely empty load
            // earns no credit for a later song. Never seek or skip samples.
            lm.creditTicks += lm.unusedTicks;
            lm.waiting = 0;
        } else if (lm.waiting == 2) lm.waiting = 3;
    }
    if (command & 1u) goal += now - start - LM_FRAME_TICKS;
    bool dirty = __atomic_exchange_n(&lm.dirty, 0, __ATOMIC_ACQ_REL);
    bool wanted = (int32_t) (goal - lm.heldTicks - lm.creditTicks) > 0;
#ifdef CTR_AUDIO_PCM_HASH
    wanted = wanted && lmdEnabled;
    lmdCallback();
#endif
    if (dirty || wanted != __atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE)) {
        if (LightLock_TryLock(CtrLoadmix_legacy.lock) != 0) {
            __atomic_store_n(&lm.dirty, 1, __ATOMIC_RELEASE);
            (*CtrLoadmix_legacy.engine)(data);
            return;
        }
#ifdef CTR_AUDIO_PCM_HASH
        // Post-write repairs are now unconditional. Record real transport
        // transitions only, rather than filling the finite diagnostic ring
        // with repeated same-state repairs during ordinary play.
        if (wanted != __atomic_load_n(&lm.applied, __ATOMIC_ACQUIRE))
            LMD_EVENT(wanted ? 3 : 5, 0);
#endif
        CtrAudio_transportMixLocked(ca, wanted, -1);
        __atomic_store_n(&lm.applied, wanted, __ATOMIC_RELEASE);
        LightLock_Unlock(CtrLoadmix_legacy.lock);
    }
    // Freeze utaCb too: it is the tail deadline, not just a service counter.
    // Keep the engine notification so the decoder can prepare unplayed PCM.
    if (lmHeld()) (*CtrLoadmix_legacy.engine)(data);
    else CtrLoadmix_legacy.callback(data);
}

// Decoder preparation continues during a load, while positioned-mix ramps
// earn no wall-clock progress from it. The original inlined ramp body stays.
LM_CODE static int lmDecodeWait(LightEvent* event, s64 timeout) {
    int result = (LightEvent_WaitTimeout)(event, timeout);
    bool held = lmHeld();
    CtrAudioSystem* ca = *CtrLoadmix_legacy.target;
    if (ca != NULL && (held || __atomic_load_n(&lm.rampHeld, __ATOMIC_ACQUIRE))) {
        LightLock_Lock(&ca->rampLock);
        ca->rampTick = svcGetSystemTick();
        LightLock_Unlock(&ca->rampLock);
    }
    __atomic_store_n(&lm.rampHeld, held, __ATOMIC_RELEASE);
    return result;
}

LM_CODE void CtrLoadmix_boundary(Runner* runner, bool loaded) {
    if (!loaded) {
        uint32_t command = __atomic_load_n(&lm.command, __ATOMIC_ACQUIRE);
        uint32_t frame = (uint32_t) runner->frameCount;
        bool close = (command & 1u) && (runner != lm.runner || frame != lm.frame);
        bool open = runner->pendingRoom >= 0 && (!(command & 1u) || close);
        if (close || open) {
            uint32_t next = (command + 4u) & ~3u;
            __atomic_store_n(&lm.command, next | 2u, __ATOMIC_SEQ_CST);
            uint32_t now = (uint32_t) svcGetSystemTick();
            if (close) {
                uint32_t frames = frame - lm.frame;
                if (runner != lm.runner || (int32_t) frames <= 0) frames = 1u;
                uint32_t goal = __atomic_load_n(&lm.goal, __ATOMIC_RELAXED);
                goal += now - __atomic_load_n(&lm.start, __ATOMIC_RELAXED) - frames * LM_FRAME_TICKS;
                __atomic_store_n(&lm.goal, goal, __ATOMIC_RELAXED);
            }
            lm.runner = runner;
            lm.frame = frame;
            __atomic_store_n(&lm.start, now, __ATOMIC_RELAXED);
            __atomic_store_n(&lm.command, next | (open ? 1u : 0u), __ATOMIC_RELEASE);
        }
    }
#ifdef CTR_AUDIO_PCM_HASH
    CtrLoadaudio_boundary(runner, loaded);
    if (loaded || runner->pendingRoom >= 0) LMD_EVENT(loaded ? 2 : 1, lat.loadCount);
#else
    (void) loaded;
#endif
}

#ifndef LM_HOST
// Keep the freebies wrapper's original single-call extent and function order.
// The audio object is excluded from earlier generic late-section collectors.
void __real_Runner_handlePendingRoomChange(Runner* runner);
LM_CODE void CtrLoadmix_handleRoomChange(Runner* runner) {
    int32_t pending = runner->pendingRoom;
    CtrLoadmix_boundary(runner, false);
    __real_Runner_handlePendingRoomChange(runner);
    if (pending != -1) CtrLoadmix_boundary(runner, true);
}
#endif

LM_CODE void CtrLoadmix_chainEndFrame(Renderer* renderer) {
    CTR_ENDFRAME_AFTER_LOADMIX(renderer);
#ifdef CTR_AUDIO_PCM_HASH
    lmdDrain();
#endif
}
