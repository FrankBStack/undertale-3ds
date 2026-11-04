// Included at ctr_gpu_queue.c's end: original functions/data keep their slots.
// This is deliberately separate from frameBusy, pendingQueue and completions.
// A prefix callback only consumes entries; only a whole-frame finish retires.
#include "ctr_gpu_kick.h"
#define KICK_TEXT __attribute__((noinline, section(".text.cheaplevers_kick_late")))
#define KICK_BSS __attribute__((section(".bss.cheaplevers_kick_late")))
#define KICK_RO __attribute__((section(".rodata.cheaplevers_kick_late")))
#define KICK_MIN_BYTES (32u * 1024u)
#define KICK_RING_RESERVE_WORDS 8192u
#define KICK_MS_TICKS ((uint64_t) SYSCLOCK_ARM11 / 1000u)
#ifdef CTR_KICK_MULTI
// Multi (change pacer): a later existing split submits what was recorded since
// the last prefix, once that prefix is off the GPU, so the GPU keeps pace with
// recording instead of starting the whole remainder at frame end. Guard (rev3,
// 2026-11-02): the gate below. CTR_KICK_FORCE (identity diagnostic only)
// kicks always.
#define KICK_MS ((uint64_t) SYSCLOCK_ARM11 / 1000u)
#endif
// Rev3 gate (lead 2026-11-02). The kick helps one shape only: the GPU gets a
// frame's commands at C3D_FrameEnd, so the frame is done main + GPU into its
// slot, and when that sum passes the slot while each part fits it, every
// frame's flip is late (Knight kfinal's echo: main 16-18 + GPU 19-24 ms, done
// 36-40 ms into a 33.4 ms slot, every other frame held). The gate opens after
// KICK_GATE_FRAMES such frames in a row and shuts at the first other one. A
// frame's main here is its recording less the time it joined a prefix, so the
// shape is the same whether the frame kicked or not. A frame near the CPU line
// (main over KICK_GATE_MAIN_MS) never qualifies: a prefix join there could make
// the CPU late (KM rev2: flowerbg +3.6 ms). Isolated late frames (KM rev2's
// flowersun f861 and f1209) never open it.
// Rev 4 (lead 2026-11-02): no per-frame log lines. Each line cost frame time
// through the bottom-screen log console (n3ds, pacer-ktr-r1: ~1-2 ms CPU and
// ~3 ms GPU per 230-character line; with the gate shut rev3 was slower than the
// build without the kick only by its trace). Counts only.
// Rev 4.1 (lead 2026-11-02): no KM line in play at all. Rev 4's totals every 300
// frames made one flowersun frame late at frame 1199 and an 18-frame echo
// followed (pacer-km4-r1, also in a row with no kick). The totals are bench-only
// output now: printed once as a test run ends (CtrBench_takeFinished).
#define KICK_GATE_FRAMES 3u
#define KICK_GATE_SLOT_MS 34u
#define KICK_GATE_MAIN_MS 22u
#define KICK_GATE_GPU_MS 33u

// Separate declarations keep GCC from specializing/inlining the original
// bodies into these helpers. The assembly launcher supplies their frozen
// definitions from the ordinary pass in this same object.
void __real_C3D_FrameSplit(u8 flags);
void __real_C3D_FrameEnd(u8 flags);
bool __real_CtrGpu_frameEndBehind(void);
void __real_CtrGpu_waitIdle(void);
void __real_CtrGpu_waitDraws(void);
bool __real_CtrGpu_busy(void);
uint32_t kickOriginalDue(void) __asm__("CtrGpu_completionDue");
void __real_CtrGpu_wrapCommandBuffer(void);
bool __real_CtrGpu_cancelCopy(CtrGpuQueued queued, const void* from, const void* to);
void kickOriginalFinish(gxCmdQueue_s* queue) __asm__("finishFrame");
void kickOriginalCallback(gxCmdQueue_s* queue) __asm__("onQueueFinish");
#ifdef CTRPORT_RING_FINISH_CHECK
void kickOriginalRingCallback(gxCmdQueue_s* queue) __asm__("ringFinishCheck");
#endif

