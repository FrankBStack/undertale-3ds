// UNDERTALE's Omega Flowey ring attack (change flowend r39): the ring boss's Create without the generated code's
// generic paths, and its seven parts made without their Create's dispatch. Old 3DS builds only (CMakeLists.txt).
//
// When the attack starts, one step makes nine ring bosses (instance_create of the boss, nine times). Each boss's Create
// makes nine constant stores and then, for (i = 0; i < count; i++), creates a part, keeps its id in one self array and
// its angle (i * 360 / count) in another, then writes the part's angle variable, its x and y (the boss's x and y plus
// lengthdir_x / lengthdir_y of the angle plus the boss's turn, at the boss's radius) and its image_angle through that
// id. On the Old 3DS that step is the attack's heaviest (16 ms): the generated code re-finds each variable for every
// read, writes the part's variables through the interpreter's generic Pop (an instance found by id, then the variable
// inserted), and each part's creation dispatches its Create through the event table and executeCode.
//
// tools/aot/gmlaot.py binds the Create here only when its bytecode is exactly the shape in UTF_NATIVE (the FNV-1a digest
// of its full tokens: every instruction, constant and variable), through a small wrapper (aotu_<k>) that passes the
// generated function and the operands. UtRing_bossCreate does what the generated function does, step by step:
//  - a store of a number into a variable: the slot found, else inserted (IntRValueHashMap_getOrInsertUndefined, the
//    same result as the generated code's aotSlotWrite), what it held freed if it owned a reference (aotFreeCopy),
//    then the value copied in, as the generated code's stores (and Instance_setSelfVar) leave it for a number;
//  - each step of the loop starts where the bytecode has nothing on the stack (but one, after the call) and checks
//    first that the variables it reads are there and hold reals (what the stores above and the loop's own arithmetic
//    leave): anything else hands the rest of the Create to the interpreter from that step's first instruction
//    (aotDeopt), with the stack as the bytecode has it there. The reads before that check change nothing;
//  - the arithmetic is what vmArithNumbers / vmDivNumbers / vmCmpNumbers / aotMathLengthdirX / Y do with reals, each
//    result behind the generated code's barrier (AOT_OPAQUE_REAL), so -ffast-math can't combine them;
//  - instance_create through handleCall, as the generated code calls it; the array stores through
//    popArrayElementIntoSlot, else (the array to make or grow) the generated code's own site (aotSitePop: handlePop).
//    The two elements the step then reads back are the values just stored there (same array, same index, nothing in
//    between), so they are taken as stored: a weak copy (ownsReference false, typed as a variable), and the id as
//    Conv.v.i makes it;
//  - the part's variable, x, y and image_angle as handlePop writes them through an id (resolveVariableWrite: the
//    instance from VM_findInstanceByTarget; the variable's slot found or inserted, then Instance_setSelfVar; the
//    builtins through VMBuiltins_setVariable, as the creddodge pop does), the part found once for the four writes:
//    between them only the part's own variable and builtins are written (its own map, its fields, the collision grid;
//    no code runs), so the id, the instance and the boss's variables are what the generated code would read again;
//  - vspeed through the generated code's site (aotSitePopVar).
// UNDERTALE Old (UTRING_BOUND), when the part's Create is the code gmlaot.py checked (its digest; at run time its table
// entry binds the function generated from that code: VM_aotBoundFn), it has no PreCreate, and instance_create is the
// engine's own builtin (not a scene's wrapper), the part is made as builtin_instance_create makes it without its
// Create's dispatch: Runner_createInstanceWithDepth at the object's own depth (createAndInitInstance, the depth layer,
// the PreCreate lookup, which finds none), createEventFired, then the Create's five stores made on the part as its
// generated function makes them (two builtins through VMBuiltins_setVariable, as aotPopVarSlow; three variables as
// slot stores), with the part as the current instance and the event context executeResolvedEvent sets; then the
// creator variable and the id, as builtin_instance_create and handleCall leave them. Not when a room change is
// pending, the runner is exiting or objects are disabled: those creates go through handleCall.
//
// All code is late (.text.utring_late, platform/3ds/late_reserve.ld, last), so nothing that existed moves. UNDERTALE
// only, and only builds with generated code (the body is only bound from there).
#include "wad_versions.h"

