// change titancpu: the Titan CPU recorder, for diagnosis builds only (build.sh ... titandiag; CMakeLists.txt compiles
// this file and its link wraps only then, so release builds are unchanged). Never a release.
//
// While a bench scene runs, it splits each frame's CPU time by main-loop phase and by what ran in it, and logs the
// slow frames and a summary every 150 bench frames to log.txt:
//
//   [td] f<frame> c<cpu> s<step> d<draw> a<audio> r<room change> p<present> pre<pre> w<wait> pw<us> x<us> rt<n>/<us> g<gpu>
//        t<loads>/<us> q<line> | <name>=<self us>/<calls> ...        (top 8 by self time in this frame)
//   [tdw] f<first>-<last> n<frames> c<avg>/<max> s<avg>/<max> d<avg>/<max> o<avg>/<max> ev<pushes per frame> q<line>
//   [tdw+] <name>=<avg us per frame>/<max us in a frame>/<calls per frame x10> ...   (top 24, 8 to a line)
//
// All times are microseconds of the 268 MHz system tick. <frame> is the game frame the bench's "measured frames A-B"
// line uses (runner->frameCount - 1 at the frame's end). cpu = from the "step" mark to the end of present (Step, Draw,
// the audio update, the room-change call and present); pre = from the bench's frame begin to the "step" mark (input
// and the bench script); wait = from the "wait for frame" mark to the bench's frame begin (CtrRenderer_beginFrame:
// its deferred frees, then the slot wait). rt = C3D_RenderTargetDelete calls and time in the frame (they wait for the
// GPU). pw = the part of wait before the pacer's slot wait (deferred frees and the rest of CtrRenderer_beginFrame's
// start), x = from the slot wait's end to the "step" mark: with cpu, the frame's share of the pacer's "main" busy time
// (less the loop's few lines after present). gpu = the renderer's last finished GPU frame. t = texture page loads and their time (the draw-time loads).
// A frame is logged when its cpu is 18 ms or more, or the scene's slowest so far. q counts the recorder's lines, so
// a gap shows lines the log writer dropped.
//
// Names: "<phase>:<code entry>" without its gml_Object_ / gml_Script_ prefix, for event code (the runner's event runs,
// VM_beginEventRun to VM_endEventRun, calls = instances; and VM_executeCode, nested and single events); "<phase>:<zone>"
// for the runner's profiler zones (<runner: draw> etc., their time less the code they ran); "rtdel" for render
// target deletes; "@<builtin>" for the builtins with a timing shim (see builtin shims). Phases: w (wait and pre), s (step), d (draw), o (audio update, room change, present). Self time:
// each entry's time less what it called that is recorded too. Scripts the code calls (VM_callCodeIndex inside vm.c,
// generated code's direct calls) and builtins count to the calling event.
//
// Cost: two svcGetSystemTick calls per event run, nested event and zone (the [td] start line gives a call's cost, ev
// the count per frame). It runs in titandiag builds only, so compare against the same build's [td] lines or the bench
// result of a build without the word, never mix.

#if defined(CTRPORT_TITANDIAG)

#include <3ds.h>
#include <citro3d.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "ctr_benchmark.h"
#include "ctr_renderer.h"
#include "data_win.h"
#include "log.h"
#include "profiler.h"
#include "runner.h"
#include "vm.h"

#define TD_TEXT __attribute__((noinline, section(".text.titandiag_late")))
#define TD_CONST __attribute__((aligned(4), section(".rodata.titandiag_in_text")))
#define TD_BSS __attribute__((section(".bss.titandiag_late")))

#define TD_SLOTS 1024u // power of two
#define TD_STACK 64
#define TD_WIN 150u
#define TD_FRAME_TOP 8
#define TD_WIN_TOP 24
#define TD_SLOW_TICKS (18u * 268112u) // 18 ms

#define TD_KIND_CODE 0u
#define TD_KIND_ZONE 1u
#define TD_KIND_RTDEL 2u
#define TD_KIND_OVER 3u

typedef struct {
    uint32_t key; // 0: empty
    const char* name;
    uint8_t kind, phase;
    uint32_t fseq, fticks, fcalls;
    uint32_t wseq, wmax, wcalls;
    uint64_t wticks;
} TdEntry;

typedef struct {
    TdEntry* e;
    uint32_t start, child;
} TdFrame;

static TdEntry tdTable[TD_SLOTS] TD_BSS;
static TdFrame tdStack[TD_STACK] TD_BSS;