static struct {
    gxCmdQueue_s view;
    gxCmdEntry_s entries[CTR_GPU_QUEUE_ENTRIES];
    gxCmdQueue_s* recording;
    gxCmdQueue_s* finalQueue;
    void (*drain)(void*);
    void* context;
    u32 owner, due, submittedEnd;
    volatile bool open, pending, active;
    bool draining;
    uint64_t started, prefixTicks, finalTicks;
    u32 kicks, deferred, fullSkips, bytes, pressure, partialFinishes;
    u32 frames, logged; // frames retained as an unused footprint placeholder
#ifdef CTR_KICK_MULTI
    u32 frameBytes; // multi: frames counts kicked recordings; this, bytes left for frame end
#endif
#ifdef CTR_KICK_TINY_RING_WORDS
    u32 diagnosticWraps, diagnosticExtensions;
#endif
    // Rev2 (lead 2026-11-01): a frame that loads or sync-copies textures, or
    // follows one that loaded, records whole. On the New 3DS in ch5_flowersun
    // the multi kick's runs read the SD card 2-7% slower and reordered the
    // room's first loads, so a later frame reopened a cache file (+41 ms).
    bool (*textureBusy)(void*);
    bool loadedBefore;
    u32 frame, textureSkips;
    // Per-frame counts (no per-frame log line since rev 4) and their running totals.
    uint64_t frameBegin, siteTicks[5], totalSiteTicks[5];
    u32 frameKicks, frameKB, frameTextureSkips, frameSyncCopies, frameFenceHits, frameFenceSleeps;
    u32 kickHistogram[4], traceFrames, tracedSlow, kickedSlow;
    uint64_t kickedSlowJoinTicks;
    // Rev3 gate: frames in a row of the shape, open now, frames open, turns,
    // and kicked frames whose recording plus end join passed 34 ms of CPU while
    // the recording less its prefix joins fit: a lower bound for frames the joins
    // made late (blind to 33.4-34 ms, to the wait booked apart from the prefix
    // joins, and to every GPU-side delay; R111 F1).
    u32 streak, gateFrames, gateTurns, cpuPastByJoins;
    bool gateOn;
} kick KICK_BSS;

// kickWaitPrefix's callers, for the trace.
enum { KICK_SITE_END, KICK_SITE_IDLE, KICK_SITE_DRAWS, KICK_SITE_WRAP, KICK_SITE_PRESSURE };

static void kickPrefixFinished(gxCmdQueue_s* view);

// gateLock held. The entry snapshot was flushed on the recording thread.
KICK_TEXT static void kickStartLocked(void) {
    if (!kick.pending || frameBusy || kick.active) return;
    kick.pending = false;
    kick.active = true;
    kick.started = svcGetSystemTick();
    kick.kicks++;
    gxCmdQueueRun(&kick.view);
}

KICK_TEXT static void kickPrefixFinished(gxCmdQueue_s* view) {
    LightLock_Lock(&gateLock);
    if (view == &kick.view && kick.active) {
        kick.prefixTicks += svcGetSystemTick() - kick.started;
        kick.recording->curEntry = kick.recording->lastEntry = kick.submittedEnd;
        kick.partialFinishes++;
        kick.active = false;
        // No finishFrame, completion count, flip, screen transfer or ring reuse.
    }
    LightLock_Unlock(&gateLock);
}

// The original callback still owns full-frame statistics, transfers and flips.
// A deferred prefix starts only after all previously submitted frames finish.
KICK_TEXT static void kickWholeFinished(gxCmdQueue_s* queue) {
    LightLock_Lock(&gateLock);
    if (kick.finalQueue == queue) {
        frameGpuTicks += kick.finalTicks;
        kick.finalTicks = 0;
        kick.finalQueue = nullptr;
    }
    LightLock_Unlock(&gateLock);
#ifdef CTRPORT_RING_FINISH_CHECK
    kickOriginalRingCallback(queue);
#else
    kickOriginalCallback(queue);
#endif
    LightLock_Lock(&gateLock);
    kickStartLocked();
    LightLock_Unlock(&gateLock);
}

