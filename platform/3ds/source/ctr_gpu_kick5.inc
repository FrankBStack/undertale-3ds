// KM rev 5 (change pacer), the append-only port onto 75zq (c26rev R131 F2). Included at ctr_gpu_queue.c's end in
// the launcher's second helper pass only (CTR_KICK_REV5, tools/analysis/cheaplevers_kick_compile.py). The first
// pass still builds KM rev 4.1 (ctr_gpu_kick.inc) exactly as 75zq has it: its code, constants and state keep their
// addresses and sizes, and each of its exported functions starts with a branch to its rev 5 twin here (the launcher
// prefixes every symbol of this pass with Km5_). This file's code, constants and state are in their own late
// sections (.text/.rodata/.bss.pacer_km5_late), after every earlier late input.
// This is deliberately separate from frameBusy, pendingQueue and completions.
// A range callback only consumes entries; only a whole-frame finish retires.
#include "ctr_gpu_kick.h"
#ifdef CTR_KICK_FORCE
// The forced arm (identity diagnostic) is R123's forced-every-boundary arm: it
// seals at every existing split with any command bytes, into a 2-slot FIFO, so
// the chain, FIFO-full fallback and generation reuse all run on Azahar too.
#define KICK_CHAIN_SLOTS 2u
#endif
#include "ctr_gpu_kick_chain.h"
#ifdef CTR_KICK_FRAME_TRACE
#include "ctr_log.h"
#endif
#define KICK_TEXT __attribute__((noinline, section(".text.pacer_km5_late")))
#define KICK_BSS __attribute__((section(".bss.pacer_km5_late")))
#define KICK_RO __attribute__((section(".rodata.pacer_km5_late")))
#define KICK_RING_RESERVE_WORDS 8192u
#define KICK_MS_TICKS ((uint64_t) SYSCLOCK_ARM11 / 1000u)
#ifndef CTR_KICK_MULTI
#error "KM rev 5 is the multi kick only (CTRPORT_GPU_KICK_MODE multi or multi-force)"
#endif
// Multi (change pacer): existing renderer splits hand the GPU what was recorded
// since the last one, so the GPU keeps pace with recording instead of starting
// the whole frame at C3D_FrameEnd. CTR_KICK_FORCE (identity diagnostic only)
// kicks whatever the gate says.
//
// Rev 4 (lead 2026-11-02): no per-frame log lines (each cost frame time through
// the bottom-screen log console). Rev 4.1: no KM line in play at all; totals
// are bench-only output, printed once as a test run ends.
//
// Rev 5 step 2 (lead 2026-11-02, c26rev R123 GO WITH CHANGES; changes 1, 2, 4
// of the overlap design, every wait and the full flushes kept):
// 1. A split kicks from KICK_MIN_BYTES (8 KB, was 32 KB) since the last sealed
//    entry, so the first range reaches the GPU early in the recording.
// 2. A bounded FIFO chain of sealed ranges (ctr_gpu_kick_chain.h): a split no
//    longer waits for the range before it to finish. It seals its entries into
//    the chain; each range's completion (GSP thread) starts the next sealed one.
//    One range on the GPU at a time, in order. A full FIFO seals nothing (the
//    entries stay with the recording: the original path).
// 4. The gate opens after one frame of the late-serial shape and shuts after
//    two frames in a row without it. Shape: CPU <= 30 ms and GPU <= 30 ms and
//    CPU + GPU >= 33.4 ms. The CPU is the whole recording, kick flushes and
//    joins inside it included (R123: the new work counts).
// Step 3 (change 3 alone): no end self-joins. Neither CtrKick_endFlush nor the
// renderer's end-of-frame wait joins this frame's ranges any more; the CPU goes
// on to the next frame while they run. The original suffix submission (startQueue,
// under gateLock) is held while a range still runs, since libctru runs one queue
// at a time and would ignore it: the chain's last completion runs it then (or
// finishes an empty one). The frame end still waits for the frame before, as
// before, so no frame is added to the GPU's queue. A frame ended behind another
// (CtrGpu_frameEndBehind) keeps the END join.
// F1 (c26rev R131): the ranges' GPU time a whole frame still has to add as it
// retires is kept per physical queue (kickFinal*), not in one record. An early
// end in the next recording (endFrameEarly: command room, readback, ...) while
// the frame before is still on the GPU used to take that frame's record, so its
// ranges' time never reached its frameGpuTicks (the gate's GPU input).
#ifdef CTR_KICK_FORCE
#define KICK_MIN_BYTES 1u
#else
#define KICK_MIN_BYTES (8u * 1024u)
#endif
// Ranges a split may leave queued or running (pacer-kc-r1 counts, 11-02): on
// Knight the first kick (25.8 ms) keeps the GPU busy to the frame's end (prefix
// 11.9 + suffix 12.5 ms) and every range chained behind a running one costs a
// ~0.5 ms completion-to-submit gap. So a split seals only with the GPU idle on
// this frame's ranges, as rev 4 did; the forced identity arm queues 2 deep.
#ifdef CTR_KICK_FORCE
#define KICK_CHAIN_DEPTH KICK_CHAIN_SLOTS
#else
#define KICK_CHAIN_DEPTH 1u
#endif
#define KICK_GATE_OFF_FRAMES 2u
#define KICK_GATE_CPU_TICKS (30u * KICK_MS_TICKS)
#define KICK_GATE_GPU_TICKS (30u * KICK_MS_TICKS)
#define KICK_GATE_SUM_TICKS (334u * KICK_MS_TICKS / 10u)

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