static struct {
    Runner* runner;
    Renderer* renderer;
    DataWin* dataWin;
    TdEntry over; // the table full
    int depth, lost; // lost: pushes past TD_STACK, popped without a frame
    uint32_t used;
    uint32_t seq, wseq;
    uint8_t phase;
    uint8_t marks; // bit per mark seen this frame
    bool active, haveWin;
    uint32_t tWait, tBegin, tStep, tDraw, tAudio, tRoom, tPresent;
    uint32_t tSlotEnter, tSlotExit; // the pacer wait in CtrRenderer_beginFrame
    uint32_t loadsAtBegin;
    float loadMsAtBegin;
    uint32_t pushes; // this frame
    uint32_t rtCount, rtTicks; // this frame
    uint32_t lines;
    uint32_t sceneMax;
    long lastFrame;
    int32_t lastRoom;
    // window
    long wFirst, wLast;
    uint32_t wFrames, wPushes;
    uint64_t wCpu, wStep, wDraw, wOther;
    uint32_t wCpuMax, wStepMax, wDrawMax, wOtherMax;
} td TD_BSS;

static const char tdPhaseNames[4][2] TD_CONST = { "w", "s", "d", "o" };
static const char tdUnknown[] TD_CONST = "?";
static const char tdRtdel[] TD_CONST = "rtdel";
static const char tdOverName[] TD_CONST = "(table full)";
static const char tdPrefixObject[] TD_CONST = "gml_Object_";
static const char tdPrefixScript[] TD_CONST = "gml_Script_";
static const char tdMarkWait[] TD_CONST = "wait for frame";
static const char tdMarkStep[] TD_CONST = "step";
static const char tdMarkDraw[] TD_CONST = "draw";
static const char tdMarkAudio[] TD_CONST = "audio update";
static const char tdMarkRoom[] TD_CONST = "room change";
static const char tdMarkPresent[] TD_CONST = "present";
static const char tdFmtStart[] TD_CONST = "[td] start: tick call %lu ns, slots %lu, window %lu frames\n";
static const char tdFmtFrame[] TD_CONST =
    "[td] f%ld c%lu s%lu d%lu a%lu r%lu p%lu pre%lu w%lu pw%lu x%lu rt%lu/%lu g%lu t%lu/%lu q%lu |";
static const char tdFmtWin[] TD_CONST =
    "[tdw] f%ld-%ld n%lu c%lu/%lu s%lu/%lu d%lu/%lu o%lu/%lu ev%lu q%lu\n";
static const char tdFmtWinPlus[] TD_CONST = "[tdw+]";
static const char tdFmtItem[] TD_CONST = " %s:%s=%lu/%lu";
static const char tdFmtItem3[] TD_CONST = " %s:%s=%lu/%lu/%lu";
static const char tdFmtLine[] TD_CONST = "%s\n";

void __real_CtrWatchdog_mark(const char* phase);
void __real_CtrBench_sessionStartedLate(const CtrBenchSession* session);
CtrBenchFrame __real_CtrBench_beginFrameTimed(u32 down, double frameMs);
void __real_CtrBench_endFrameTimed(double stepMs, double drawMs, bool skipped);
void __real_Profiler_enterKind(Profiler* p, const char* name, ProfilerKind kind);
void __real_Profiler_exit(Profiler* p);
void __real_VM_beginEventRun(VMContext* ctx, VMEventRun* run, int32_t codeIndex, int32_t eventType, int32_t eventSubtype, int32_t ownerObjectIndex);
void __real_VM_endEventRun(VMContext* ctx, VMEventRun* run);
void __real_VM_runEvent(VMContext* ctx, VMEventRun* run, struct Instance* instance);
RValue __real_VM_executeCode(VMContext* ctx, int32_t codeIndex);
bool __real_CtrPacer_waitForSlot(bool catchUp, int32_t skipMax);
bool __real_CtrPacer_levelWait(bool mayskip);
void __real_C3D_RenderTargetDelete(C3D_RenderTarget* target);

static inline uint32_t tdNow(void) {
    return (uint32_t) svcGetSystemTick();
}

static inline uint32_t tdUs(uint64_t ticks) {
    return (uint32_t) ((ticks * 1000000ull) / 268111856ull);
}

TD_TEXT static void tdClear(void) {
    memset(tdTable, 0, sizeof tdTable);
    memset(&td.over, 0, sizeof td.over);
    td.over.name = tdOverName;
    td.over.kind = TD_KIND_OVER;
    td.used = 0;
    td.depth = 0;
    td.lost = 0;
    td.haveWin = false;
}