KICK_TEXT static bool kickCallbacks(void) {
    LightLock_Lock(&gateLock);
    // Both measurements already exist. Start() leaves elapsed intact until
    // End() updates it: elapsed describes the preceding CPU recording, not
    // this frame's partial CPU time. Read the asynchronous GPU total while
    // holding its writer's lock. This is a global history guard, not a
    // guarantee about the next frame, and requires console qualification.
#if defined(CTR_KICK_FORCE)
    bool gpuBound = true;
#elif defined(CTR_KICK_MULTI)
    bool gpuBound = kick.gateOn;
#else
    bool gpuBound = lastGpuTicks >= (uint64_t) SYSCLOCK_ARM11 / 50 &&
                    lastGpuTicks > cpuTime.elapsed;
#endif
    for (int i = 0; gpuBound && i < 3; i++) {
        if (queues[i] != nullptr && (queues[i]->callback == onQueueFinish
#ifdef CTRPORT_RING_FINISH_CHECK
                                    || queues[i]->callback == ringFinishCheck
#endif
                                    )) queues[i]->callback = kickWholeFinished;
    }
    LightLock_Unlock(&gateLock);
    return gpuBound;
}

// A physical drain. It never waits for the recording frame to be ended.
KICK_TEXT static void kickWaitPrefix(int site) {
    uint64_t start = svcGetSystemTick();
    uint64_t accounted = waitTotalTicks;
    for (;;) {
        LightLock_Lock(&gateLock);
        kickStartLocked();
        bool waiting = kick.pending || kick.active;
        LightLock_Unlock(&gateLock);
        if (!waiting) break;
        if (frameBusy) __real_CtrGpu_waitIdle();
        else svcSleepThread(100 * 1000);
    }
    uint64_t ticks = svcGetSystemTick() - start;
    uint64_t oldWait = waitTotalTicks - accounted;
    ticks = ticks > oldWait ? ticks - oldWait : 0;
    waitTicks += ticks;
    waitTotalTicks += ticks;
    kick.siteTicks[site] += ticks;
}

KICK_TEXT bool CtrKick_retirementBusy(void) {
    // open is published before a prefix can run, and cleared only after the
    // whole recording is submitted. The allocator must not use physical idle.
    bool open = __atomic_load_n(&kick.open, __ATOMIC_ACQUIRE);
    bool busy = __real_CtrGpu_busy();
    if (open && !busy) kick.frameFenceHits++; // the fence alone (any thread; a diagnostic count)
    return open || busy;
}

KICK_TEXT uint32_t CtrKick_retirementDue(void) {
    if (__atomic_load_n(&kick.open, __ATOMIC_ACQUIRE)) return kick.due;
    return kickOriginalDue();
}

KICK_TEXT void CtrKick_setDrain(void (*drain)(void*), void* context) {
    kick.drain = drain;
    kick.context = context;
    svcGetThreadId(&kick.owner, CUR_THREAD_HANDLE);
#ifdef CTR_KICK_TINY_RING_WORDS
    // The allocation is unchanged; only its usable ring is deliberately tiny.
    // Never used by a release or timing binary.
    if (CITRO_CONTEXT->cmdBufSize > CTR_KICK_TINY_RING_WORDS)
        CITRO_CONTEXT->cmdBufSize = CTR_KICK_TINY_RING_WORDS;
#endif
}

KICK_TEXT void CtrKick_pressureWait(s64 nanos) {
    u32 caller = 0;
    svcGetThreadId(&caller, CUR_THREAD_HANDLE);
    if (caller == kick.owner && kick.open && !kick.draining) {
        kick.draining = true;
        kick.pressure++;
        kickWaitPrefix(KICK_SITE_PRESSURE);
        __real_CtrGpu_waitIdle();
        // The allocator released its linear lock before reaching this call.
        // End/run/resume is synchronous and leaves the pending batch intact.
        kick.drain(kick.context);
        kick.draining = false;
    } else if (kick.open) {
        kick.frameFenceSleeps++; // another thread sleeps on this recording's fence
    }
    svcSleepThread(nanos);
}

KICK_TEXT void CtrKick_setTextureProbe(bool (*textureBusy)(void*)) {
    kick.textureBusy = textureBusy;
}

// No prefix while a tile load, fill, whole-page read or sync copy is already
// known when the split comes, nor in the frame after a measured tile load.
// Engine-wide, no scene list. Not covered (R111 F2): a load asked for later in
// the same frame, after a prefix has gone.
KICK_TEXT static bool kickTextureFrame(void) {
    return kick.loadedBefore || kick.frameSyncCopies != 0 ||
           (kick.textureBusy != nullptr && kick.context != nullptr && kick.textureBusy(kick.context));
}

