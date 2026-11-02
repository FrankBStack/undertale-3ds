// UNDERTALE's Omega Flowey vine burst (change flowend r37): the vine's Create without its four sound script calls'
// frames, and the burst's sound calls made together after the burst's creation loop.
//
// In the final fight, the master's user event 9 makes 30 vines in one step (repeat (30) { m = instance_create(...,
// the vine object); with (m) { ... } }), the last code of that branch. Each vine's Create sets six variables and then
// calls stop(A), play(A), stop(B), play(B), scripts that only call audio_stop_sound(argument0) and
// audio_play_sound(argument0, 80, 0). On the Old 3DS that step is the scene's heaviest: each create runs the
// creation code, two event dispatches, the Create, four script frames, four builtins and the audio code, far more
// code than the 16 KB instruction cache holds, so every create misses it again (the same sound call costs 2.3-3.4x
// more right after the creation code than after another sound call).
//
// tools/aot/gmlaot.py binds both code entries here only when their bytecode is exactly the shape in UTF_NATIVE (the
// FNV-1a digest of their full tokens: every instruction, constant and variable), through small wrappers (aotu_<k>)
// that pass the generated function and the operands.
//  - UtBurst_vineCreate makes the six stores as the generated function does (the same values and types, through the
//    same site function or the Pop fast path's result), then calls the two builtins the scripts call, with the
//    arguments the scripts pass, in the same order. Each script is exactly that call: on UNDERTALE Old
//    (UTBURST_BOUND) gmlaot.py checks it at build time and the body checks that the script's code runs as the
//    function generated from that checked code (aotBind matched it: name, place, the digest of every byte, every
//    variable and function reference); elsewhere the body checks the script's words once per data.win. Nothing
//    else runs in a script frame: the scripts have no locals, and their results are dropped. Scripts that aren't
//    exactly those calls (or not proven so) run the generated function instead, before any store; so does a self
//    variable the Pop fast path wouldn't take (the stores before it store the same constants again).
//  - UtBurst_masterBatch runs the master's event with the vines' sound calls held: each vine's Create counts itself
//    instead of calling, and when the event returns, the held calls are made in their order (stop A, play A, stop B,
//    play B, a vine at a time). Between the first held call and the event's end only the creation loop runs, which
//    makes no sound call and reads no sound state (instance_create of the vine, whose Create is the only event it
//    runs, the with block's variable writes, random and point_direction); any other path (a Create that falls back,
//    a store's site that hands over to the interpreter) makes the held calls first.
//    With 3 or more vines held, every play of the batch is left for the frame's audio update to start
//    (CtrAudio_burstDeferAll, flowend's burst deferral from the batch's first play): the plays that would have started
//    at once are a vine's first two, each stopped by the next vine's stops of the same sound inside the same batch.
//
// All code is late (.text.utburst_late, platform/3ds/late_reserve.ld, last), so nothing that existed moves. UNDERTALE
// only, and only builds with generated code (the bodies are only bound from there).
#include "wad_versions.h"

#if defined(ENABLE_WAD16) && defined(CTRPORT_AOT) && defined(__GNUC__)

#include "aot/vm_aot.h"
#include "data_win.h"
#include "instance.h"
#include "int_rvalue_hashmap.h"
#include "rvalue.h"
#include "vm.h"

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#if defined(__arm__) && defined(__3DS__)
#define UTB_LATE __attribute__((noinline, section(".text.utburst_late")))
#define UTB_BSS __attribute__((section(".bss.utburst_late")))
#else
#define UTB_LATE __attribute__((noinline))
#define UTB_BSS
#endif

RValue UtBurst_vineCreate(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) UTB_LATE;
RValue UtBurst_masterBatch(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) UTB_LATE;

#if !defined(ENABLE_VM_TRACING) && !defined(CTRPORT_AOT_STRESS) && !defined(ENABLE_VM_GML_PROFILER)

#if defined(UTBURST_BOUND)
// vm.c's late VM_aotBoundFn (UNDERTALE Old writerfront builds): the function bound to a code entry in this context,
// nullptr when none is (not looked up yet, interpreted, generated code off).
AotFn VM_aotBoundFn(VMContext* ctx, int32_t codeIndex);
#else
// z_utkill_vapor.c: a code entry's bytecode (operands patched) against a template, calls by name.
typedef struct {
    uint32_t word;
    const char* name;
} UtkillCall;
bool Utkill_codeIs(DataWin* dw, int32_t codeId, const uint32_t* words, uint32_t wordCount, const UtkillCall* calls,
                   uint32_t callCount);
#endif
// ctr_audio_system.c (UNDERTALE): the rest of this step's plays are left for the update to start.
void CtrAudio_burstDeferAll(void);

