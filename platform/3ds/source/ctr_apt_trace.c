#include "ctr_apt_trace.h"

#include <3ds.h>
#include <citro3d.h>

#include "common.h"
#include "ctr_log.h"
#include "log.h"

// The console froze on real hardware between the app's suspend hook and the
// HOME Menu appearing, inside libctru's aptJumpToHomeMenu. These wrappers
// (linked with -Wl,--wrap, see CMakeLists.txt) log each step it takes from
// there, flushing as they go, so the last line in log.txt names the step that
// never returned:
//   citro3d waits for the GPU queue -> GSP saves its VRAM area -> APT hands
//   the screens to the HOME Menu -> NDSP puts the DSP to sleep -> GSP gives
//   up the GPU -> HOME Menu.

static volatile bool tracing = false;
static bool hooked = false;
static aptHookCookie aptCookie;
static dspHookCookie dspCookie;

Result __real_GSPGPU_SaveVramSysArea(void);
Result __real_GSPGPU_ImportDisplayCaptureInfo(GSPGPU_CaptureInfo* captureinfo);
Result __real_GSPGPU_ReleaseRight(void);
Result __real_GSPGPU_AcquireRight(u8 flags);
bool __real_gxCmdQueueWait(gxCmdQueue_s* queue, s64 timeout);

static void step(const char* text) {
    logInfo("APT: %s\n", text);
    CtrLog_flush();
}

Result __wrap_GSPGPU_SaveVramSysArea(void) {
    if (tracing) step("saving the system VRAM area");
    Result res = __real_GSPGPU_SaveVramSysArea();
    if (tracing) step("saved; handing the screens over");
    return res;
}

Result __wrap_GSPGPU_ImportDisplayCaptureInfo(GSPGPU_CaptureInfo* captureinfo) {
    Result res = __real_GSPGPU_ImportDisplayCaptureInfo(captureinfo);
    if (tracing) {
        logInfo("APT: screen capture info: top %p format 0x%lX, bottom %p format 0x%lX\n", captureinfo->screencapture[0].framebuf0_vaddr,
                (unsigned long) captureinfo->screencapture[0].format, captureinfo->screencapture[1].framebuf0_vaddr,
                (unsigned long) captureinfo->screencapture[1].format);
        CtrLog_flush();
    }
    return res;
}

Result __wrap_GSPGPU_ReleaseRight(void) {
    if (tracing) step("releasing the GPU");
    Result res = __real_GSPGPU_ReleaseRight();
    if (tracing) step("GPU released; the HOME Menu should open");
    return res;
}

Result __wrap_GSPGPU_AcquireRight(u8 flags) {
    if (tracing) step("taking the GPU back");
    Result res = __real_GSPGPU_AcquireRight(flags);
    if (tracing) step("GPU back");
    return res;
}

bool __wrap_gxCmdQueueWait(gxCmdQueue_s* queue, s64 timeout) {
    // citro3d's own suspend hook waits for its queue with no timeout.
    bool trace = tracing && 0 > timeout;
    if (trace) step("waiting for the GPU queue");
    bool done = __real_gxCmdQueueWait(queue, timeout);
    if (trace) step("GPU queue done");
    return done;
}

static void onDspEvent(DSP_HookType hook) {
    if (!tracing) return;
    if (hook == DSPHOOK_ONSLEEP) step("putting the DSP to sleep");
    else if (hook == DSPHOOK_ONWAKEUP) step("waking the DSP");
    else if (hook == DSPHOOK_ONCANCEL) step("DSP sleep cancelled");
}

// While suspended, a thread at the top and one at the bottom of the app's
// priorities each log every few seconds. If the HOME Menu never shows up,
// the high one ticking means the process is alive, and the low one ticking
// means none of the game's threads is hogging the app core.
#define HEARTBEAT_SECONDS 3
#define HEARTBEAT_LIMIT_SECONDS 45
#define HEARTBEAT_STACK_SIZE (8 * 1024)

static volatile u64 suspendTick = 0;
static volatile bool closing = false;

#ifdef ENABLE_WAD16
void auditfixgF2Wait(s64 timeout);
void auditfixgF2Wake(void);
void auditfixgF2Exit(int status) __attribute__((noreturn));
// Retain the worker's instruction shape; only its timed-wait call target changes.
#define svcSleepThread auditfixgF2Wait
#endif
#line 94
static void heartbeatMain(void* arg) {
    const char* name = arg;
    while (!closing) {
        svcSleepThread(HEARTBEAT_SECONDS * 1000 * 1000 * 1000LL);
        if (!tracing || closing) continue;
        u64 seconds = (svcGetSystemTick() - suspendTick) / SYSCLOCK_ARM11;
        if (seconds > HEARTBEAT_LIMIT_SECONDS) continue;
        logInfo("APT: %s thread still running, %llu s after suspending\n", name, (unsigned long long) seconds);
        CtrLog_flush();
    }
}

