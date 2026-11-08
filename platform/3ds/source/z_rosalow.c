// UT-001 on Old models (change rosaport; UNDERTALE Old only). Closing Rosalina's menu with B can stall or freeze the
// console. The cause on maintainer's o3DS, on Luma 13.5: on that close, Rosalina spins with no sleep at menu.c:600 until HID
// reports B up, and with the app's core 1 time limit at 50% or more, the limiter leaves HID's own threads almost no time
// while it spins (rosamech.md: limit 25 and a one-line fix to that loop, PR 2305, both end it). This is the bridge for
// players on a Luma without that fix.
//
// So the limit goes down to 25 while the player's buttons are forming Rosalina's combo, and if that lands before Rosalina's
// lock stops this app, it stays down by itself for the whole menu, since nothing here runs while the app is stopped. This
// reduces the stall; it doesn't remove it. Its first pass after a pause puts the limit back, as does 100 ms with the combo
// no longer forming, 400 ms after the last new press of a combo button, or the budget below, whichever comes first.
// Rosalina locks the app right after it sees the whole combo, and the whole combo's last press is a new press, so the cap
// can't end a lowering Rosalina still needs unless it takes over 400 ms to act.
//
// No play may pay for this, so with SELECT up, buttons can hold the limit low for about 1 s in any 5 s and no more, whatever
// the pattern (ctr_rosalow.h). What that gives up: a partial chord pressed again and again without SELECT stops giving early
// warning, and a custom combo without SELECT can open with its budget gone and no lowering. The default combo always has
// SELECT's own press: if that's the last button, the limit drops at it, with no warning before it.
//
// The watcher wakes when HID publishes (the PAD0 event, about 234 times a second) instead of every 5 ms. Rosalina reads
// the same shared memory every 50 ms, so it can't see buttons before they are published; this is ahead of it unless its
// sleep ends between HID's publish and the limit call below, or the watcher isn't scheduled in time. That is a race,
// smaller than a poll's, not a guarantee, and its size is only partly measured. A lost
// race leaves that one menu as it is today.
//
// When the watcher stops, at an exit or for a crash screen (CtrRosalina_quiet), its thread puts the limit back before it
// ends. Every limit call is on that thread, so none can be in flight behind it, and the crashing thread makes no call. The
// restores all depend on this thread getting to run and the call working: a crash screen waits for it 100 ms, as ever.
//
// The limit is set by svcSetResourceLimitValues on this process's own limit object, the call and object Luma's PM uses
// for APT_SetAppCpuTimeLimit (reslimit.c, setAppCpuTimeLimit; launch.c gives the process g_manager.reslimits[0]). No IPC,
// no APT lock, no session: libctru's APT call opens a session through srv: first, and a lock before its send means it is
// never sent, whereas a thread inside an SVC finishes it and stops on the way out (k11_extension svc.c). A .3dsx may make
// this SVC: hbldr.c gives it 0 to 0x7F. A .cia's exheader doesn't list it, and the kernel would end the process, so a
// .cia (envIsHomebrew false), or a console whose SVC returns a failure, takes the APT call.
//
// `low` and the base it found are this file's own truth: nothing here asks APT what the limit is. The value is never 0:
// reslimit.c calls that undefined while 1..89 is running, and at 25 or below there is nothing to lower.
//
// ctr_rosalina.c keeps every instruction and ctr_input.c isn't touched: the ways in are CMakeLists.txt's rename of
// z_rosabl.c's sleep and --wrap of the session's input start. All late code and statics (late_reserve.ld). Release builds
// log nothing. Test only: CTRPORT_ROSALINA_PROBE (build.sh rosaprobe) logs each lowering, raise and open with its class;
// CTRPORT_ROSALOW_ARM (build.sh rosalow=arm) takes the wake and the lowering from a byte a copy of the .3dsx can change
// (tools/analysis/rosalow_arm.py); CTRPORT_ROSALOW_SCRIPT (rosalow=script, Azahar only) adds buttons and pauses from
// rosalow.txt.

#include <3ds.h>

#include "ctr_input_map.h"
#include "ctr_rosalow.h"

#if defined(CTRPORT_ROSALOW_SCRIPT)
#include <stdio.h>
#endif
#if defined(CTRPORT_ROSALINA_PROBE) || defined(CTRPORT_ROSALOW_ARM)
#include "ctr_log.h"
#include "log.h"
#endif

#define LOW_CODE __attribute__((noinline, section(".text_rosalow")))
#define LOW_BSS __attribute__((section(".bss.rosalow_late")))