TD_TEXT static TdEntry* tdFind(uint32_t kind, uint32_t id, const char* name) {
    uint32_t phase = td.phase;
    uint32_t key = 0x80000000u | (kind << 29) | (phase << 26) | (id & 0x03FFFFFFu);
    uint32_t h = (key * 2654435761u) >> 22; // 10 bits
    for (uint32_t i = 0; TD_SLOTS > i; i++) {
        TdEntry* e = &tdTable[(h + i) & (TD_SLOTS - 1u)];
        if (e->key == key) return e;
        if (e->key == 0) {
            if (td.used >= TD_SLOTS - TD_SLOTS / 8u) return &td.over;
            td.used++;
            e->key = key;
            e->name = name;
            e->kind = (uint8_t) kind;
            e->phase = (uint8_t) phase;
            return e;
        }
    }
    return &td.over;
}

// Entries hold one frame's and one window's times only, so the table empties at each window's end (and when a test
// starts) to keep room: the current frame's entries stay, the rest go (a chapter's load and the scene's room change
// run hundreds of entries once). Only with nothing on the stack, which holds entry pointers.
#define TD_KEEP 160
static TdEntry tdKeep[TD_KEEP] TD_BSS;

TD_TEXT static void tdCompact(void) {
    if (td.depth != 0 || td.lost != 0) return;
    uint32_t n = 0;
    for (uint32_t i = 0; TD_SLOTS > i && TD_KEEP > n; i++) {
        if (tdTable[i].key != 0 && tdTable[i].fseq == td.seq) tdKeep[n++] = tdTable[i];
    }
    memset(tdTable, 0, sizeof tdTable);
    td.used = 0;
    if (td.over.fseq != td.seq) {
        memset(&td.over, 0, sizeof td.over);
        td.over.name = tdOverName;
        td.over.kind = TD_KIND_OVER;
    }
    for (uint32_t k = 0; n > k; k++) {
        uint32_t h = (tdKeep[k].key * 2654435761u) >> 22;
        for (uint32_t i = 0; TD_SLOTS > i; i++) {
            TdEntry* e = &tdTable[(h + i) & (TD_SLOTS - 1u)];
            if (e->key == 0) {
                *e = tdKeep[k];
                td.used++;
                break;
            }
        }
    }
}

static inline void tdPush(TdEntry* e, uint32_t now) {
    td.pushes++;
    if (td.depth >= TD_STACK) {
        td.lost++;
        return;
    }
    TdFrame* f = &tdStack[td.depth++];
    f->e = e;
    f->start = now;
    f->child = 0;
}

static inline void tdCredit(TdEntry* e, uint32_t self, uint32_t calls) {
    if (e->fseq != td.seq) {
        e->fseq = td.seq;
        e->fticks = 0;
        e->fcalls = 0;
    }
    e->fticks += self;
    e->fcalls += calls;
}

// kind: the kind the top frame must have (a zone exit pops only a zone); 0xFF any.
TD_TEXT static void tdPop(uint32_t now, uint32_t kind) {
    if (td.lost > 0) {
        td.lost--;
        return;
    }
    if (td.depth <= 0) return;
    TdFrame* f = &tdStack[td.depth - 1];
    if (kind != 0xFFu && f->e->kind != kind && !(f->e->kind == TD_KIND_OVER)) return;
    td.depth--;
    uint32_t d = now - f->start;
    uint32_t self = d > f->child ? d - f->child : 0;
    tdCredit(f->e, self, f->e->kind == TD_KIND_CODE ? 0u : 1u);
    if (td.depth > 0) tdStack[td.depth - 1].child += d;
}

static inline void tdCheckDataWin(VMContext* ctx) {
    if (ctx->dataWin != td.dataWin) {
        td.dataWin = ctx->dataWin;
        tdClear();
    }
}

TD_TEXT static const char* tdCodeName(VMContext* ctx, int32_t codeIndex) {
    if (ctx->dataWin == NULL || 0 > codeIndex || (uint32_t) codeIndex >= ctx->dataWin->code.count) return tdUnknown;
    const char* n = ctx->dataWin->code.entries[codeIndex].name;
    return n != NULL ? n : tdUnknown;
}

TD_TEXT static const char* tdShort(const char* n) {
    if (strncmp(n, tdPrefixObject, 11) == 0 || strncmp(n, tdPrefixScript, 11) == 0) return n + 11;
    return n;
}

// ===[ builtin shims ]===