void __real_C3D_SyncTextureCopy(u32* inadr, u32 indim, u32* outadr, u32 outdim, u32 size, u32 flags);
KICK_TEXT void __wrap_C3D_SyncTextureCopy(u32* inadr, u32 indim, u32* outadr, u32 outdim, u32 size, u32 flags) {
    kick.frameSyncCopies++;
    __real_C3D_SyncTextureCopy(inadr, indim, outadr, outdim, size, flags);
}

// Ends the frame before (trace) and starts the next one's counts. Called from
// the renderer's begin, before its own begin runs.
KICK_TEXT void CtrKick_frameBegin(bool loadedBefore) {
    uint64_t now = svcGetSystemTick();
    if (kick.frameBegin != 0) {
        uint64_t span = now - kick.frameBegin;
        uint64_t waited = 0;
        for (int i = 0; i < 5; i++) {
            waited += kick.siteTicks[i];
            kick.totalSiteTicks[i] += kick.siteTicks[i];
        }
        kick.kickHistogram[kick.frameKicks < 3u ? kick.frameKicks : 3u]++;
        kick.traceFrames++;
#if defined(CTR_KICK_MULTI) && !defined(CTR_KICK_FORCE)
        // Rev3 gate, from the frame that just ended: its recording (C3D_FrameBegin
        // to C3D_FrameEnd's tick update) less the prefix joins inside it, and the
        // GPU's last whole frame. The frame-end join comes after that update.
        uint64_t inside = waited - kick.siteTicks[KICK_SITE_END];
        uint64_t cpu = cpuTime.elapsed > inside ? cpuTime.elapsed - inside : 0;
        // The GPU total under its writer's lock (R111 F3).
        LightLock_Lock(&gateLock);
        uint64_t gpu = lastGpuTicks;
        LightLock_Unlock(&gateLock);
        // A kicked frame whose prefix joins took its CPU past the slot (without them it fit).
        if (kick.frameKicks != 0 && cpuTime.elapsed + kick.siteTicks[KICK_SITE_END] > KICK_GATE_SLOT_MS * KICK_MS_TICKS &&
            cpu <= KICK_GATE_SLOT_MS * KICK_MS_TICKS) kick.cpuPastByJoins++;
        bool shape = cpu + gpu >= KICK_GATE_SLOT_MS * KICK_MS_TICKS && cpu <= KICK_GATE_MAIN_MS * KICK_MS_TICKS &&
                     gpu <= KICK_GATE_GPU_MS * KICK_MS_TICKS;
        kick.streak = shape ? kick.streak + 1u : 0u;
        bool open = kick.streak >= KICK_GATE_FRAMES;
        if (open != kick.gateOn) kick.gateTurns++;
        kick.gateOn = open;
        if (open) kick.gateFrames++;
#endif
        // Slow frames (over a 30 fps slot) and frames that joined a prefix for 2 ms or more: counted only.
        if (span > 34u * KICK_MS_TICKS || waited >= 2u * KICK_MS_TICKS) kick.tracedSlow++;
        if (kick.frameKicks != 0 && span > 34u * KICK_MS_TICKS) {
            kick.kickedSlow++;
            kick.kickedSlowJoinTicks += waited;
        }
    }
    kick.frameBegin = now;
    kick.loadedBefore = loadedBefore;
    kick.frameKicks = kick.frameKB = kick.frameTextureSkips = kick.frameSyncCopies = 0;
    kick.frameFenceHits = kick.frameFenceSleeps = 0;
    for (int i = 0; i < 5; i++) kick.siteTicks[i] = 0;
}

KICK_TEXT void CtrKick_setFrame(uint32_t frame) {
    kick.frame = frame;
}