#define ROSALOW_PERCENT 25
#define ROSALOW_TICKS_PER_MS ((u64) SYSCLOCK_ARM11 / 1000)
#define ROSALOW_PAUSE_TICKS (250 * ROSALOW_TICKS_PER_MS) // the watcher runs at least every 20 ms; ctr_rosalina.c's own test
#define ROSALOW_DEFAULT_COMBO (KEY_L | KEY_DDOWN | KEY_SELECT)
_Static_assert(KEY_SELECT == CTR_ROSALOW_SELECT, "ctr_rosalow.h's SELECT");
#define ROSALOW_WAIT_NS (20 * 1000 * 1000LL) // HID stopped (sleep): the watcher still looks at its exit flag

extern Handle hidEvents[5]; // libctru's hid.c; no header has it

enum { WAKE_OFF, WAKE_POLL, WAKE_EVENT, WAKE_EVENT_CORE0 };

#ifdef CTRPORT_ROSALOW_ARM
// One hex digit, patched in copies. Bits 0-1: the wake above. Bit 2: lower. 0 is no lowering watcher at all.
static const volatile char lowArmText[] = "ROSALOW_ARM=6";
static u32 lowArm LOW_BSS;
#define LOW_WAKE (lowArm & 3)
#define LOW_LOWERS ((lowArm & 4) != 0)
#else
#define LOW_WAKE WAKE_EVENT
#define LOW_LOWERS true
#endif

#ifdef CTRPORT_ROSALOW_SCRIPT
static u32 lowQuietMs LOW_BSS, lowCapMs LOW_BSS;
#define ROSALOW_QUIET_TICKS (lowQuietMs * ROSALOW_TICKS_PER_MS)
#define ROSALOW_CAP_TICKS (lowCapMs * ROSALOW_TICKS_PER_MS)
#else
#define ROSALOW_QUIET_TICKS (100 * ROSALOW_TICKS_PER_MS)
#define ROSALOW_CAP_TICKS (400 * ROSALOW_TICKS_PER_MS)
#endif
#define ROSALOW_BUDGET_TICKS (600 * ROSALOW_TICKS_PER_MS)
#define ROSALOW_REARM_TICKS (100 * ROSALOW_TICKS_PER_MS)

static Handle lowLimit LOW_BSS; // this process's limit object, or 1 on the APT call; set means the lowering is on
static bool lowViaApt LOW_BSS;  // the APT call: a .cia, or the SVC failed
static u32 lowCombo LOW_BSS;
static u64 lowLast LOW_BSS;     // this watcher pass's time, kept across a limit call so that a pause inside it counts
static s64 lowBase LOW_BSS;     // the limit a lowering found, and puts back
static CtrRosalowState lowState LOW_BSS;

void CtrRosalina_startAll(void); // ctr_rosalina.c's end: starts the watcher if the bottom backlight hasn't yet
void CtrRosalina_guardSleep(s64 ns);

#ifdef __arm__
// svcSetResourceLimitValues itself: libctru's stub isn't in the build yet, and would be new in early text and move all
// that follows it by 8 B.
Result CtrRosalow_setValues(Handle limit, const ResourceLimitType* names, const s64* values, s32 count);
// svcWaitSynchronization, then CtrRosalina_guardSleep's check that this thread's stack is still mapped read-write: an
// exceptional exit can free the heap it lives on while it waits. The stack isn't touched until that check has passed.
Result CtrRosalow_guardWait(Handle event, s64 ns);
__attribute__((used, section(".bss.rosalow_late"))) u32 CtrRosalow_guardSave[3];
__asm__(
    ".section .text_rosalow,\"ax\",%progbits\n.arm\n.align 2\n"
    ".global CtrRosalow_setValues\n.type CtrRosalow_setValues, %function\n"
    "CtrRosalow_setValues:\n"
    "svc 0x79\nbx lr\n"
    ".size CtrRosalow_setValues, . - CtrRosalow_setValues\n"
    ".global CtrRosalow_guardWait\n.type CtrRosalow_guardWait, %function\n"
    "CtrRosalow_guardWait:\n"
    "svc 0x24\nldr r12, =CtrRosalow_guardSave\nstr r0, [r12, #8]\nstm r12, {r4,r5}\n"
    "mov r2, sp\nsvc 0x02\nldr r12, =CtrRosalow_guardSave\nldm r12, {r4,r5}\n"
    "cmp r0, #0\nbne 2f\nand r3, r3, #3\ncmp r3, #3\nbne 1f\n"
    "2: ldr r0, [r12, #8]\nbx lr\n"
    "1: mvn r0, #0\nmvn r1, #0x80000000\nsvc 0x0a\nb 1b\n.ltorg\n"
    ".size CtrRosalow_guardWait, . - CtrRosalow_guardWait\n.previous\n");