#if defined(ENABLE_WAD16) && defined(CTRPORT_AOT) && defined(__GNUC__)

#include "aot/vm_aot.h"
#include "data_win.h"
#include "event_table.h"
#include "instance.h"
#include "int_rvalue_hashmap.h"
#include "runner.h"
#include "rvalue.h"
#include "vm.h"
#include "vm_builtins.h"

#include <stdbool.h>
#include <stdint.h>

#if defined(__arm__) && defined(__3DS__)
#define UTR_LATE __attribute__((noinline, section(".text.utring_late")))
#define UTR_BSS __attribute__((section(".bss.utring_late")))
#else
#define UTR_LATE __attribute__((noinline))
#define UTR_BSS
#endif

RValue UtRing_bossCreate(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) UTR_LATE;

#if !defined(ENABLE_VM_TRACING) && !defined(CTRPORT_AOT_STRESS) && !defined(ENABLE_VM_GML_PROFILER) && \
    !defined(UTRING_FORCE_FALLBACK)

// The operands (gmlaot.py's UTF_NATIVE order).
enum {
    UTR_TURN = 2,    // the angle added to each part's (a[0..8]: the nine stored variables, in store order)
    UTR_RADIUS = 3,
    UTR_I = 8,       // the loop counter (a[0]: the count)
    UTR_ARR = 9,     // the parts' ids
    UTR_ANGS = 10,   // their angles
    UTR_ANG = 11,    // the part's angle variable
    UTR_REFX = 12,   // the Pops of the part's x (0188), y (01EC), image_angle (0234); vspeed (0264)
    UTR_REFV = 15,
    UTR_OBJ = 16,    // the part's object
    UTR_FN = 17,     // instance_create's function index
    UTR_PFN = 18,    // the part's Create's generated function (0: not the checked code)
    UTR_PREF = 19,   // its Pops at 0004 and 0010
    UTR_PVAR = 21,   // its three variables
};

#if defined(UTRING_BOUND) && !defined(UTRING_NO_G2)
AotFn VM_aotBoundFn(VMContext* ctx, int32_t codeIndex); // vm.c's late VM_aotBoundFn (UNDERTALE Old writerfront)
#if defined(UTSW_ON)
void* Utsw_plainCreate(void* fn, int32_t target);       // z_utkill_swarm.c: what fn runs for this object
#define UTR_RUNS(fn, obj) Utsw_plainCreate((fn), (obj))
#else
#define UTR_RUNS(fn, obj) (fn)
#endif
static const DataWin* utrDw UTR_BSS;                    // the data.win utrCreate is for
static BuiltinFunc utrCreate UTR_BSS;                   // the engine's instance_create
#endif

// One of the nine stored variables of self, when it holds a real (what the Create's stores leave), else nullptr. The
// slot is there (the prologue stored it and no key is ever removed), so getOrInsertUndefined finds it: the read
// fast path's slot (vmScopeVarSlot), with no insert.
static RValue* utrReal(Instance* self, int32_t varID) UTR_LATE;
static RValue* utrReal(Instance* self, int32_t varID) {
    RValue* p = IntRValueHashMap_getOrInsertUndefined(&self->selfVars, varID);
    return p->type == RVALUE_REAL ? p : nullptr;
}

// A number v (no reference) into slot p: storeStackValueIntoSlot / Instance_setSelfVar for it.
static void utrPut(RValue* p, const RValue* v) UTR_LATE;
static void utrPut(RValue* p, const RValue* v) {
    if (p->ownsReference) aotFreeCopy(p);
    *p = *v;
}

// A PushI.i16 / Pop.v.i store of v into an instance's variable (aotPopVarFast, AOT_CSTORE): the slot found or inserted
// (getOrInsertUndefined: the same result as aotSlotWrite's getOrInsertUndefinedFast), and the int as
// coerceIntStoreToRealInPlace leaves it.
static void utrStoreInt(Instance* inst, int32_t varID, int32_t v) UTR_LATE;
static void utrStoreInt(Instance* inst, int32_t varID, int32_t v) {
    RValue t;
    AOT_SET_INT(&t, v, GML_TYPE_INT16);
    coerceIntStoreToRealInPlace(&t, GML_TYPE_INT32);
    utrPut(IntRValueHashMap_getOrInsertUndefined(&inst->selfVars, varID), &t);
}