#ifdef CTR_KICK_FRAME_TRACE
// R123's compact in-memory trace (prototype builds): one record a frame, kept
// only for frames a bench window measures, printed between windows (and as the
// run ends), never in a window or in play. Times in 0.1 ms from the frame's
// begin; the GPU time the gate used (the last whole frame's) and the frame's
// own whole GPU time (written when it retires) side by side, by frame ID.
#define KICK_TRACE_RECORDS 1024u
#define KICK_TRACE_LINES 12u
typedef struct {
    u32 frame; // the renderer's frame ID
    u16 cpu, gateGpu, ownGpu, endJoin, innerJoin, flushUs, callbackUs, firstSeal, lastSeal, lastDone;
    u8 ranges, kb, flags, measured;
} KickTraceRecord;
enum { KT_GATE = 1, KT_SHAPE = 2, KT_TEXTURE = 4, KT_DEFERRED = 8, KT_FULL = 16, KT_RING = 32, KT_AFTER_END = 64 };
bool CtrBench_running(void);
bool CtrBench_wantsBottomScreen(void);
#endif

// F1: one record per physical queue (queues[], at most three). A queue is
// recorded again only after its whole frame finished (C3D_FrameEnd waits for
// the frame before), so two frames on the GPU never share a record.
#define KICK_FINALS 3u

static struct {
    KickChain chain;
    gxCmdQueue_s views[KICK_CHAIN_SLOTS];
    // Sealed copies at the recording's own indices: ranges never share entries.
    gxCmdEntry_s entries[CTR_GPU_QUEUE_ENTRIES];
    gxCmdQueue_s* recording;
    // F1: per queue, the GPU time of its frame's ranges (prefix ranges, then
    // ranges that finish after its end) its whole finish adds to frameGpuTicks.
    gxCmdQueue_s* finalQueue[KICK_FINALS];
    uint64_t finalTicks[KICK_FINALS];
    u32 finalFull, finalStale; // diagnostics: no free record (never expected), a record left by an unhooked finish
    // Step 3: the chain's own recording (its ranges may finish after its frame
    // ended), the frame end's suffix (wanted: its startQueue run comes next;
    // queue: held for the chain's last completion), and the renderer's end wait.
    gxCmdQueue_s* chainQueue;
    gxCmdQueue_s* suffixWanted;
    gxCmdQueue_s* suffixQueue;
    bool chainEnded, endWaitNext, inBehind;
    u32 suffixDeferred, suffixDeferredEmpty, endWaitsSkipped;
#ifdef CTR_KICK_FORCE
    u32 forceEndSeals;
    bool forceHold; // the frame-end range starts with the suffix submission
#endif
    void (*drain)(void*);
    void* context;
    u32 owner, due;
    volatile bool open, busy;
    bool draining;
    uint64_t started, prefixTicks;
    u32 kicks, deferred, fullSkips, fifoFull, staleCallbacks, frontierMismatch, bytes, pressure, partialFinishes;
    u32 frames, frameBytes; // kicked recordings, and bytes left for frame end
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
    // Per-frame counts (no per-frame log line) and their running totals.
    uint64_t frameBegin, siteTicks[5], totalSiteTicks[5];
    u32 frameKicks, frameKB, frameTextureSkips, frameSyncCopies, frameFenceHits, frameFenceSleeps;
    u32 kickHistogram[4], traceFrames, tracedSlow, kickedSlow;
    uint64_t kickedSlowJoinTicks;
    // Gate: frames in a row without the shape, open now, frames open, turns,
    // and kicked frames whose recording passed 30 ms of CPU.
    u32 miss, gateFrames, gateTurns, kickedOverCpu;
    bool gateOn;
#ifdef CTR_KICK_FRAME_TRACE
    KickTraceRecord trace[KICK_TRACE_RECORDS];
    u32 traceRead, traceLost, finalIndex[KICK_FINALS];
    uint64_t flushTicks, callbackTicks;
#endif
} kick KICK_BSS;

// kickWaitPrefix's callers, for the trace.
enum { KICK_SITE_END, KICK_SITE_IDLE, KICK_SITE_DRAWS, KICK_SITE_WRAP, KICK_SITE_PRESSURE };

#ifdef CTR_KICK_FRAME_TRACE
#define KICK_TRACE_NOW (&kick.trace[kick.traceFrames % KICK_TRACE_RECORDS])
KICK_TEXT static u16 kickTenths(uint64_t ticks) {
    uint64_t t = ticks * 10u / KICK_MS_TICKS;
    return (u16) (t > 0xFFFFu ? 0xFFFFu : t);
}
KICK_TEXT static u16 kickSince(uint64_t now) {
    return kick.frameBegin != 0 && now > kick.frameBegin ? kickTenths(now - kick.frameBegin) : 0;
}
#endif