#else
#define CtrRosalow_setValues svcSetResourceLimitValues
#define CtrRosalow_guardWait svcWaitSynchronization
#endif

#ifdef CTRPORT_ROSALOW_SCRIPT
static u32 scriptOn LOW_BSS, scriptOff LOW_BSS, scriptAt LOW_BSS, scriptPauseAt LOW_BSS, scriptPauseMs LOW_BSS;
static u32 scriptSelect LOW_BSS; // 0: two game buttons, on the budget; else with SELECT, off it
static u64 scriptStart LOW_BSS;
static bool scriptPaused LOW_BSS;
#endif

static LOW_CODE Result lowRead(s64* value) {
    if (lowViaApt) {
        u32 percent = 0;
        Result res = APT_GetAppCpuTimeLimit(&percent);
        *value = percent;
        return res;
    }
    ResourceLimitType name = RESLIMIT_CPUTIME;
    return svcGetResourceLimitLimitValues(value, lowLimit, &name, 1);
}

static LOW_CODE Result lowWrite(s64 value) {
    if (!LOW_LOWERS) return 0;
    if (lowViaApt) return APT_SetAppCpuTimeLimit((u32) value);
    ResourceLimitType name = RESLIMIT_CPUTIME;
    Result res = CtrRosalow_setValues(lowLimit, &name, &value, 1);
    if (R_FAILED(res)) lowViaApt = true; // the next try goes through APT
    return res;
}

#ifdef CTRPORT_ROSALINA_PROBE
static u64 lowFormAt LOW_BSS, lowDoneAt LOW_BSS, lowCallTicks LOW_BSS;
static u32 lowOpens[3] LOW_BSS; // lowered, in flight, beaten
static u32 lowLowers LOW_BSS;
#define LOW_US(ticks) ((unsigned long) ((ticks) * 1000000 / SYSCLOCK_ARM11))
#define LOW_MS(ticks) ((unsigned long) ((ticks) / ROSALOW_TICKS_PER_MS))
// The line goes to the card before Rosalina can open, so a console that freezes after a lowering leaves it in the log. A
// freeze with no such line is an open that beat the watcher.
static const char lowLowerText[] =
    "Rosalow: lower from %ld, held %03lX, publish to wake about %ld us, call %lu us, res %08lX, reads %ld\n";
static const char lowRaiseText[] = "Rosalow: raise (%s) to %ld after %lu ms low, held %03lX, call %lu us, res %08lX\n";
static const char lowOpenText[] =
    "Rosalow: open %s, paused %lu ms, limit landed %lu ms before, call %lu us, forming seen %ld ms before, "
    "held %03lX then %03lX now; opens %lu lowered, %lu in flight, %lu beaten; lowerings %lu\n";
static const char lowStartText[] =
    "Rosalow: on, combo %03lX, wake %lu, lowers %d, apt %d, limit %ld read, %lu by APT, res %08lX %08lX\n";
static const char lowOffText[] = "Rosalow: off, res %08lX, homebrew %d\n";
static const char lowQuietText[] = "quiet";
static const char lowCapText[] = "cap";
static const char lowBudgetText[] = "budget";
static const char lowResumeText[] = "resume";

// A pause seen at this pass: the class of that open, read before the raise. In flight: the pause fell inside the limit
// call. Beaten: no lowering was on, which HOME and a closed lid also are; the held buttons tell them apart. The limit
// landed that long before the last pass this watcher ran, so before the lock by that much and up to one wake more.
static LOW_CODE void lowLogOpen(u64 now, u64 last, bool low, u32 before, u32 part) {
    static const char* const names[3] = {"lowered", "in flight", "beaten"};
    int kind = !low ? 2 : lowCallTicks >= ROSALOW_PAUSE_TICKS ? 1 : 0;
    lowOpens[kind]++;
    u64 lead = low && kind == 0 ? last - lowDoneAt : 0;
    logInfo(lowOpenText, names[kind], LOW_MS(now - last), LOW_MS(lead), LOW_US(lowCallTicks),
            lowFormAt != 0 ? (long) LOW_MS(last - lowFormAt) : -1L, (unsigned long) before, (unsigned long) part,
            (unsigned long) lowOpens[0], (unsigned long) lowOpens[1], (unsigned long) lowOpens[2], (unsigned long) lowLowers);
}