// The builtins below get a timing shim in the VM's function call cache (funcCallCache[i].builtin), the pointer the
// interpreter, aotCallBuiltin and the typed AOT regions all call through. Their entries ("@<name>") take their time
// out of the calling event's self time; each call's time includes about one tick call (the [td] start line).
#define TD_BI_COUNT 32
static const char tdBiName0[] TD_CONST = "@draw_surface_part";
static const char tdBiName1[] TD_CONST = "@surface_set_target";
static const char tdBiName2[] TD_CONST = "@surface_reset_target";
static const char tdBiName3[] TD_CONST = "@draw_clear_alpha";
static const char tdBiName4[] TD_CONST = "@draw_sprite_ext";
static const char tdBiName5[] TD_CONST = "@draw_sprite";
static const char tdBiName6[] TD_CONST = "@surface_exists";
static const char tdBiName7[] TD_CONST = "@surface_create";
static const char tdBiName8[] TD_CONST = "@surface_free";
static const char tdBiName9[] TD_CONST = "@draw_surface_ext";
static const char tdBiName10[] TD_CONST = "@draw_surface";
static const char tdBiName11[] TD_CONST = "@draw_sprite_part_ext";
static const char tdBiName12[] TD_CONST = "@draw_sprite_part";
static const char tdBiName13[] TD_CONST = "@draw_set_alpha";
static const char tdBiName14[] TD_CONST = "@draw_set_color";
static const char tdBiName15[] TD_CONST = "@draw_rectangle";
static const char tdBiName16[] TD_CONST = "@draw_self";
static const char tdBiName17[] TD_CONST = "@draw_text";
static const char tdBiName18[] TD_CONST = "@draw_line_width";
static const char tdBiName19[] TD_CONST = "@gpu_set_blendmode";
static const char tdBiName20[] TD_CONST = "@gpu_set_fog";
static const char tdBiName21[] TD_CONST = "@shader_set";
static const char tdBiName22[] TD_CONST = "@shader_reset";
static const char tdBiName23[] TD_CONST = "@instance_create";
static const char tdBiName24[] TD_CONST = "@instance_create_depth";
static const char tdBiName25[] TD_CONST = "@instance_destroy";
static const char tdBiName26[] TD_CONST = "@instance_exists";
static const char tdBiName27[] TD_CONST = "@path_add_point";
static const char tdBiName28[] TD_CONST = "@layer_sprite_y";
static const char tdBiName29[] TD_CONST = "@point_distance";
static const char tdBiName30[] TD_CONST = "@layer_get_x";
static const char tdBiName31[] TD_CONST = "@layer_get_y";
static const char* const tdBiNames[TD_BI_COUNT] TD_CONST = {
    tdBiName0, tdBiName1, tdBiName2, tdBiName3, tdBiName4, tdBiName5, tdBiName6, tdBiName7, tdBiName8, tdBiName9, tdBiName10, tdBiName11, tdBiName12, tdBiName13, tdBiName14, tdBiName15, tdBiName16, tdBiName17, tdBiName18, tdBiName19, tdBiName20, tdBiName21, tdBiName22, tdBiName23, tdBiName24, tdBiName25, tdBiName26, tdBiName27, tdBiName28, tdBiName29, tdBiName30, tdBiName31,
};
static BuiltinFunc tdBiOrig[TD_BI_COUNT] TD_BSS;
static VMContext* tdBiCtx TD_BSS;

static inline RValue tdBiCall(int n, VMContext* ctx, RValue* args, int32_t argCount) {
    TdEntry* e = tdFind(TD_KIND_RTDEL, 1u + (uint32_t) n, tdBiNames[n]);
    tdPush(e, tdNow());
    RValue r = tdBiOrig[n](ctx, args, argCount);
    tdPop(tdNow(), TD_KIND_RTDEL);
    return r;
}