// gateLock held. Every change to the chain republishes busy for lock-free readers.
KICK_TEXT static void kickPublishBusy(void) {
    __atomic_store_n(&kick.busy, kickChainBusy(&kick.chain), __ATOMIC_RELEASE);
}

// gateLock held (F1). The record of queue's whole frame, or -1; with queue
// nullptr, a free record.
KICK_TEXT static int kickFinalOf(const gxCmdQueue_s* queue) {
    for (u32 i = 0; i < KICK_FINALS; i++) {
        if (kick.finalQueue[i] == queue) return (int) i;
    }
    return -1;
}

// gateLock held (F1). queue's whole frame retires: its ranges' GPU time joins
// frameGpuTicks (the original finish adds the suffix and publishes the total).
// False if queue's frame kicked nothing. *index: the record's trace frame.
KICK_TEXT static bool kickFinalTake(const gxCmdQueue_s* queue, u32* index) {
    int i = queue != nullptr ? kickFinalOf(queue) : -1;
    if (i < 0) return false;
    frameGpuTicks += kick.finalTicks[i];
    kick.finalTicks[i] = 0;
    kick.finalQueue[i] = nullptr;
#ifdef CTR_KICK_FRAME_TRACE
    *index = kick.finalIndex[i];
#else
    *index = 0;
#endif
    return true;
}

// gateLock held. Starts the oldest sealed range when nothing of this chain and
// no whole frame is on the GPU. Never waits; safe from the range callback
// (libctru clears isRunning before it calls back).
void __real_gxCmdQueueRun(gxCmdQueue_s* queue);
KICK_TEXT static void kickStartLocked(void) {
    // The whole frame on the GPU holds a range back, unless that frame is this
    // chain's own, its suffix held until the chain drains (step 3).
    if (frameBusy && kick.suffixQueue == nullptr) return;
#ifdef CTR_KICK_FORCE
    if (kick.forceHold) return;
#endif
    int i = kickChainNext(&kick.chain);
    if (i < 0) return;
    kick.started = svcGetSystemTick();
    kick.kicks++;
    __real_gxCmdQueueRun(&kick.views[i]);
}

// gateLock held (step 3). The chain has drained and its frame's end held the
// suffix's run: run it now, or finish an empty one (libctru calls nothing back
// for a run with nothing to send), as kickWholeFinished would.
KICK_TEXT static void kickRunSuffixLocked(uint64_t now) {
    gxCmdQueue_s* queue = kick.suffixQueue;
    if (queue == nullptr || kickChainBusy(&kick.chain)) return;
    kick.suffixQueue = nullptr;
    segmentStart = runStart = now; // the suffix's GPU time from its real start
    if (queue->lastEntry < queue->numEntries) {
        __real_gxCmdQueueRun(queue);
        return;
    }
    kick.suffixDeferredEmpty++;
    u32 index;
    bool kicked = kickFinalTake(queue, &index);
    (void) kicked;
    onQueueFinishLocked(queue);
#ifdef CTR_KICK_FRAME_TRACE
    if (kicked) kick.trace[index % KICK_TRACE_RECORDS].ownGpu = kickTenths(lastGpuTicks);
#endif
    kickStartLocked();
}

// A range's completion, on the GSP thread: advance the completed frontier and
// start the next sealed range. No flush, wait, log, allocation or retirement.
KICK_TEXT static void kickRangeFinished(gxCmdQueue_s* view) {
    uint64_t now = svcGetSystemTick();
    LightLock_Lock(&gateLock);
    if (view >= kick.views && view < kick.views + KICK_CHAIN_SLOTS &&
        kickChainFinished(&kick.chain, (uint32_t) (view - kick.views), (uint32_t) (uintptr_t) view->user)) {
        // A range finishing after its frame's end counts in that frame's GPU time
        // (F1: the record of the chain's own queue).
        int final = kick.chainEnded ? kickFinalOf(kick.chainQueue) : -1;
        if (final >= 0) kick.finalTicks[final] += now - kick.started;
        else if (!kick.chainEnded) kick.prefixTicks += now - kick.started;
        // The chain's own recording (its frame may have ended): the consumed
        // entries, for the suffix submission.
        kick.chainQueue->curEntry = kick.chainQueue->lastEntry = kick.chain.completedEnd;
        kick.partialFinishes++;
#ifdef CTR_KICK_FRAME_TRACE
        if (final >= 0) kick.trace[kick.finalIndex[final] % KICK_TRACE_RECORDS].flags |= KT_AFTER_END;
        else if (!kick.chainEnded) KICK_TRACE_NOW->lastDone = kickSince(now);
#endif
        kickStartLocked();
        kickRunSuffixLocked(now);
        kickPublishBusy();
    } else {
        kick.staleCallbacks++;
    }
#ifdef CTR_KICK_FRAME_TRACE
    kick.callbackTicks += svcGetSystemTick() - now;
#endif
    LightLock_Unlock(&gateLock);
}