// HID's own time for its entry 0, and this wake's entry: HID publishes about every 4.27 ms, so the entry's time is that
// many after entry 0's. An estimate; lumarepro6 measured the spread on entry 0 itself.
static LOW_CODE long lowPublishLate(u64 now) {
    if (LOW_WAKE < WAKE_EVENT) return -1;
    vu32* shared = hidSharedMem;
    u32 index = shared[4];
    u64 zero = (u64) shared[0] | ((u64) shared[1] << 32);
    u64 at = zero + (u64) index * SYSCLOCK_ARM11 / 234;
    return now >= at && 100 * ROSALOW_TICKS_PER_MS > now - at ? (long) LOW_US(now - at) : -1;
}
#endif

#ifdef CTRPORT_ROSALOW_ARM
// What a wake costs: wakes, and the time from a wake to the next wait (the watcher's whole pass), every 30 s.
static u32 lowWakes LOW_BSS, lowTimeouts LOW_BSS;
static u64 lowStatsAt LOW_BSS, lowPassAt LOW_BSS, lowBusy LOW_BSS, lowBusyMax LOW_BSS;
static const char lowStatsText[] = "Rosalow: stats, arm %lu, wakes %lu timeouts %lu in %lu ms, pass avg %lu us max %lu us\n";
#define LOW_US_STATS(ticks) ((unsigned long) ((ticks) * 1000000 / SYSCLOCK_ARM11))
#endif

#ifdef CTRPORT_ROSALOW_SCRIPT
// Azahar only: two buttons of the combo for scriptOn ms in every scriptOn + scriptOff, from scriptAt ms; one
// pause of scriptPauseMs at scriptPauseAt ms, as Rosalina's lock would stop the watcher.
static LOW_CODE u32 scriptHeld(u64 now) {
    u32 ms = (u32) ((now - scriptStart) / ROSALOW_TICKS_PER_MS);
    if (scriptPauseMs != 0 && !scriptPaused && ms >= scriptPauseAt) {
        scriptPaused = true;
        svcSleepThread((s64) scriptPauseMs * 1000000);
    }
    u32 pool = scriptSelect != 0 ? lowCombo : lowCombo & ~(u32) KEY_SELECT;
    u32 first = pool & (0u - pool);
    u32 rest = pool & ~first;
    u32 two = first | (rest & (0u - rest));
    return ms >= scriptAt && (ms - scriptAt) % (scriptOn + scriptOff) < scriptOn ? two : 0;
}
#endif

// One look at the buttons, and what it asks of the limit.
static LOW_CODE void lowStep(void) {
    u64 now = svcGetSystemTick();
    u64 last = lowLast;
    bool paused = last != 0 && now - last >= ROSALOW_PAUSE_TICKS;
    lowLast = now;
#ifdef CTRPORT_ROSALOW_SCRIPT
    u32 held = scriptHeld(now);
#else
    vu32* shared = hidSharedMem; // mapped from before the watcher starts until after it is joined
    u32 index = shared[4];
    u32 held = 8 > index ? shared[10 + index * 4] : 0;
#endif
    u32 part = held & lowCombo;
#ifdef CTRPORT_ROSALINA_PROBE
    if (paused) lowLogOpen(now, last, lowState.low, lowState.prev, part);
    if (!CtrRosalow_forming(part, lowCombo)) lowFormAt = 0;
    else if (lowFormAt == 0) lowFormAt = now;
#endif
    CtrRosalowAct act = CtrRosalow_step(&lowState, now, part, lowCombo, paused, ROSALOW_QUIET_TICKS, ROSALOW_CAP_TICKS,
                                        ROSALOW_BUDGET_TICKS, ROSALOW_REARM_TICKS);
    if (act == ROSALOW_NONE) return;
    if (act == ROSALOW_LOWER) {
#ifdef CTRPORT_ROSALINA_PROBE
        long late = lowPublishLate(now);
#endif
        s64 base = 0;
        if (R_FAILED(lowRead(&base)) || base <= ROSALOW_PERCENT) {
            // Nothing to gain, and 0 means no thread of this app is on core 1 at all: not until a new press.
            lowState.low = false;
            lowState.capped = true;
            return;
        }
        lowBase = base;
#ifdef CTRPORT_ROSALINA_PROBE
        u64 t0 = svcGetSystemTick();
#endif
        Result res = lowWrite(ROSALOW_PERCENT);
        if (R_FAILED(res)) lowState.low = false; // again at the next pass
#ifdef CTRPORT_ROSALINA_PROBE
        u64 t1 = svcGetSystemTick();
        lowCallTicks = t1 - t0;
        lowDoneAt = t1;
        lowLowers++;
        s64 now2 = 0;
        lowRead(&now2);
        logInfo(lowLowerText, (long) base, (unsigned long) held, late, LOW_US(lowCallTicks), (unsigned long) res, (long) now2);
        CtrLog_flush();
#endif
        return;
    }
#ifdef CTRPORT_ROSALINA_PROBE
    u64 t0 = svcGetSystemTick();
#endif
    Result res = lowWrite(lowBase);
    if (R_FAILED(res)) lowState.low = true; // again at the next pass: quiet and cap have both run out by then
#ifdef CTRPORT_ROSALINA_PROBE
    u64 t1 = svcGetSystemTick();
    logInfo(lowRaiseText, act == ROSALOW_RAISE_QUIET ? lowQuietText : act == ROSALOW_RAISE_CAP ? lowCapText :
            act == ROSALOW_RAISE_BUDGET ? lowBudgetText : lowResumeText,
            (long) lowBase, LOW_MS(t1 - lowDoneAt), (unsigned long) held, LOW_US(t1 - t0), (unsigned long) res);
    lowCallTicks = 0;
#endif
}