// Generic opportunity: an existing renderer split has just closed a list.
// Skip near either ring's limit so the original full-drain fallback has room.
KICK_TEXT void __wrap_C3D_FrameSplit(u8 flags) {
    __real_C3D_FrameSplit(flags);
    // Keep at most one prefix open per physical recording, even after its
    // callback completes. Avoid another full-heap flush/submission in Draw.
#ifdef CTR_KICK_MULTI
    // One prefix in flight; the next split after it finishes takes the rest.
    if (!inFrame || kick.drain == nullptr || kick.draining || kick.pending || kick.active) return;
#else
    if (!inFrame || kick.drain == nullptr || kick.draining || kick.open) return;
#endif
    gxCmdQueue_s* queue = boundQueue();
    if (queue->numEntries + 8u >= queue->maxEntries ||
        gpuCmdBufOffset + KICK_RING_RESERVE_WORDS >= gpuCmdBufSize) {
        kick.fullSkips++;
        return;
    }
    u32 bytes = 0;
    for (u32 i = queue->curEntry; i < queue->numEntries; i++) {
        const u32* cmd = queue->entries[i].data;
        if ((cmd[0] & 0xFF) == 1) bytes += cmd[2]; // GX_ProcessCommandList, bytes
    }
    // An empty entry range leaves bytes at zero, below KICK_MIN_BYTES.
    if (bytes < KICK_MIN_BYTES) return;
#ifdef CTR_KICK_MULTI
    // The guard decides once per recording; later prefixes follow the first.
    if (!kick.open && !kickCallbacks()) return;
#else
    if (!kickCallbacks()) return;
#endif
    if (kickTextureFrame()) {
        kick.textureSkips++;
        kick.frameTextureSkips++;
        return;
    }
    extern u32 __ctru_linear_heap, __ctru_linear_heap_size;
    // Exactly frame end's full-heap flush, including vertices and command lists.
    // Later entries go into the recording queue, never this frozen view.
    GSPGPU_FlushDataCache((void*) __ctru_linear_heap, __ctru_linear_heap_size);
    LightLock_Lock(&gateLock);
    u32 first = queue->curEntry, count = queue->numEntries - first;
    memcpy(kick.entries, queue->entries + first, count * sizeof(gxCmdEntry_s));
    kick.view.entries = kick.entries;
    kick.view.maxEntries = CTR_GPU_QUEUE_ENTRIES;
    kick.view.numEntries = count;
    kick.view.curEntry = kick.view.lastEntry = 0;
    kick.view.callback = kickPrefixFinished;
    kick.view.user = nullptr;
    kick.recording = queue;
    kick.submittedEnd = queue->numEntries;
#ifdef CTR_KICK_MULTI
    if (!kick.open) {
        kick.frames++;
        kick.due = completions + (frameBusy ? (pendingQueue != nullptr ? 2u : 1u) : 0u) + 1u;
    }
#else
    kick.due = completions + (frameBusy ? (pendingQueue != nullptr ? 2u : 1u) : 0u) + 1u;
#endif
    __atomic_store_n(&kick.open, true, __ATOMIC_RELEASE);
    queueRuns++; // invalidates pre-snapshot copy-cancellation handles
    kick.bytes += bytes;
    kick.frameKicks++;
    kick.frameKB += bytes / 1024u;
    kick.pending = true;
    if (frameBusy) kick.deferred++;
    kickStartLocked();
    LightLock_Unlock(&gateLock);
#ifdef CTR_KICK_SERIAL_PREFIX
    // Diagnostic isolation only: preserve prefix boundaries and whole-frame
    // retirement, but remove CPU recording overlap with the submitted prefix.
    kickWaitPrefix(KICK_SITE_IDLE);
#endif
#ifdef CTR_KICK_FORCE_PRESSURE
    // Stress the dangerous physically-idle, not-yet-retired state. A prefix
    // completion alone must not release a free or satisfy its frame fence.
    kickWaitPrefix(KICK_SITE_IDLE);
    __real_CtrGpu_waitIdle();
    if (!kick.open || (int32_t) (completions - kick.due) >= 0) svcBreak(USERBREAK_PANIC);
    CtrMemory_kickPressureTest();
#endif
}

// Wrappers cover external physical waits. The ordinary frame end's inlined
// wait is protected by CtrKick_endFlush, after closing/flushing CPU commands.
KICK_TEXT void __wrap_CtrGpu_waitIdle(void) {
    kickWaitPrefix(KICK_SITE_IDLE);
    __real_CtrGpu_waitIdle();
}

KICK_TEXT void __wrap_CtrGpu_waitDraws(void) {
    kickWaitPrefix(KICK_SITE_DRAWS);
    __real_CtrGpu_waitDraws();
}

KICK_TEXT bool __wrap_CtrGpu_busy(void) {
    return __real_CtrGpu_busy() || __atomic_load_n(&kick.active, __ATOMIC_ACQUIRE) ||
           __atomic_load_n(&kick.pending, __ATOMIC_ACQUIRE);
}