// The stop script: audio_stop_sound(argument0). The play script: audio_play_sound(argument0, 80, 0). Word 1 (and 5)
// is argument0's operand (patched), the call word is matched by the function's name.
#if !defined(UTBURST_BOUND)
static const uint32_t utbStopWords[5] = { 0xC305FFFF, 0xA0000008, 0xD9020001, 0, 0x9E050000 };
static const UtkillCall utbStopCall = { 3, "audio_stop_sound" };
static const uint32_t utbPlayWords[9] = {
    0x840F0000, 0x07520000, 0x840F0050, 0x07520000, 0xC305FFFF, 0xA0000008, 0xD9020003, 0, 0x9E050000,
};
static const UtkillCall utbPlayCall = { 7, "audio_play_sound" };
#endif
static const union {
    uint64_t u;
    double d;
} utbTenth = { 0x3FB999999999999AULL }; // the Push.d at 000C: 0.1

#if !defined(UTBURST_BOUND)
static const DataWin* utbDw UTB_BSS;   // the data.win the checks below are for
#endif
static BuiltinFunc utbStop UTB_BSS;    // audio_stop_sound, when the stop script is exactly the call above; else nullptr
static BuiltinFunc utbPlay UTB_BSS;    // audio_play_sound, likewise
static uint8_t utbBatch UTB_BSS;       // the master's event is running: vines hold their sound calls
static uint16_t utbHeld UTB_BSS;       // vines held
static int32_t utbHeldA UTB_BSS;       // their sounds (the binding's constants: the same for every vine)
static int32_t utbHeldB UTB_BSS;

#if !defined(UTBURST_BOUND)
// The builtin a script that is exactly `words` calls, or nullptr (also when the function isn't a script).
static BuiltinFunc utbScriptBuiltin(VMContext* ctx, int32_t fn, const uint32_t* words, uint32_t count,
                                    const UtkillCall* call) UTB_LATE;
static BuiltinFunc utbScriptBuiltin(VMContext* ctx, int32_t fn, const uint32_t* words, uint32_t count,
                                    const UtkillCall* call) {
    DataWin* dw = ctx->dataWin;
    FuncCallCache* fc = &ctx->funcCallCache[fn];
    int32_t code = fc->scriptCodeIndex;
    if (fc->builtin != nullptr || !Utkill_codeIs(dw, code, words, count, call, 1)) return nullptr;
    uint32_t w;
    memcpy(&w, DataWin_codeBytes(dw, &dw->code.entries[code]) + 4 * call->word, sizeof w);
    return (BuiltinFunc) ctx->funcCallCache[w].builtin;
}
#endif

// builtin(s) or builtin(s, 80, 0), as handleCall makes the scripts' calls: the arguments in call order (argument0,
// then the play script's 80 and 0: each Push.i, Conv.i.v, an int32 typed Variable), the result freed.
static void utbCall(VMContext* ctx, BuiltinFunc f, int32_t s, int32_t argc) UTB_LATE;
static void utbCall(VMContext* ctx, BuiltinFunc f, int32_t s, int32_t argc) {
    RValue args[3];
    AOT_SET_INT(&args[0], s, GML_TYPE_VARIABLE);
    AOT_SET_INT(&args[1], 80, GML_TYPE_VARIABLE);
    AOT_SET_INT(&args[2], 0, GML_TYPE_VARIABLE);
    RValue r = f(ctx, args, argc);
    if (r.ownsReference) aotFreeCopy(&r);
}

// The held vines' calls, in their order: each vine's stop(A), play(A), stop(B), play(B).
static void utbFlush(VMContext* ctx) UTB_LATE;
static void utbFlush(VMContext* ctx) {
    uint32_t n = utbHeld;
    if (n == 0) return;
    utbHeld = 0;
#if !defined(UTBURST_NO_D1)
    if (n >= 3) CtrAudio_burstDeferAll();
#endif
    for (; n != 0; n--)
        for (int j = 0; 2 > j; j++) {
            int32_t s = j == 0 ? utbHeldA : utbHeldB;
            utbCall(ctx, utbStop, s, 1);
            utbCall(ctx, utbPlay, s, 3);
        }
}
#endif