// The watcher's sleep (z_rosabl.c's call, renamed in CMakeLists.txt). Before the session, or with no lowering, the sleep
// as it was. The event is cleared before the buttons are read, so a publish after this read wakes the next wait.
void CtrRosalow_wait(s64 ns);
LOW_CODE void CtrRosalow_wait(s64 ns) {
    if (lowLimit == 0) {
        CtrRosalina_guardSleep(ns);
        return;
    }
#ifdef CTRPORT_ROSALOW_ARM
    u64 enter = svcGetSystemTick();
    if (lowPassAt != 0) {
        u64 pass = enter - lowPassAt;
        lowBusy += pass;
        if (pass > lowBusyMax) lowBusyMax = pass;
    }
#endif
    if (LOW_WAKE >= WAKE_EVENT) {
        Handle event = hidEvents[HIDEVENT_PAD0];
        Result res = CtrRosalow_guardWait(event, ROSALOW_WAIT_NS);
        if (R_SUCCEEDED(res)) svcClearEvent(event);
        else if (R_DESCRIPTION(res) != RD_TIMEOUT) CtrRosalina_guardSleep(ns); // no busy loop on a closed handle
#ifdef CTRPORT_ROSALOW_ARM
        else lowTimeouts++;
#endif
    } else {
        CtrRosalina_guardSleep(ns);
    }
#ifdef CTRPORT_ROSALOW_ARM
    lowWakes++;
    u64 tick = svcGetSystemTick();
    lowPassAt = tick;
    if (lowStatsAt == 0) lowStatsAt = tick;
    if (tick - lowStatsAt >= 30000 * ROSALOW_TICKS_PER_MS) {
        logInfo(lowStatsText, (unsigned long) lowArm, (unsigned long) lowWakes, (unsigned long) lowTimeouts,
                (unsigned long) ((tick - lowStatsAt) / ROSALOW_TICKS_PER_MS), LOW_US_STATS(lowBusy / lowWakes),
                LOW_US_STATS(lowBusyMax));
        lowStatsAt = tick;
        lowWakes = lowTimeouts = 0;
        lowBusy = lowBusyMax = 0;
    }
#endif
    lowStep();
}

extern void (*rosaWatchEntry)(void*); // ctr_rosalina.c: what CtrRosalina_watchRun calls, ahead of its crash-screen light
static void (*lowEntry)(void*) LOW_BSS;

// The watcher's thread, with its passes over: put the limit back, ahead of the crash screen's light.
static LOW_CODE void lowWatch(void* arg) {
    lowEntry(arg);
    if (__atomic_load_n(&lowLimit, __ATOMIC_ACQUIRE) == 0 || !lowState.low) return;
    lowState.low = false;
    if (R_FAILED(lowWrite(lowBase))) lowWrite(lowBase); // the second is through APT: lowWrite has seen to that
}