KICK_TEXT void __wrap_CtrGpu_wrapCommandBuffer(void) {
    kickWaitPrefix(KICK_SITE_WRAP);
    // canWrap's ring-reuse hook can make room by extending the current span.
    // asgRoomSlow then splits and calls wrap without rechecking that room,
    // unlike makeCommandRoom. A split has already closed the list: retain the
    // extended span instead of resetting it when no physical wrap was granted.
    // Do not turn a prefix finish into a whole-frame completion or ring reuse.
    if (inFrame && ringReuse.valid && ringReuse.reused && ringReuse.extended &&
        frameStart == 0 && !mayWrap && gpuCmdBufOffset == 0 && gpuCmdBuf != nullptr) {
        CitroContextHead* ctx = CITRO_CONTEXT;
        u32 base = (u32) gpuCmdBuf, start = (u32) ctx->cmdBuf;
        u32 words = (base - start) / sizeof(u32);
        if (base >= start && (base - start) % sizeof(u32) == 0 &&
            words <= ctx->cmdBufSize && gpuCmdBufSize <= ctx->cmdBufSize - words) {
#ifdef CTR_KICK_TINY_RING_WORDS
            kick.diagnosticExtensions++;
#endif
            return;
        }
    }
    // Unrecognized states still reach the original wrap assertion.
    __real_CtrGpu_wrapCommandBuffer();
#ifdef CTR_KICK_TINY_RING_WORDS
    kick.diagnosticWraps++;
#endif
}

KICK_TEXT bool __wrap_CtrGpu_cancelCopy(CtrGpuQueued queued, const void* from, const void* to) {
    if (queued.queue == kick.recording && queued.index < kick.submittedEnd && kick.open) return false;
    return __real_CtrGpu_cancelCopy(queued, from, to);
}

// Exactly one original ARM call in EACH frame-end path targets this helper.
// Their split and wait can be inlined, so --wrap cannot intercept them.
// Finish CPU recording and its flush BEFORE draining the prefix, then prepare
// its accounting before either original suffix submission can run. Both
// original flush callers discard Result; this replacement has no return value.
// Retain the whole-frame retirement fence until the end wrapper returns.
KICK_TEXT void CtrKick_endFlush(const void* address, u32 size) {
    GSPGPU_FlushDataCache(address, size);
    if (!kick.open) return;
    kickWaitPrefix(KICK_SITE_END);
    LightLock_Lock(&gateLock);
    kick.finalQueue = kick.recording;
    kick.finalTicks = kick.prefixTicks;
    kick.prefixTicks = 0;
#ifdef CTR_KICK_MULTI
    for (u32 i = kick.recording->curEntry; i < kick.recording->numEntries; i++) {
        const u32* cmd = kick.recording->entries[i].data;
        if ((cmd[0] & 0xFF) == 1) kick.frameBytes += cmd[2];
    }
#endif
    LightLock_Unlock(&gateLock);
}

KICK_TEXT static void kickEndComplete(void) {
    LightLock_Lock(&gateLock);
    gxCmdQueue_s* queue = kick.recording;
    // All work may have been consumed by prefixes. libctru emits no callback
    // for an empty suffix; retire it here, only after the whole end was called.
    if (!frameBusy && pendingQueue == nullptr && (int32_t) (completions - kick.due) < 0 &&
        queue->lastEntry == queue->numEntries) {
        frameGpuTicks += kick.finalTicks;
        kick.finalTicks = 0;
        kick.finalQueue = nullptr;
        kickOriginalFinish(queue);
    }
    __atomic_store_n(&kick.open, false, __ATOMIC_RELEASE);
    kick.recording = nullptr;
    kick.submittedEnd = 0;
    LightLock_Unlock(&gateLock);
}

KICK_TEXT void __wrap_C3D_FrameEnd(u8 flags) {
    // Always take the full-heap flush and its scoped end-join hook, including
    // callers that ordinarily request per-list flushing instead. No new frame
    // is buffered and no prefix can cross the original suffix submission.
    __real_C3D_FrameEnd(flags & ~GX_CMDLIST_FLUSH);
    if (kick.open) kickEndComplete();
}

KICK_TEXT bool __wrap_CtrGpu_frameEndBehind(void) {
    // A declined behind-frame attempt has not closed anything: let recording
    // continue without joining the prefix. Successful closure reaches the
    // same scoped heap-flush join as ordinary frame end.
    bool ended = __real_CtrGpu_frameEndBehind();
    if (ended && kick.open) kickEndComplete();
    return ended;
}