TD_TEXT static RValue tdBi0(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(0, ctx, args, argCount); }
TD_TEXT static RValue tdBi1(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(1, ctx, args, argCount); }
TD_TEXT static RValue tdBi2(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(2, ctx, args, argCount); }
TD_TEXT static RValue tdBi3(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(3, ctx, args, argCount); }
TD_TEXT static RValue tdBi4(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(4, ctx, args, argCount); }
TD_TEXT static RValue tdBi5(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(5, ctx, args, argCount); }
TD_TEXT static RValue tdBi6(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(6, ctx, args, argCount); }
TD_TEXT static RValue tdBi7(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(7, ctx, args, argCount); }
TD_TEXT static RValue tdBi8(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(8, ctx, args, argCount); }
TD_TEXT static RValue tdBi9(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(9, ctx, args, argCount); }
TD_TEXT static RValue tdBi10(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(10, ctx, args, argCount); }
TD_TEXT static RValue tdBi11(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(11, ctx, args, argCount); }
TD_TEXT static RValue tdBi12(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(12, ctx, args, argCount); }
TD_TEXT static RValue tdBi13(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(13, ctx, args, argCount); }
TD_TEXT static RValue tdBi14(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(14, ctx, args, argCount); }
TD_TEXT static RValue tdBi15(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(15, ctx, args, argCount); }
TD_TEXT static RValue tdBi16(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(16, ctx, args, argCount); }
TD_TEXT static RValue tdBi17(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(17, ctx, args, argCount); }
TD_TEXT static RValue tdBi18(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(18, ctx, args, argCount); }
TD_TEXT static RValue tdBi19(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(19, ctx, args, argCount); }
TD_TEXT static RValue tdBi20(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(20, ctx, args, argCount); }
TD_TEXT static RValue tdBi21(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(21, ctx, args, argCount); }
TD_TEXT static RValue tdBi22(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(22, ctx, args, argCount); }
TD_TEXT static RValue tdBi23(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(23, ctx, args, argCount); }
TD_TEXT static RValue tdBi24(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(24, ctx, args, argCount); }
TD_TEXT static RValue tdBi25(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(25, ctx, args, argCount); }
TD_TEXT static RValue tdBi26(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(26, ctx, args, argCount); }
TD_TEXT static RValue tdBi27(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(27, ctx, args, argCount); }
TD_TEXT static RValue tdBi28(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(28, ctx, args, argCount); }
TD_TEXT static RValue tdBi29(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(29, ctx, args, argCount); }
TD_TEXT static RValue tdBi30(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(30, ctx, args, argCount); }
TD_TEXT static RValue tdBi31(VMContext* ctx, RValue* args, int32_t argCount) { return tdBiCall(31, ctx, args, argCount); }
static const BuiltinFunc tdBiShims[TD_BI_COUNT] TD_CONST = {
    tdBi0, tdBi1, tdBi2, tdBi3, tdBi4, tdBi5, tdBi6, tdBi7, tdBi8, tdBi9, tdBi10, tdBi11, tdBi12, tdBi13, tdBi14, tdBi15, tdBi16, tdBi17, tdBi18, tdBi19, tdBi20, tdBi21, tdBi22, tdBi23, tdBi24, tdBi25, tdBi26, tdBi27, tdBi28, tdBi29, tdBi30, tdBi31,
};

// Once per VM context (each chapter makes its own).
TD_TEXT static void tdBiInstall(VMContext* ctx) {
    tdBiCtx = ctx;
    if (ctx->funcCallCache == NULL || ctx->dataWin == NULL) return;
    uint32_t count = ctx->funcCallCacheCount;
    if (count > ctx->dataWin->func.functionCount) count = ctx->dataWin->func.functionCount;
    for (uint32_t i = 0; count > i; i++) {
        const char* name = ctx->dataWin->func.functions[i].name;
        void* b = ctx->funcCallCache[i].builtin;
        if (name == NULL || b == NULL) continue;
        for (int n = 0; TD_BI_COUNT > n; n++) {
            if (strcmp(name, tdBiNames[n] + 1) != 0) continue;
            if (b != (void*) tdBiShims[n]) {
                tdBiOrig[n] = (BuiltinFunc) b;
                ctx->funcCallCache[i].builtin = (void*) tdBiShims[n];
            }
            break;
        }
    }
}

static inline void tdBiCheck(VMContext* ctx) {
    if (ctx != tdBiCtx) tdBiInstall(ctx);
}

// ===[ wraps: the VM and the runner ]===

TD_TEXT void __wrap_VM_beginEventRun(VMContext* ctx, VMEventRun* run, int32_t codeIndex, int32_t eventType, int32_t eventSubtype, int32_t ownerObjectIndex) {
    __real_VM_beginEventRun(ctx, run, codeIndex, eventType, eventSubtype, ownerObjectIndex);
    tdCheckDataWin(ctx);
    tdBiCheck(ctx);
    tdPush(tdFind(TD_KIND_CODE, (uint32_t) codeIndex, tdCodeName(ctx, codeIndex)), tdNow());
}

TD_TEXT void __wrap_VM_endEventRun(VMContext* ctx, VMEventRun* run) {
    tdPop(tdNow(), TD_KIND_CODE);
    __real_VM_endEventRun(ctx, run);
}