// The watcher's create: it's the one thread here that isn't detached. rosaWatchEntry is stored just before this call, each
// try. In the core 0 test arms it asks for the game's core, where the watcher's 0x2D is above the game thread's 0x30, so
// each wake takes the core from it.
Thread __real_CtrRosalina_threadCreate(void (*entry)(void*), void* arg, size_t stackBytes, int prio, int core, bool detached);
Thread __wrap_CtrRosalina_threadCreate(void (*entry)(void*), void* arg, size_t stackBytes, int prio, int core, bool detached);
LOW_CODE Thread __wrap_CtrRosalina_threadCreate(void (*entry)(void*), void* arg, size_t stackBytes, int prio, int core,
                                                bool detached) {
    if (!detached && rosaWatchEntry != lowWatch) {
        lowEntry = rosaWatchEntry;
        rosaWatchEntry = lowWatch;
    }
#ifdef CTRPORT_ROSALOW_ARM
    if (LOW_WAKE == WAKE_EVENT_CORE0) core = 0;
#endif
    return __real_CtrRosalina_threadCreate(entry, arg, stackBytes, prio, core, detached);
}

// Every session's start (z_inputlate.c's call): the limit is set by now, every load's texture prepare has given back what
// it borrowed, and a limit read here on is the game's own. A watcher already running for a dark bottom goes on as it is.
bool __real_CtrInput_start(bool isNew3ds, const CtrInputMap* map);
bool __wrap_CtrInput_start(bool isNew3ds, const CtrInputMap* map);
LOW_CODE bool __wrap_CtrInput_start(bool isNew3ds, const CtrInputMap* map) {
    bool started = __real_CtrInput_start(isNew3ds, map);
    s64 info; // read only after a call that succeeded
    if (!started || lowLimit != 0 || isNew3ds || R_FAILED(svcGetSystemInfo(&info, 0x10000, 0))) return started;
#ifdef CTRPORT_ROSALOW_ARM
    {
        u32 arm = (u32) lowArmText[12];
        lowArm = arm - '0';
        if (LOW_WAKE == WAKE_OFF) return started;
    }
#endif
    Handle limit = 1;
    Result got = 0;
    lowViaApt = !envIsHomebrew(); // a .cia may not make these SVCs; Azahar's limiter answers to APT's call
    if (!lowViaApt) got = svcGetResourceLimit(&limit, CUR_PROCESS_HANDLE);
#ifdef CTRPORT_ROSALINA_PROBE
    if (R_FAILED(got)) logInfo(lowOffText, (unsigned long) got, (int) envIsHomebrew());
#endif
    if (R_FAILED(got)) return started;
    u32 combo = ROSALOW_DEFAULT_COMBO;
    if (R_SUCCEEDED(svcGetSystemInfo(&info, 0x10000, 0x101)) && (u32) info != 0) combo = (u32) info;
    lowCombo = combo;
#ifdef CTRPORT_ROSALOW_SCRIPT
    {
        FILE* script = fopen("sdmc:/3ds/undertale-3ds/rosalow.txt", "r");
        unsigned long v[8] = {0, 0, 0, 0, 0, 100, 400, 0};
        if (script != NULL) {
            fscanf(script, "%lu %lu %lu %lu %lu %lu %lu %lu", &v[0], &v[1], &v[2], &v[3], &v[4], &v[5], &v[6], &v[7]);
            fclose(script);
        }
        scriptOn = v[0];
        scriptOff = v[1] != 0 ? v[1] : 1;
        scriptAt = v[2];
        scriptPauseAt = v[3];
        scriptPauseMs = v[4];
        lowQuietMs = v[5];
        lowCapMs = v[6];
        scriptSelect = v[7];
        scriptStart = svcGetSystemTick();
        if (v[0] == 0) scriptAt = 0xFFFFFFFFu; // the control: no presses
    }
#endif
    __atomic_store_n(&lowLimit, limit, __ATOMIC_RELEASE);
#ifdef CTRPORT_ROSALINA_PROBE
    s64 viaSvc = 0;
    u32 viaApt = 0;
    Result r1 = lowRead(&viaSvc);
    Result r2 = APT_GetAppCpuTimeLimit(&viaApt);
    logInfo(lowStartText, (unsigned long) combo, (unsigned long) LOW_WAKE, (int) LOW_LOWERS, (int) lowViaApt, (long) viaSvc,
            (unsigned long) viaApt, (unsigned long) r1, (unsigned long) r2);
#endif
    CtrRosalina_startAll();
    return started;
}