// Pop.v.v [array] of S[0] into self's array at index (S[1]: the scope, -1; S[2]: the index, as Conv.v.i leaves it):
// popArrayElementIntoSlot, else (no such variable yet, or an element it can't store) the generated code's site at addr
// (handlePop). 0, or the address the interpreter carries on from.
static uint32_t utrArrayStore(VMContext* ctx, int32_t B, int32_t varID, int32_t index, uint32_t addr) UTR_LATE;
static uint32_t utrArrayStore(VMContext* ctx, int32_t B, int32_t varID, int32_t index, uint32_t addr) {
    RValue* S = &ctx->stack.slots[B];
    AOT_SET_INT(&S[1], -1, GML_TYPE_INT16);
    AOT_SET_INT(&S[2], index, GML_TYPE_INT32);
    RValue* p = vmScopeVarSlot(ctx, INSTANCE_SELF, varID);
    if (p != nullptr && aotx_popArrayElementIntoSlot(ctx, p, &S[2], &S[0], GML_TYPE_VARIABLE, false)) return 0;
    return aotSitePop(ctx, B + 3, AOT_SITE_WORD(addr, 8, 3, 0));
}

// A builtin of inst written as handlePop / aotPopVarSlow write it: the variable the Pop's operand names, no index.
static void utrSetBuiltin(VMContext* ctx, Instance* inst, int32_t ref, GMLReal v) UTR_LATE;
static void utrSetBuiltin(VMContext* ctx, Instance* inst, int32_t ref, GMLReal v) {
    const Variable* vd = &ctx->dataWin->vari.variables[(uint32_t) ref & 0x07FFFFFF];
    RValue r;
    AOT_SET_REAL(&r, v, GML_TYPE_VARIABLE);
    VMBuiltins_setVariable(ctx, inst, vd->builtinVarId, vd->name, r, -1);
}

#if defined(UTRING_BOUND) && !defined(UTRING_NO_G2)
// The part, made as builtin_instance_create makes it with its Create run in place (see the top), or nullptr when this
// create has to go through handleCall (nothing done).
static Instance* utrMakePart(VMContext* ctx, const int32_t* a, GMLReal x, GMLReal y) UTR_LATE;
static Instance* utrMakePart(VMContext* ctx, const int32_t* a, GMLReal x, GMLReal y) {
    Runner* runner = (Runner*) ctx->runner;
    DataWin* dw = ctx->dataWin;
    int32_t obj = a[UTR_OBJ];
    if (a[UTR_PFN] == 0 || runner->pendingRoom != -1 || runner->shouldExit || runner->disabledObjects != nullptr
        || 0 > obj || dw->objt.count <= (uint32_t) obj)
        return nullptr;
    if (utrDw != dw) {
        utrDw = dw;
        utrCreate = VM_findBuiltin(ctx, "instance_create");
    }
    // the call handleCall makes: the engine's builtin, cached, or z_utkill_swarm.c's wrapper (installed at the first
    // frame end) when for this object it would only call it
    if (utrCreate == nullptr || ctx->funcCallCache == nullptr || 0 > a[UTR_FN]
        || ctx->funcCallCacheCount <= (uint32_t) a[UTR_FN])
        return nullptr;
    const FuncCallCache* fc = &ctx->funcCallCache[a[UTR_FN]];
    if (UTR_RUNS(fc->builtin, obj) != (void*) utrCreate || fc->forward != nullptr) return nullptr;
    // findEventCodeIdAndOwner's lookups: no PreCreate, and the Create's code is the checked one
    int32_t slot = EventSlotMap_lookup(&runner->eventSlotMap, EVENT_PRECREATE, 0);
    if (slot >= 0 && ResolvedEventTable_lookup(&runner->eventTable, obj, slot, nullptr) >= 0) return nullptr;
    slot = EventSlotMap_lookup(&runner->eventSlotMap, EVENT_CREATE, 0);
    int32_t code = 0 > slot ? -1 : ResolvedEventTable_lookup(&runner->eventTable, obj, slot, nullptr);
    if (0 > code || VM_aotBoundFn(ctx, code) != (AotFn) (intptr_t) a[UTR_PFN]) return nullptr;

    // createAndInitInstance sets the object's depth already: Runner_createInstance less the Create's dispatch. The
    // Create's five stores go straight to the part: executeResolvedEvent's event context and executeCode's current
    // instance would be set around them and restored after, and none of them reads either (VMBuiltins_setVariable's
    // scales read the value, the part and the runner's grid).
    Instance* caller = (Instance*) ctx->currentInstance;
    Instance* inst = Runner_createInstanceWithDepth(runner, x, y, obj, dw->objt.objects[obj].depth);
    if (inst == nullptr) return nullptr; // (not with no objects disabled)
    inst->createEventFired = true;
    for (int j = 0; 2 > j; j++) utrSetBuiltin(ctx, inst, a[UTR_PREF + j], (GMLReal) 2);
    for (int j = 0; 3 > j; j++) utrStoreInt(inst, a[UTR_PVAR + j], 0);
    if (caller != nullptr && ctx->creatorVarID >= 0) {
        RValue c = RValue_makeReal((GMLReal) caller->instanceId);
        utrPut(IntRValueHashMap_getOrInsertUndefined(&inst->selfVars, ctx->creatorVarID), &c);
    }
    return inst;
}
#endif