TD_TEXT void __wrap_VM_runEvent(VMContext* ctx, VMEventRun* run, struct Instance* instance) {
    if (td.depth > 0 && td.lost == 0) {
        TdEntry* e = tdStack[td.depth - 1].e;
        if (e->fseq != td.seq) {
            e->fseq = td.seq;
            e->fticks = 0;
            e->fcalls = 0;
        }
        e->fcalls++;
    }
    __real_VM_runEvent(ctx, run, instance);
}

TD_TEXT RValue __wrap_VM_executeCode(VMContext* ctx, int32_t codeIndex) {
    tdCheckDataWin(ctx);
    tdBiCheck(ctx);
    TdEntry* e = tdFind(TD_KIND_CODE, (uint32_t) codeIndex, tdCodeName(ctx, codeIndex));
    tdPush(e, tdNow());
    tdCredit(e, 0, 1);
    RValue result = __real_VM_executeCode(ctx, codeIndex);
    tdPop(tdNow(), TD_KIND_CODE);
    return result;
}

TD_TEXT void __wrap_Profiler_enterKind(Profiler* p, const char* name, ProfilerKind kind) {
    __real_Profiler_enterKind(p, name, kind);
    tdPush(tdFind(TD_KIND_ZONE, (uint32_t) (uintptr_t) name, name), tdNow());
}

TD_TEXT void __wrap_Profiler_exit(Profiler* p) {
    tdPop(tdNow(), TD_KIND_ZONE);
    __real_Profiler_exit(p);
}

TD_TEXT void __wrap_C3D_RenderTargetDelete(C3D_RenderTarget* target) {
    uint32_t start = tdNow();
    TdEntry* e = tdFind(TD_KIND_RTDEL, 0, tdRtdel);
    tdPush(e, start);
    __real_C3D_RenderTargetDelete(target);
    uint32_t now = tdNow();
    tdPop(now, TD_KIND_RTDEL);
    td.rtCount++;
    td.rtTicks += now - start;
}

TD_TEXT bool __wrap_CtrPacer_waitForSlot(bool catchUp, int32_t skipMax) {
    td.tSlotEnter = tdNow();
    td.marks |= 0x80u;
    bool r = __real_CtrPacer_waitForSlot(catchUp, skipMax);
    td.tSlotExit = tdNow();
    return r;
}

TD_TEXT bool __wrap_CtrPacer_levelWait(bool mayskip) {
    td.tSlotEnter = tdNow();
    td.marks |= 0x80u;
    bool r = __real_CtrPacer_levelWait(mayskip);
    td.tSlotExit = tdNow();
    return r;
}

// ===[ output ]===

TD_TEXT static void tdEmit(const char* text) {
    logInfo(tdFmtLine, text);
}

// The n entries with the most ticks (frame or window), in order.
TD_TEXT static int tdTop(TdEntry** out, int n, bool window) {
    int count = 0;
    for (uint32_t i = 0; TD_SLOTS + 1u > i; i++) {
        TdEntry* e = i < TD_SLOTS ? &tdTable[i] : &td.over;
        if (i < TD_SLOTS && e->key == 0) continue;
        uint64_t v;
        if (window) {
            if (e->wseq != td.wseq) continue;
            v = e->wticks;
        } else {
            if (e->fseq != td.seq) continue;
            v = e->fticks;
        }
        if (v == 0) continue;
        int at = count;
        while (at > 0) {
            TdEntry* o = out[at - 1];
            uint64_t ov = window ? o->wticks : o->fticks;
            if (ov >= v) break;
            if (at < n) out[at] = o;
            at--;
        }
        if (at < n) {
            out[at] = e;
            if (count < n) count++;
        }
    }
    return count;
}

TD_TEXT static void tdWindowFlush(void) {
    if (!td.haveWin || td.wFrames == 0) {
        td.haveWin = false;
        tdCompact();
        return;
    }
    char line[960];
    uint32_t n = td.wFrames;
    snprintf(line, sizeof line, tdFmtWin, td.wFirst, td.wLast, (unsigned long) n, (unsigned long) tdUs(td.wCpu / n),
             (unsigned long) tdUs(td.wCpuMax), (unsigned long) tdUs(td.wStep / n), (unsigned long) tdUs(td.wStepMax),
             (unsigned long) tdUs(td.wDraw / n), (unsigned long) tdUs(td.wDrawMax), (unsigned long) tdUs(td.wOther / n),
             (unsigned long) tdUs(td.wOtherMax), (unsigned long) (td.wPushes / n), (unsigned long) ++td.lines);
    size_t len = strlen(line);
    if (len > 0) line[len - 1] = '\0';
    tdEmit(line);
    TdEntry* top[TD_WIN_TOP];
    int count = tdTop(top, TD_WIN_TOP, true);
    for (int i = 0; count > i; i += 8) {
        int used = snprintf(line, sizeof line, "%s", tdFmtWinPlus);
        for (int j = i; count > j && i + 8 > j && used < (int) sizeof line - 1; j++) {
            TdEntry* e = top[j];
            used += snprintf(line + used, sizeof line - (size_t) used, tdFmtItem3, tdPhaseNames[e->phase & 3u], tdShort(e->name),
                             (unsigned long) tdUs(e->wticks / n), (unsigned long) tdUs(e->wmax),
                             (unsigned long) ((uint64_t) e->wcalls * 10u / n));
        }
        tdEmit(line);
    }
    td.haveWin = false;
    tdCompact();
}