#undef svcSleepThread
#line 106
static void onAptEvent(APT_HookType hook, void* param) {
    (void) param;
    if (hook == APTHOOK_ONSUSPEND || hook == APTHOOK_ONSLEEP) {
        suspendTick = svcGetSystemTick();
        tracing = true;
        step(hook == APTHOOK_ONSLEEP ? "going to sleep" : "HOME pressed, suspending");
    } else if (hook == APTHOOK_ONRESTORE || hook == APTHOOK_ONWAKEUP) {
        step("back in the game");
        tracing = false;
    } else if (hook == APTHOOK_ONEXIT) {
        closing = true;
        tracing = false;
    }
}

#ifdef ENABLE_WAD16
static Thread auditfixgR2TraceCreate(ThreadFunc entry, void* arg, size_t stack, int priority, int core, bool detached);
static void auditfixgR2TraceStop(void) __attribute__((used));
#else
#define auditfixgR2TraceCreate threadCreate
#endif

void CtrAptTrace_init(void) {
    if (hooked) return;
    hooked = true;
    // Hooks run newest first, so these run before the renderer's, the
    // watchdog's, citro3d's and NDSP's.
    aptHook(&aptCookie, onAptEvent, nullptr);
    dspHook(&dspCookie, onDspEvent);
    auditfixgR2TraceCreate(heartbeatMain, (void*) "high-priority (0x18)", HEARTBEAT_STACK_SIZE, 0x18, 0, true);
    auditfixgR2TraceCreate(heartbeatMain, (void*) "low-priority (0x3F)", HEARTBEAT_STACK_SIZE, 0x3F, 0, true);
}

void CtrAptTrace_stop(void) {
    closing = true;
    tracing = false;
#ifdef ENABLE_WAD16
    auditfixgF2Wake();
#endif
}
#line 140

#ifdef ENABLE_WAD16
// SCOURS2-009: retain the original init call shape and pool; the adapter owns
// joinable handles. New code/state are appended, with no new log strings.
#define TRACE_R2_CODE __attribute__((noinline, noipa, optimize("Os"), section(".auditfixg_r2_heartbeat_text")))
static Thread auditfixgR2Threads[2] __attribute__((section(".bss_auditfixg_r2_heartbeat,\"aw\",%nobits @")));
// 0: accepting creates, 1: create/handle publication in progress, 2: exit owns
// the handles. Never wait for a possibly faulted initializer at process exit.
static u32 auditfixgR2CreateState __attribute__((section(".bss_auditfixg_r2_heartbeat,\"aw\",%nobits @")));

static TRACE_R2_CODE Thread auditfixgR2TraceCreate(ThreadFunc entry, void* arg, size_t stack, int priority, int core, bool detached) {
    (void) detached;
    u32 idle = 0;
    if (!__atomic_compare_exchange_n(&auditfixgR2CreateState, &idle, 1, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) return NULL;
    Thread thread = threadCreate(entry, arg, stack, priority, core, false);
    auditfixgR2Threads[priority == 0x18 ? 0 : 1] = thread;
    __atomic_store_n(&auditfixgR2CreateState, 0, __ATOMIC_RELEASE);
    return thread;
}

static TRACE_R2_CODE void auditfixgR2TraceStop(void) {
    closing = true;
    tracing = false;
    u32 idle = 0;
    // If exit interrupted a create, its not-yet-published stack cannot be
    // joined safely. End the still-mapped process; never race heap teardown.
    if (!__atomic_compare_exchange_n(&auditfixgR2CreateState, &idle, 2, false, __ATOMIC_ACQ_REL, __ATOMIC_ACQUIRE)) svcExitProcess();
    for (unsigned i = 0; i < 2; ++i) {
        Thread thread = auditfixgR2Threads[i];
        if (thread == NULL) continue;
        // Shutdown signals the sticky event before joining. Retain the finite
        // four-second scheduling/failure deadline; a fatal exit never joins.
        // Any nonzero result (including libctru's positive timeout result)
        // ends the process while its heap is mapped. Never free a live thread
        // or return to heap teardown after a failed join.
        if (threadJoin(thread, 4000000000ULL) != 0) svcExitProcess();
        threadFree(thread);
        auditfixgR2Threads[i] = NULL;
    }
}

// Cover _exit callers as well as main's normal/error-screen stops. The exit
// owner reaches this adapter before libctru can unmap either worker's stack.
// Only that owner joins/frees handles. Main's earlier stop only signals them,
// so an error-exit thread cannot race main through two joins or two frees.
void __real__exit(int status) __attribute__((noreturn));
TRACE_R2_CODE __attribute__((noreturn)) void CtrAptTrace_exit(int status) {
    auditfixgF2Exit(status);
}

// A named alias lets the appended TU reach the unchanged owner-only join body.
// No old definition moves; the alias occupies the same late address and bytes.
__asm__(".global auditfixgF2Join\n.set auditfixgF2Join, auditfixgR2TraceStop\n");
// Retain the old 20 B exit adapter's slot after its new noreturn redirect.
// Hard section limit: 300 B, with 12 B slack after the current 288 B of code;
// growth beyond that slack fails assembly rather than moving frozen inputs.
#if defined(__3DS__) && defined(NDEBUG)
__asm__(".pushsection .auditfixg_r2_heartbeat_text,\"ax\",%progbits\n.subsection 1\n.org 300, 0\n.popsection\n");
#endif
#endif // ENABLE_WAD16: shared fixes await DELTARUNE qualification.