// The Create's prologue values (the PushI.i16 before each of its first nine Pops).
static const int8_t utrInit[9] = { 7, 3, 0, 90, 0, 0, 0, 0, 0 };

// The interpreter carries on from addr with d values on the stack (they are in S[0..d-1]).
#define UTR_DEOPT(d, addr) do { depth = (d); at = (addr); goto deopt; } while (0)

// a: see the enum above.
RValue UtRing_bossCreate(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) {
    Instance* self = (Instance*) ctx->currentInstance;
    if (self == nullptr || self->objectIndex == STRUCT_OBJECT_INDEX) return generated(ctx);
    const int32_t B = ctx->stack.top;
    RValue* S = &ctx->stack.slots[B];
    int32_t depth;
    uint32_t at;
    for (int n = 0; 9 > n; n++) utrStoreInt(self, a[n], utrInit[n]);

    for (;;) {
        // 006C: i < count (vmCmpNumbers), else to the end
        const RValue* pi = utrReal(self, a[UTR_I]);
        const RValue* pc = utrReal(self, a[0]);
        if (pi == nullptr || pc == nullptr) UTR_DEOPT(0, 0x6C);
        if (vmCmpNumbers(pi, pc, CMP_LT) == 0) break;

        // 0084: instance_create(x, y, part): the object (Conv.i.v: a retag), y and x read from self
        AOT_SET_INT(&S[0], a[UTR_OBJ], GML_TYPE_VARIABLE);
        AOT_SET_REAL(&S[1], (GMLReal) self->y, GML_TYPE_VARIABLE);
        AOT_SET_REAL(&S[2], (GMLReal) self->x, GML_TYPE_VARIABLE);
        __asm__("" : "+m"(S[0]), "+m"(S[1]), "+m"(S[2]));
        ctx->ip = 0xA4;
        Instance* part = nullptr;
#if defined(UTRING_BOUND) && !defined(UTRING_NO_G2)
        part = utrMakePart(ctx, a, S[2].real, S[1].real);
        if (part != nullptr) {
            AOT_SET_REAL(&S[0], (GMLReal) part->instanceId, GML_TYPE_VARIABLE); // handleCall's stackPushTyped
            ctx->stack.top = B + 1;
        } else
#endif
        {
            ctx->stack.top = B + 3;
            aotx_handleCall(ctx, 0xD9020003u, ctx->bytecodeBase + 0xA0);
            if (ctx->stack.top != B + 1) UTR_DEOPT(ctx->stack.top - B, 0xA4);
        }
        // the id as the array keeps it, and as Conv.v.i makes it from there (vmConvFast)
        if (S[0].type != RVALUE_REAL) UTR_DEOPT(1, 0xA4);
        const int32_t id = (int32_t) S[0].real;

        // 00A4: ids[int(i)] = the result
        pi = utrReal(self, a[UTR_I]);
        if (pi == nullptr) UTR_DEOPT(1, 0xA4);
        const int32_t index = (int32_t) pi->real;
        uint32_t ip = utrArrayStore(ctx, B, a[UTR_ARR], index, 0xB4);
        if (ip != 0) return aotDeopt(ctx, k, ip);

        // 00BC: angles[int(i)] = i * 360 / count
        pi = utrReal(self, a[UTR_I]);
        pc = utrReal(self, a[0]);
        if (pi == nullptr || pc == nullptr) UTR_DEOPT(0, 0xBC);
        GMLReal ang = pi->real * (GMLReal) 360;
        AOT_OPAQUE_REAL(ang);
        ang = ang / pc->real;
        AOT_OPAQUE_REAL(ang);
        AOT_SET_REAL(&S[0], ang, GML_TYPE_VARIABLE);
        const RValue angv = S[0]; // as stored: a weak copy of it reads the same
        ip = utrArrayStore(ctx, B, a[UTR_ANGS], index, 0xE8);
        if (ip != 0) return aotDeopt(ctx, k, ip);

        // 00F0: the part's angle = angles[int(i)], through ids[int(i)]
        if (part == nullptr && INSTANCE_ID_BASE <= id) part = VM_findInstanceByTarget(ctx, id);
        if (part == nullptr || part->objectIndex == STRUCT_OBJECT_INDEX) UTR_DEOPT(0, 0xF0);
        utrPut(IntRValueHashMap_getOrInsertUndefined(&part->selfVars, a[UTR_ANG]), &angv);

        // 012C / 0190 / 01F4: x = x + lengthdir_x(radius, angle + turn), y likewise, image_angle = angle + turn
        const RValue* pt = utrReal(self, a[UTR_TURN]);
        const RValue* pr = utrReal(self, a[UTR_RADIUS]);
        if (pt == nullptr || pr == nullptr) UTR_DEOPT(0, 0x12C);
        GMLReal sum = ang + pt->real;
        AOT_OPAQUE_REAL(sum);
        for (int j = 0; 3 > j; j++) {
            GMLReal v = sum;
            if (2 > j) {
                GMLReal len = pr->real, dir = sum;
                AOT_OPAQUE_REAL(len);
                AOT_OPAQUE_REAL(dir);
                GMLReal d = j == 0 ? aotMathLengthdirX(len, dir) : aotMathLengthdirY(len, dir);
                AOT_OPAQUE_REAL(d);
                GMLReal base = (GMLReal) (j == 0 ? self->x : self->y);
                AOT_OPAQUE_REAL(base);
                v = base + d;
                AOT_OPAQUE_REAL(v);
            }
            utrSetBuiltin(ctx, part, a[UTR_REFX + j], v);
        }

        // 023C: i = i + 1 (a real over a real: a plain copy)
        RValue* pw = utrReal(self, a[UTR_I]);
        if (pw == nullptr) UTR_DEOPT(0, 0x23C);
        GMLReal next = pw->real + (GMLReal) 1;
        AOT_OPAQUE_REAL(next);
        pw->real = next;
        pw->ownsReference = false;
        pw->gmlStackType = GML_TYPE_VARIABLE;
    }

    // 0258: vspeed = 2.5, through the generated code's site
    AOT_SET_REAL(&S[0], (GMLReal) 2.5, GML_TYPE_DOUBLE);
    uint32_t ip = aotSitePopVar(ctx, B + 1, 0x264u >> 2, (uint32_t) a[UTR_REFV]);
    if (ip != 0) return aotDeopt(ctx, k, ip);
    ctx->stack.top = B;
    return aotx_scriptFallthroughReturnValue(ctx);
deopt:
    ctx->stack.top = B + depth;
    return aotDeopt(ctx, k, at);
}

#else

RValue UtRing_bossCreate(VMContext* ctx, uint32_t k, AotFn generated, const int32_t* a) {
    (void) k;
    (void) a;
    return generated(ctx);
}

#endif

#endif