// The original callback still owns full-frame statistics, transfers and flips.
// A sealed range starts only after all previously submitted frames finish.
KICK_TEXT static void kickWholeFinished(gxCmdQueue_s* queue) {
    LightLock_Lock(&gateLock);
    u32 index;
    bool kicked = kickFinalTake(queue, &index);
    LightLock_Unlock(&gateLock);
#ifdef CTRPORT_RING_FINISH_CHECK
    kickOriginalRingCallback(queue);
#else
    kickOriginalCallback(queue);
#endif
    LightLock_Lock(&gateLock);
#ifdef CTR_KICK_FRAME_TRACE
    // lastGpuTicks is now this frame's whole GPU time (its ranges included).
    if (kicked) kick.trace[index % KICK_TRACE_RECORDS].ownGpu = kickTenths(lastGpuTicks);
#else
    (void) kicked;
#endif
    kickStartLocked();
    LightLock_Unlock(&gateLock);
}

KICK_TEXT static bool kickCallbacks(void) {
    LightLock_Lock(&gateLock);
#if defined(CTR_KICK_FORCE)
    bool gpuBound = true;
#else
    bool gpuBound = kick.gateOn;
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

// A physical drain of every sealed range. It never waits for the recording
// frame to be ended, and never holds gateLock while it sleeps.
KICK_TEXT static void kickWaitPrefix(int site) {
#ifdef CTR_KICK_FORCE
    kick.forceHold = false;
#endif
    uint64_t start = svcGetSystemTick();
    uint64_t accounted = waitTotalTicks;
    for (;;) {
        LightLock_Lock(&gateLock);
        kickStartLocked();
        bool waiting = kickChainBusy(&kick.chain);
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
    // open is published before a range can run, and cleared only after the
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

// No range while a tile load, fill, whole-page read or sync copy is already
// known when the split comes, nor in the frame after a measured tile load.
// Engine-wide, no scene list. Not covered (R111 F2): a load asked for later in
// the same frame, after a range has gone.
KICK_TEXT static bool kickTextureFrame(void) {
    return kick.loadedBefore || kick.frameSyncCopies != 0 ||
           (kick.textureBusy != nullptr && kick.context != nullptr && kick.textureBusy(kick.context));
}

void __real_C3D_SyncTextureCopy(u32* inadr, u32 indim, u32* outadr, u32 outdim, u32 size, u32 flags);
KICK_TEXT void __wrap_C3D_SyncTextureCopy(u32* inadr, u32 indim, u32* outadr, u32 outdim, u32 size, u32 flags) {
    kick.frameSyncCopies++;
    __real_C3D_SyncTextureCopy(inadr, indim, outadr, outdim, size, flags);
}

#ifdef CTR_KICK_FRAME_TRACE
static const char kickTraceLine[] KICK_RO =
    "KT %lu c%u g%u o%u e%u i%u f%u b%u s%u-%u d%u r%u k%u x%u\n";
static const char kickTraceLost[] KICK_RO = "KT lost %lu\n";
// Prints up to max finished, measured records (all but the two newest, whose
// whole GPU time may not be in yet, unless all).
KICK_TEXT static void kickTraceDrain(u32 max, bool all) {
    u32 end = kick.traceFrames - (all ? 0u : 2u);
    if (kick.traceFrames < 2u && !all) return;
    if (end - kick.traceRead > KICK_TRACE_RECORDS) {
        kick.traceLost += end - kick.traceRead - KICK_TRACE_RECORDS;
        kick.traceRead = end - KICK_TRACE_RECORDS;
        logInfo(kickTraceLost, (unsigned long) kick.traceLost);
    }
    for (u32 n = 0; n < max && kick.traceRead != end; kick.traceRead++) {
        KickTraceRecord* t = &kick.trace[kick.traceRead % KICK_TRACE_RECORDS];
        if (!t->measured) continue;
        t->measured = 0;
        n++;
        logInfo(kickTraceLine, (unsigned long) t->frame, t->cpu, t->gateGpu, t->ownGpu, t->endJoin, t->innerJoin,
                t->flushUs, t->callbackUs, t->firstSeal, t->lastSeal, t->lastDone, t->ranges, t->kb, t->flags);
        // The test end prints up to the whole ring at once: wait for the log writer
        // now and then, or it drops lines (the bench's own end lines among them).
        if (all && n % 16u == 0) CtrLog_flush();
    }
}
#endif

// Ends the frame before (counts, gate) and starts the next one's counts.
// Called from the renderer's begin, before its own begin runs.
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
        // The frame that just ended: its whole recording (C3D_FrameBegin to
        // C3D_FrameEnd's tick update: kick flushes and the joins inside it
        // included), and the GPU's last whole frame, under its writer's lock.
        uint64_t cpu = cpuTime.elapsed;
        LightLock_Lock(&gateLock);
        uint64_t gpu = lastGpuTicks;
        LightLock_Unlock(&gateLock);
        if (kick.frameKicks != 0 && cpu > KICK_GATE_CPU_TICKS) kick.kickedOverCpu++;
        bool shape = cpu + gpu >= KICK_GATE_SUM_TICKS && cpu <= KICK_GATE_CPU_TICKS && gpu <= KICK_GATE_GPU_TICKS;
        (void) shape; // forced builds and builds without the trace read it nowhere else
#ifndef CTR_KICK_FORCE
        // One frame of the shape opens the gate; KICK_GATE_OFF_FRAMES in a row without it shut it.
        kick.miss = shape ? 0u : kick.miss + 1u;
        bool open = shape ? true : (kick.miss >= KICK_GATE_OFF_FRAMES ? false : kick.gateOn);
        if (open != kick.gateOn) kick.gateTurns++;
        kick.gateOn = open;
        if (open) kick.gateFrames++;
#endif
#ifdef CTR_KICK_FRAME_TRACE
        KickTraceRecord* t = KICK_TRACE_NOW;
        t->frame = kick.frame;
        t->cpu = kickTenths(cpu);
        t->gateGpu = kickTenths(gpu);
        t->endJoin = kickTenths(kick.siteTicks[KICK_SITE_END]);
        t->innerJoin = kickTenths(waited - kick.siteTicks[KICK_SITE_END]);
        uint64_t us = kick.flushTicks * 1000u / KICK_MS_TICKS, cb = kick.callbackTicks * 1000u / KICK_MS_TICKS;
        t->flushUs = (u16) (us > 0xFFFFu ? 0xFFFFu : us);
        t->callbackUs = (u16) (cb > 0xFFFFu ? 0xFFFFu : cb);
        t->ranges = (u8) (kick.frameKicks > 255u ? 255u : kick.frameKicks);
        t->kb = (u8) (kick.frameKB > 255u ? 255u : kick.frameKB);
        t->flags |= (u8) ((shape ? KT_SHAPE : 0) | (kick.gateOn ? KT_GATE : 0));
        t->measured = CtrBench_running() && !CtrBench_wantsBottomScreen();
        kick.flushTicks = kick.callbackTicks = 0;
#endif
        kick.traceFrames++;
        // Slow frames (over a 30 fps slot) and frames that joined a range for 2 ms or more: counted only.
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
#ifdef CTR_KICK_FRAME_TRACE
    LightLock_Lock(&gateLock);
    memset(KICK_TRACE_NOW, 0, sizeof(KickTraceRecord));
    LightLock_Unlock(&gateLock);
    // Between bench windows only: never in a window, never in play (no record is measured there).
    if (!CtrBench_running() || CtrBench_wantsBottomScreen()) kickTraceDrain(KICK_TRACE_LINES, false);
#endif
}

KICK_TEXT void CtrKick_setFrame(uint32_t frame) {
    kick.frame = frame;
    // F1: after the renderer's begin, the bound queue records and so is not on
    // the GPU. A record still naming it was left by a finish that bypassed the
    // kick's hooks (held transfers dropped after 250 ms without a vblank, a
    // stopped queue): drop it, so a later frame of this queue does not add it.
    if (!inFrame) return;
    LightLock_Lock(&gateLock);
    int stale = kickFinalOf(boundQueue());
    if (stale >= 0) {
        kick.finalQueue[stale] = nullptr;
        kick.finalTicks[stale] = 0;
        kick.finalStale++;
    }
    LightLock_Unlock(&gateLock);
}

// Generic opportunity: an existing renderer split has just closed a list.
// Skip near either ring's limit so the original full-drain fallback has room.
KICK_TEXT void __wrap_C3D_FrameSplit(u8 flags) {
    __real_C3D_FrameSplit(flags);
    if (!inFrame || kick.drain == nullptr || kick.draining) return;
    gxCmdQueue_s* queue = boundQueue();
    // One chain per physical recording.
    if (kick.open && queue != kick.recording) return;
    if (queue->numEntries > CTR_GPU_QUEUE_ENTRIES || queue->numEntries + 8u >= queue->maxEntries ||
        gpuCmdBufOffset + KICK_RING_RESERVE_WORDS >= gpuCmdBufSize) {
        kick.fullSkips++;
#ifdef CTR_KICK_FRAME_TRACE
        KICK_TRACE_NOW->flags |= KT_RING;
#endif
        return;
    }
    // The recording thread is the only writer of sealedEnd.
    u32 from = kick.open ? kick.chain.sealedEnd : queue->curEntry;
    u32 bytes = 0;
    for (u32 i = from; i < queue->numEntries; i++) {
        const u32* cmd = queue->entries[i].data;
        if ((cmd[0] & 0xFF) == 1) bytes += cmd[2]; // GX_ProcessCommandList, bytes
    }
    // An empty entry range leaves bytes at zero, below KICK_MIN_BYTES: no empty range is ever sealed.
    if (bytes < KICK_MIN_BYTES) return;
    // The guard decides once per recording; later ranges follow the first.
    if (!kick.open && !kickCallbacks()) return;
    if (kickTextureFrame()) {
        kick.textureSkips++;
        kick.frameTextureSkips++;
#ifdef CTR_KICK_FRAME_TRACE
        KICK_TRACE_NOW->flags |= KT_TEXTURE;
#endif
        return;
    }
    // FIFO room (completions only free slots, so the seal below finds it still).
    // A new chain needs the last one fully drained (the end join ensures it).
    LightLock_Lock(&gateLock);
    bool room = kickChainCount(&kick.chain) < KICK_CHAIN_DEPTH && !kickChainFull(&kick.chain) &&
                (kick.open || !kickChainBusy(&kick.chain));
    LightLock_Unlock(&gateLock);
    if (!room) {
        kick.fifoFull++;
#ifdef CTR_KICK_FRAME_TRACE
        KICK_TRACE_NOW->flags |= KT_FULL;
#endif
        return; // the original path: these entries wait for the next split or the suffix
    }
    extern u32 __ctru_linear_heap, __ctru_linear_heap_size;
    // Exactly frame end's full-heap flush, including vertices and command lists.
    // Later entries go into the recording queue, never a sealed range.
#ifdef CTR_KICK_FRAME_TRACE
    uint64_t flushStart = svcGetSystemTick();
#endif
    GSPGPU_FlushDataCache((void*) __ctru_linear_heap, __ctru_linear_heap_size);
    LightLock_Lock(&gateLock);
#ifdef CTR_KICK_FRAME_TRACE
    uint64_t sealed = svcGetSystemTick();
    kick.flushTicks += sealed - flushStart;
#endif
    if (!kick.open) {
        if (!kickChainReset(&kick.chain, from)) {
            LightLock_Unlock(&gateLock);
            return;
        }
        kick.recording = kick.chainQueue = queue;
        kick.chainEnded = false;
        kick.frames++;
        kick.due = completions + (frameBusy ? (pendingQueue != nullptr ? 2u : 1u) : 0u) + 1u;
    }
    u32 to = queue->numEntries;
    // Disjoint from every live range: those hold indices below from.
    memcpy(kick.entries + from, queue->entries + from, (to - from) * sizeof(gxCmdEntry_s));
    int slot = kickChainSeal(&kick.chain, to);
    if (slot >= 0) {
        gxCmdQueue_s* view = &kick.views[slot];
        view->entries = kick.entries + from;
        view->maxEntries = view->numEntries = to - from;
        view->curEntry = view->lastEntry = 0;
        view->callback = kickRangeFinished;
        view->user = (void*) (uintptr_t) kick.chain.slot[slot].gen;
        __atomic_store_n(&kick.open, true, __ATOMIC_RELEASE);
        queueRuns++; // invalidates pre-seal copy-cancellation handles
        kick.bytes += bytes;
        kick.frameKicks++;
        kick.frameKB += bytes / 1024u;
        if (frameBusy) kick.deferred++;
#ifdef CTR_KICK_FRAME_TRACE
        KickTraceRecord* t = KICK_TRACE_NOW;
        if (t->firstSeal == 0) t->firstSeal = kickSince(sealed);
        t->lastSeal = kickSince(sealed);
        if (frameBusy) t->flags |= KT_DEFERRED;
#endif
        kickPublishBusy();
        kickStartLocked();
    }
    LightLock_Unlock(&gateLock);
#ifdef CTR_KICK_SERIAL_PREFIX
    // Diagnostic isolation only: preserve range boundaries and whole-frame
    // retirement, but remove CPU recording overlap with the submitted range.
    kickWaitPrefix(KICK_SITE_IDLE);
#endif
#ifdef CTR_KICK_FORCE_PRESSURE
    // Stress the dangerous physically-idle, not-yet-retired state. A range
    // completion alone must not release a free or satisfy its frame fence.
    kickWaitPrefix(KICK_SITE_IDLE);
    __real_CtrGpu_waitIdle();
    if (!kick.open || (int32_t) (completions - kick.due) >= 0) svcBreak(USERBREAK_PANIC);
    CtrMemory_kickPressureTest();
#endif
}

// Wrappers cover external physical waits. Step 3: the renderer's end-of-frame
// wait (right after CtrPacer_stressStep) is for the frame before only ("done with
// the frame before, the GPU can start this one"): it no longer joins this
// frame's ranges.
KICK_TEXT void __wrap_CtrGpu_waitIdle(void) {
    if (kick.endWaitNext) {
        kick.endWaitNext = false;
        if (kick.open) {
            kick.endWaitsSkipped++;
            __real_CtrGpu_waitIdle();
            return;
        }
    }
    kickWaitPrefix(KICK_SITE_IDLE);
    __real_CtrGpu_waitIdle();
}

void __real_CtrPacer_stressStep(bool shown);
// Called once a frame, in CtrRenderer_endFrame, just before its end wait.
KICK_TEXT void __wrap_CtrPacer_stressStep(bool shown) {
    __real_CtrPacer_stressStep(shown);
    kick.endWaitNext = true;
}

// After the renderer's whole end of frame: an end wait it skipped (a frame
// ended behind another) must not excuse a later wait. (Declared here, not in
// ctr_gpu_kick.h, which KM rev 4.1's pass includes unchanged.)
void CtrKick_endFrameDone(void);
KICK_TEXT void CtrKick_endFrameDone(void) {
    kick.endWaitNext = false;
}

// Step 3, gateLock held: startQueue's run of the frame-end suffix. While a
// range of its chain still runs, libctru would ignore it (one queue at a time):
// hold it for kickRunSuffixLocked. Every other run passes straight through.
KICK_TEXT void __wrap_gxCmdQueueRun(gxCmdQueue_s* queue) {
    if (queue == kick.suffixWanted) {
        kick.suffixWanted = nullptr;
#ifdef CTR_KICK_FORCE
        bool held = kick.forceHold;
        kick.forceHold = false;
#endif
        if (kickChainBusy(&kick.chain)) {
            kick.suffixQueue = queue;
            kick.suffixDeferred++;
#ifdef CTR_KICK_FORCE
            if (held) kickStartLocked();
#endif
            return;
        }
    }
    __real_gxCmdQueueRun(queue);
}

KICK_TEXT void __wrap_CtrGpu_waitDraws(void) {
    kickWaitPrefix(KICK_SITE_DRAWS);
    __real_CtrGpu_waitDraws();
}

KICK_TEXT bool __wrap_CtrGpu_busy(void) {
    return __real_CtrGpu_busy() || __atomic_load_n(&kick.busy, __ATOMIC_ACQUIRE);
}

KICK_TEXT void __wrap_CtrGpu_wrapCommandBuffer(void) {
    kickWaitPrefix(KICK_SITE_WRAP);
    // canWrap's ring-reuse hook can make room by extending the current span.
    // asgRoomSlow then splits and calls wrap without rechecking that room,
    // unlike makeCommandRoom. A split has already closed the list: retain the
    // extended span instead of resetting it when no physical wrap was granted.
    // Do not turn a range finish into a whole-frame completion or ring reuse.
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
    // A sealed entry's copy is already in a range: cancelling the recording's entry would not reach the GPU.
    if (kick.open && queued.queue == kick.recording && queued.index < kick.chain.sealedEnd) return false;
    return __real_CtrGpu_cancelCopy(queued, from, to);
}

// Exactly one original ARM call in EACH frame-end path targets this helper.
// Their split and wait can be inlined, so --wrap cannot intercept them.
// Finish CPU recording and its flush BEFORE draining the ranges, then prepare
// their accounting before either original suffix submission can run. Both
// original flush callers discard Result; this replacement has no return value.
// Retain the whole-frame retirement fence until the end wrapper returns.
#ifdef CTR_KICK_FORCE
// Forced identity arm only: also seal what the frame's last split left (its
// final command list included), right after the frame end's full flush. The
// suffix startQueue then submits is the frame's transfers or nothing, and the
// chain is often still running then, on Azahar too: both held-suffix paths run.
KICK_TEXT static void kickForceEndSeal(void) {
    gxCmdQueue_s* queue = kick.recording;
    LightLock_Lock(&gateLock);
    u32 from = kick.chain.sealedEnd, to = queue->numEntries;
    if (to > from && to <= CTR_GPU_QUEUE_ENTRIES && kickChainCount(&kick.chain) < KICK_CHAIN_DEPTH &&
        !kickChainFull(&kick.chain)) {
        memcpy(kick.entries + from, queue->entries + from, (to - from) * sizeof(gxCmdEntry_s));
        int slot = kickChainSeal(&kick.chain, to);
        if (slot >= 0) {
            gxCmdQueue_s* view = &kick.views[slot];
            view->entries = kick.entries + from;
            view->maxEntries = view->numEntries = to - from;
            view->curEntry = view->lastEntry = 0;
            view->callback = kickRangeFinished;
            view->user = (void*) (uintptr_t) kick.chain.slot[slot].gen;
            queueRuns++; // invalidates pre-seal copy-cancellation handles
            kick.forceEndSeals++;
            kickPublishBusy();
            // Started by startQueue's suffix submission (__wrap_gxCmdQueueRun),
            // so that submission finds the chain busy and holds the suffix.
            kick.forceHold = true;
        }
    }
    LightLock_Unlock(&gateLock);
}
#endif

KICK_TEXT void CtrKick_endFlush(const void* address, u32 size) {
    GSPGPU_FlushDataCache(address, size);
    if (!kick.open) return;
#ifdef CTR_KICK_FORCE
    if (!kick.inBehind) kickForceEndSeal();
#endif
    // Step 3: no END join, except for a frame ended behind another (its queue
    // may wait as pendingQueue, which a held suffix must never be).
    if (kick.inBehind) kickWaitPrefix(KICK_SITE_END);
    LightLock_Lock(&gateLock);
    // A drained chain: the suffix starts where the chain ended.
    if (!kickChainBusy(&kick.chain) && kick.recording->curEntry != kick.chain.sealedEnd) kick.frontierMismatch++;
    // F1: this queue's own record. A frame before, still on the GPU (an early
    // end here: its suffix or held transfers still run), keeps its record until
    // its own whole finish adds it.
    int final = kickFinalOf(kick.recording);
    if (final < 0) final = kickFinalOf(nullptr);
    if (final >= 0) {
        kick.finalQueue[final] = kick.recording;
        kick.finalTicks[final] = kick.prefixTicks;
#ifdef CTR_KICK_FRAME_TRACE
        kick.finalIndex[final] = kick.traceFrames;
#endif
    } else {
        kick.finalFull++;
    }
    kick.prefixTicks = 0;
    kick.chainEnded = true;
    // startQueue's run of this queue comes next, under gateLock (__wrap_gxCmdQueueRun).
    kick.suffixWanted = kick.inBehind ? nullptr : kick.recording;
    for (u32 i = kick.chain.sealedEnd; i < kick.recording->numEntries; i++) {
        const u32* cmd = kick.recording->entries[i].data;
        if ((cmd[0] & 0xFF) == 1) kick.frameBytes += cmd[2];
    }
    LightLock_Unlock(&gateLock);
}

KICK_TEXT static void kickEndComplete(void) {
    LightLock_Lock(&gateLock);
    gxCmdQueue_s* queue = kick.recording;
    // All work may have been consumed by ranges. libctru emits no callback
    // for an empty suffix; retire it here, only after the whole end was called.
    if (!frameBusy && pendingQueue == nullptr && (int32_t) (completions - kick.due) < 0 &&
        queue->lastEntry == queue->numEntries) {
        u32 index;
        kickFinalTake(queue, &index);
        kickOriginalFinish(queue);
    }
    __atomic_store_n(&kick.open, false, __ATOMIC_RELEASE);
    kick.recording = nullptr;
    kick.suffixWanted = nullptr; // startQueue has run (or held) it, or it ended behind another
    kick.endWaitNext = false;
#ifdef CTR_KICK_FORCE
    if (kick.forceHold) {
        kick.forceHold = false;
        kickStartLocked();
    }
#endif
    LightLock_Unlock(&gateLock);
}

KICK_TEXT void __wrap_C3D_FrameEnd(u8 flags) {
    // Always take the full-heap flush and its scoped end-join hook, including
    // callers that ordinarily request per-list flushing instead. No new frame
    // is buffered and no range can cross the original suffix submission.
    __real_C3D_FrameEnd(flags & ~GX_CMDLIST_FLUSH);
    if (kick.open) kickEndComplete();
}

KICK_TEXT bool __wrap_CtrGpu_frameEndBehind(void) {
    // A declined behind-frame attempt has not closed anything: let recording
    // continue without joining the ranges. Successful closure reaches the
    // same scoped heap-flush join as ordinary frame end.
    kick.inBehind = true;
    bool ended = __real_CtrGpu_frameEndBehind();
    kick.inBehind = false;
    if (ended && kick.open) kickEndComplete();
    return ended;
}

#ifdef CTR_KICK_BENCH_TOTALS
// R147 F2 (RULES 755a82c45): rev 4.1 holds these two formats byte for byte. The kick launcher assembles both
// passes into one file and leaves these names unprefixed, so rev 5 prints rev 4.1's retained copies.
extern const char kickLog[];
extern const char kickTraceLog[];
static const char kickChainLog[] KICK_RO =
    "GPU kick chain: %lu splits behind a range or FIFO full, %lu stale callbacks, %lu frontier mismatches; "
    "suffix held for the chain %lu (%lu empty), end waits not joined %lu; final records full %lu, stale %lu\n";
#ifdef CTR_KICK_FORCE
static const char kickForceLog[] KICK_RO = "GPU kick forced: %lu frame-end seals\n";
#endif
static const char kickGateTotals[] KICK_RO =
    "GPU kick multi: %lu frames, %lu KB left for frame end; gate open %lu frames, %lu turns; "
    "%lu kicked frames over 30 ms of CPU\n";
#ifdef CTR_KICK_TINY_RING_WORDS
static const char kickTinyLog[] KICK_RO =
    "GPU kick diagnostic: %lu ring words, %lu completed wraps\n";
static const char kickExtensionLog[] KICK_RO =
    "GPU kick diagnostic: %lu extended spans kept without wrapping\n";
#endif
KICK_TEXT static void kickLogTotals(void) {
    // The run's cumulative counters, once, after its last measured frame.
#ifdef CTR_KICK_FRAME_TRACE
    kickTraceDrain(KICK_TRACE_RECORDS, true);
    CtrLog_flush();
#endif
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
    logInfo(kickChainLog, (unsigned long) kick.fifoFull, (unsigned long) kick.staleCallbacks,
            (unsigned long) kick.frontierMismatch, (unsigned long) kick.suffixDeferred,
            (unsigned long) kick.suffixDeferredEmpty, (unsigned long) kick.endWaitsSkipped,
            (unsigned long) kick.finalFull, (unsigned long) kick.finalStale);
#ifdef CTR_KICK_FORCE
    logInfo(kickForceLog, (unsigned long) kick.forceEndSeals);
#endif
    logInfo(kickGateTotals, (unsigned long) kick.frames, (unsigned long) (kick.frameBytes / 1024),
            (unsigned long) kick.gateFrames, (unsigned long) kick.gateTurns, (unsigned long) kick.kickedOverCpu);
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