TD_TEXT static void tdEndFrame(uint32_t tEnd, bool skipped) {
    Runner* runner = td.runner;
    long frame = (long) runner->frameCount - 1;
    int32_t room = runner->currentRoomIndex;
    bool complete = (td.marks & 0x7Fu) == 0x7Fu;
    if (!complete) return;
    uint32_t step = td.tDraw - td.tStep;
    uint32_t draw = td.tAudio - td.tDraw;
    uint32_t audio = td.tRoom - td.tAudio;
    uint32_t roomc = td.tPresent - td.tRoom;
    uint32_t present = tEnd - td.tPresent;
    uint32_t cpu = tEnd - td.tStep;
    uint32_t pre = td.tStep - td.tBegin;
    uint32_t wait = td.tBegin - td.tWait;
    bool slot = (td.marks & 0x80u) != 0;
    uint32_t preWait = slot ? td.tSlotEnter - td.tWait : 0;
    uint32_t postWait = slot ? td.tStep - td.tSlotExit : 0;
    CtrRenderStats rs = CtrRenderer_getStats(td.renderer);
    uint32_t loads = rs.textureLoads - td.loadsAtBegin;
    float loadMs = rs.textureLoadMs - td.loadMsAtBegin;

    // A new window at a gap (pause, load) or room change; the old one is logged.
    if (td.haveWin && (frame != td.lastFrame + 1 || room != td.lastRoom)) tdWindowFlush();
    if (frame != td.lastFrame + 1) td.sceneMax = 0;
    if (!td.haveWin) {
        td.haveWin = true;
        td.wseq++;
        td.wFirst = frame;
        td.wFrames = 0;
        td.wPushes = 0;
        td.wCpu = td.wStep = td.wDraw = td.wOther = 0;
        td.wCpuMax = td.wStepMax = td.wDrawMax = td.wOtherMax = 0;
    }
    td.lastFrame = frame;
    td.lastRoom = room;

    // This frame's entries into the window.
    for (uint32_t i = 0; TD_SLOTS + 1u > i; i++) {
        TdEntry* e = i < TD_SLOTS ? &tdTable[i] : &td.over;
        if (e->fseq != td.seq) continue;
        if (e->wseq != td.wseq) {
            e->wseq = td.wseq;
            e->wticks = 0;
            e->wmax = 0;
            e->wcalls = 0;
        }
        e->wticks += e->fticks;
        if (e->fticks > e->wmax) e->wmax = e->fticks;
        e->wcalls += e->fcalls;
    }
    uint32_t other = audio + roomc + present;
    td.wFrames++;
    td.wLast = frame;
    td.wPushes += td.pushes;
    td.wCpu += cpu;
    td.wStep += step;
    td.wDraw += draw;
    td.wOther += other;
    if (cpu > td.wCpuMax) td.wCpuMax = cpu;
    if (step > td.wStepMax) td.wStepMax = step;
    if (draw > td.wDrawMax) td.wDrawMax = draw;
    if (other > td.wOtherMax) td.wOtherMax = other;

    if (cpu >= TD_SLOW_TICKS || cpu > td.sceneMax) {
        if (cpu > td.sceneMax) td.sceneMax = cpu;
        char line[960];
        int used = snprintf(line, sizeof line, tdFmtFrame, frame, (unsigned long) tdUs(cpu), (unsigned long) tdUs(step),
                            (unsigned long) tdUs(draw), (unsigned long) tdUs(audio), (unsigned long) tdUs(roomc),
                            (unsigned long) tdUs(present), (unsigned long) tdUs(pre), (unsigned long) tdUs(wait), (unsigned long) tdUs(preWait), (unsigned long) tdUs(postWait),
                            (unsigned long) td.rtCount, (unsigned long) tdUs(td.rtTicks),
                            (unsigned long) (skipped ? 0u : (uint32_t) (rs.gpuMs * 1000.0f)), (unsigned long) loads,
                            (unsigned long) (loadMs > 0.0f ? (uint32_t) (loadMs * 1000.0f) : 0u), (unsigned long) ++td.lines);
        TdEntry* top[TD_FRAME_TOP];
        int count = tdTop(top, TD_FRAME_TOP, false);
        for (int j = 0; count > j && used < (int) sizeof line - 1; j++) {
            TdEntry* e = top[j];
            used += snprintf(line + used, sizeof line - (size_t) used, tdFmtItem, tdPhaseNames[e->phase & 3u], tdShort(e->name),
                             (unsigned long) tdUs(e->fticks), (unsigned long) e->fcalls);
        }
        tdEmit(line);
    }
    if (td.wFrames >= TD_WIN) tdWindowFlush();
}