// a: con, saved, memorymode and active's IDs; the stop and play scripts' function indices; the two sounds (the
// PushI.i16 at 0050 and 0078); the operand words of the Pops at 0004 (visible) and 0018 (image_xscale); the functions
// the stop and play scripts' table entries bind (gmlaot.py checked those scripts' code; nullptr: none generated) and
// the builtins the scripts call (used with UTBURST_BOUND only).
RValue UtBurst_vineCreate(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) {
#if defined(ENABLE_VM_TRACING) || defined(CTRPORT_AOT_STRESS) || defined(ENABLE_VM_GML_PROFILER) || \
    defined(UTBURST_FORCE_FALLBACK)
    (void) k;
    (void) a;
#if defined(UTBURST_FORCE_FALLBACK) && !defined(ENABLE_VM_TRACING) && !defined(CTRPORT_AOT_STRESS) && \
    !defined(ENABLE_VM_GML_PROFILER)
    utbFlush(ctx);
#endif
    return generated(ctx);
#else
#if defined(UTBURST_BOUND)
    // Each call runs a script (no builtin of its name), and that script's code runs as the function generated from
    // the code gmlaot.py checked; then the builtins it calls. Checked at every create: a binding can change.
    BuiltinFunc f[2];
    for (int j = 0; 2 > j; j++) {
        const FuncCallCache* fc = &ctx->funcCallCache[a[4 + j]];
        AotFn want = (AotFn) (intptr_t) a[10 + j];
        if (fc->builtin != nullptr || want == nullptr || VM_aotBoundFn(ctx, fc->scriptCodeIndex) != want
            || (f[j] = (BuiltinFunc) ctx->funcCallCache[a[12 + j]].builtin) == nullptr) {
            utbFlush(ctx); // with the held vines' builtins, checked when they were held
            return generated(ctx);
        }
    }
    utbStop = f[0];
    utbPlay = f[1];
#else
    if (utbDw != ctx->dataWin) {
        utbDw = ctx->dataWin;
        utbStop = utbScriptBuiltin(ctx, a[4], utbStopWords, 5, &utbStopCall);
        utbPlay = utbScriptBuiltin(ctx, a[5], utbPlayWords, 9, &utbPlayCall);
    }
    if (utbStop == nullptr || utbPlay == nullptr) {
        utbFlush(ctx);
        return generated(ctx);
    }
#endif
    // The six stores as the generated function makes them. visible = 0 and image_xscale = 0.1 (PushI.i16 / Push.d
    // into the slot at the stack top, Pop.v.i / Pop.v.d) through their sites. con, saved, memorymode = 0 and
    // active = 1 as the Pop fast path stores them (aotPopVarFast: the int stored as a real by
    // coerceIntStoreToRealInPlace, then storeStackValueIntoSlot, a plain copy over a slot that owns nothing).
    const int32_t B = ctx->stack.top;
    RValue* S = &ctx->stack.slots[B];
    for (int i = 0; 2 > i; i++) {
        uint32_t type2 = GML_TYPE_INT32;
        if (i != 0) {
            type2 = GML_TYPE_DOUBLE;
            AOT_SET_REAL(S, (GMLReal) utbTenth.d, GML_TYPE_DOUBLE);
        } else {
            AOT_SET_INT(S, 0, GML_TYPE_INT16);
        }
        uint32_t ip = aotSitePopVar(ctx, B + 1, (uint32_t) ((i != 0 ? 0x18 : 0x04) >> 2) | (type2 << 28), (uint32_t) a[8 + i]);
        if (ip != 0) {
            utbFlush(ctx);
            return aotDeopt(ctx, k, ip);
        }
    }
    Instance* self = (Instance*) ctx->currentInstance;
    for (int i = 0; 4 > i; i++) {
        // vmScopeVarWriteSlot's lookup (IntRValueHashMap_getOrInsertUndefinedFast's result, out of line)
        RValue* dst = self != nullptr ? IntRValueHashMap_getOrInsertUndefined(&self->selfVars, a[i]) : nullptr;
        if (dst == nullptr || dst->ownsReference) {
            utbFlush(ctx);
            return generated(ctx);
        }
        AOT_SET_REAL(dst, (GMLReal) (i == 3), GML_TYPE_DOUBLE);
    }
    // Held in the master's event, else made at once (a single vine: no deferral).
    utbHeldA = a[6];
    utbHeldB = a[7];
    utbHeld++;
    if (!utbBatch) utbFlush(ctx);
    return aotx_scriptFallthroughReturnValue(ctx);
#endif
}

// The master's user event 9 with the vines' sound calls held until it returns (a: unused, instance_create's index).
RValue UtBurst_masterBatch(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) {
    (void) k;
    (void) a;
#if defined(ENABLE_VM_TRACING) || defined(CTRPORT_AOT_STRESS) || defined(ENABLE_VM_GML_PROFILER) || \
    defined(UTBURST_NO_BATCH)
    return generated(ctx);
#else
    if (utbBatch) return generated(ctx); // inside an outer one, which makes the calls
    utbBatch = 1;
    RValue r = generated(ctx);
    utbBatch = 0;
    utbFlush(ctx);
    return r;
#endif
}

#endif