#ifdef CTR_KICK_BENCH_TOTALS
static const char kickLog[] KICK_RO =
    "GPU kick: %lu runs, %lu deferred, %lu full skips, %lu KB, %lu partial finishes, %lu pressure drains\n";
#if defined(CTR_KICK_MULTI) && defined(CTR_KICK_FORCE)
static const char kickMultiLog[] KICK_RO = "GPU kick multi: %lu frames, %lu KB left for frame end\n";
#endif
static const char kickTraceLog[] KICK_RO =
    "GPU kick trace: %lu frames (%lu with no kick, %lu with 1, %lu with 2, %lu with 3+; %lu over 34 ms or joining 2+ ms), "
    "%lu splits kept for textures; prefix joins: end %lu, idle %lu, draws %lu, wrap %lu, pressure %lu ms; "
    "%lu kicked frames over 34 ms (joins %lu ms)\n";
#if defined(CTR_KICK_MULTI) && !defined(CTR_KICK_FORCE)
static const char kickGateTotals[] KICK_RO =
    "GPU kick multi: %lu frames, %lu KB left for frame end; gate open %lu frames, %lu turns; "
    "%lu kicked frames past 34 ms of CPU only with their joins (a lower bound)\n";
#endif
#ifdef CTR_KICK_TINY_RING_WORDS
static const char kickTinyLog[] KICK_RO =
    "GPU kick diagnostic: %lu ring words, %lu completed wraps\n";
static const char kickExtensionLog[] KICK_RO =
    "GPU kick diagnostic: %lu extended spans kept without wrapping\n";
#endif
KICK_TEXT static void kickLogTotals(void) {
    // The run's cumulative counters, once, after its last measured frame.
    logInfo(kickTraceLog, (unsigned long) kick.traceFrames, (unsigned long) kick.kickHistogram[0],
            (unsigned long) kick.kickHistogram[1], (unsigned long) kick.kickHistogram[2],
            (unsigned long) kick.kickHistogram[3], (unsigned long) kick.tracedSlow, (unsigned long) kick.textureSkips,
            (unsigned long) (kick.totalSiteTicks[KICK_SITE_END] / KICK_MS_TICKS),
            (unsigned long) (kick.totalSiteTicks[KICK_SITE_IDLE] / KICK_MS_TICKS),
            (unsigned long) (kick.totalSiteTicks[KICK_SITE_DRAWS] / KICK_MS_TICKS),
            (unsigned long) (kick.totalSiteTicks[KICK_SITE_WRAP] / KICK_MS_TICKS),
            (unsigned long) (kick.totalSiteTicks[KICK_SITE_PRESSURE] / KICK_MS_TICKS),
            (unsigned long) kick.kickedSlow, (unsigned long) (kick.kickedSlowJoinTicks / KICK_MS_TICKS));
    logInfo(kickLog, (unsigned long) kick.kicks, (unsigned long) kick.deferred,
            (unsigned long) kick.fullSkips, (unsigned long) (kick.bytes / 1024),
            (unsigned long) kick.partialFinishes, (unsigned long) kick.pressure);
#if defined(CTR_KICK_MULTI) && defined(CTR_KICK_FORCE)
    logInfo(kickMultiLog, (unsigned long) kick.frames, (unsigned long) (kick.frameBytes / 1024));
#elif defined(CTR_KICK_MULTI)
    logInfo(kickGateTotals, (unsigned long) kick.frames, (unsigned long) (kick.frameBytes / 1024),
            (unsigned long) kick.gateFrames, (unsigned long) kick.gateTurns, (unsigned long) kick.cpuPastByJoins);
#endif
#ifdef CTR_KICK_TINY_RING_WORDS
    logInfo(kickTinyLog, (unsigned long) CTR_KICK_TINY_RING_WORDS,
            (unsigned long) kick.diagnosticWraps);
    logInfo(kickExtensionLog, (unsigned long) kick.diagnosticExtensions);
#endif
}

bool __real_CtrBench_takeFinished(void);
// main.c asks this once a frame with --exit-after; true means the test run has
// ended and the app is leaving. Normal play never reaches it.
KICK_TEXT bool __wrap_CtrBench_takeFinished(void) {
    bool finished = __real_CtrBench_takeFinished();
    if (finished) kickLogTotals();
    return finished;
}
#endif