// ===[ wraps: the main loop and the bench ]===

TD_TEXT void __wrap_CtrBench_sessionStartedLate(const CtrBenchSession* session) {
    td.runner = session != NULL ? session->runner : NULL;
    td.renderer = session != NULL ? session->renderer : NULL;
    td.dataWin = NULL;
    tdClear();
    td.lastFrame = -10;
    uint32_t a = tdNow();
    for (int i = 0; 32 > i; i++) (void) svcGetSystemTick();
    uint32_t b = tdNow();
    logInfo(tdFmtStart, (unsigned long) ((uint64_t) (b - a) * 1000000000ull / 268111856ull / 32u), (unsigned long) TD_SLOTS,
            (unsigned long) TD_WIN);
    __real_CtrBench_sessionStartedLate(session);
}

TD_TEXT CtrBenchFrame __wrap_CtrBench_beginFrameTimed(u32 down, double frameMs) {
    CtrBenchFrame frame = __real_CtrBench_beginFrameTimed(down, frameMs);
    bool active = td.runner != NULL && td.renderer != NULL && CtrBench_running();
    if (!active && td.active && td.haveWin) {
        if (td.runner != NULL && td.runner->vmContext != NULL && td.runner->vmContext->dataWin == td.dataWin) tdWindowFlush();
        else td.haveWin = false;
    }
    if (active && !td.active) tdCompact();
    td.active = active;
    td.tBegin = tdNow();
    td.marks |= 0x02u;
    if (active) {
        CtrRenderStats rs = CtrRenderer_getStats(td.renderer);
        td.loadsAtBegin = rs.textureLoads;
        td.loadMsAtBegin = rs.textureLoadMs;
    }
    return frame;
}

TD_TEXT void __wrap_CtrBench_endFrameTimed(double stepMs, double drawMs, bool skipped) {
    uint32_t tEnd = tdNow();
    __real_CtrBench_endFrameTimed(stepMs, drawMs, skipped);
    if (td.active && td.runner != NULL && td.runner->vmContext != NULL && td.runner->vmContext->dataWin == td.dataWin) {
        tdEndFrame(tEnd, skipped);
    }
}

TD_TEXT void __wrap_CtrWatchdog_mark(const char* phase) {
    __real_CtrWatchdog_mark(phase);
    uint32_t now = tdNow();
    if (phase == NULL) return;
    switch (phase[0]) {
    case 'w':
        if (strcmp(phase, tdMarkWait) == 0) {
            td.seq++;
            td.phase = 0;
            td.marks = 0x01u;
            td.tWait = now;
            td.pushes = 0;
            td.rtCount = 0;
            td.rtTicks = 0;
        }
        break;
    case 's':
        if (strcmp(phase, tdMarkStep) == 0) {
            td.phase = 1;
            td.marks |= 0x04u;
            td.tStep = now;
        }
        break;
    case 'd':
        if (strcmp(phase, tdMarkDraw) == 0) {
            td.phase = 2;
            td.marks |= 0x08u;
            td.tDraw = now;
        }
        break;
    case 'a':
        if (strcmp(phase, tdMarkAudio) == 0) {
            td.phase = 3;
            td.marks |= 0x10u;
            td.tAudio = now;
        }
        break;
    case 'r':
        if (strcmp(phase, tdMarkRoom) == 0) {
            td.marks |= 0x20u;
            td.tRoom = now;
        }
        break;
    case 'p':
        if (strcmp(phase, tdMarkPresent) == 0) {
            td.marks |= 0x40u;
            td.tPresent = now;
        }
        break;
    default:
        break;
    }
}

#endif
