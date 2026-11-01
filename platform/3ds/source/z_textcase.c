// textcase       codeclose, lever 1; UNDERTALE Old 3DS only): the dialogue script's switch jumps straight to its case.
//
// Why: every text box runs UNDERTALE's dialogue script (146 KB of bytecode, interpreted on the Old 3DS) to fill in
// its lines, often several times in the frame it opens. The script is one switch on a self variable, compiled as a
// chain of about 480 compares (Dup.v 0, PushI.e K, Cmp.i.v EQ, Bt case) that the interpreter walks from the top on
// every call: about 2,000 instructions, 0.6 ms on Azahar, several ms on the console (the SAVE Alphys frame 21891 ran
// it three times; codeclose's results, "CAUSE").
//
// What: the builder lists the chain's cases sorted by constant in romfs:/textcase.bin (tools/aot/textcase.py). The
// switch is on the script's argument0: its first instruction is PushBltn.v self.argument0, which vm.c's executeLoop
// (pushSelfBuiltinVar) runs as a weak copy of the call's first argument, typed as a variable, whatever self is. This
// front reads that argument the same way. Only a whole number goes on: an int32, or a real equal to an int32. The
// front pushes it as that instruction would, finds the case by binary search and starts the interpreter there,
// exactly as the chain's Bt would have; one no case has goes to the chain's final B (no compare could match it:
// every constant is a whole number, at least 1 away, and the compare's epsilon is far below 1). Anything else (no
// argument, a fraction, a string, undefined) pushes nothing and starts the interpreter at the script's first
// instruction, as without the front. The first constant of a repeated one is the one listed, as the chain's first
// matching Bt wins. (The front reads the argument itself: the interpreter's exported PushBltn handler is otherwise
// unused, so the link leaves it out, and linking it would move every late function after it.)
//
// Binding: the table names its code entry by index and length (checked when it is read, at the first room change),
// and its digest (FNV-1a 32 of the bytes from the entry's offset through the chain's B, operands patched) is checked
// at the front's first run, when the bytes are in memory, with the first instruction's variable resolved to
// argument0 (the builder checks its name too). The front is bound at each room change through CtrRenderer_prefetchRoom's wrap
// chain (ctr_wrap_chain.h) with VM_aotBindFront (vm.c's late end); aotDispatch runs it only with ip at the entry's
// start. Without the file, or on a mismatch when it is read, nothing is bound and the chain runs as before; on a
// mismatch at the first run the front hands every call to the interpreter at the script's start.
//
// Count: the direct jumps and the frame of the last one, logged at the next room change when they changed
// ("textcase: N direct, last F"). Late text, constants and bss only: the table (at most TC_MAX cases) is read whole
// into bss, so there is no allocation.
//
// This build is the only user: CMakeLists.txt compiles this file (with CTRPORT_DODGEFRONT) for UNDERTALE o3DS only.

#if defined(CTRPORT_DODGEFRONT) && defined(ENABLE_WAD16) && defined(__3DS__)

#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>

#include "ctr_wrap_chain.h"
#include "data_win.h"
#include "log.h"
#include "renderer.h"
#include "runner.h"
#include "vm.h"
#include "vm_builtins.h"
#include "vm_fastpath.h"

#define TC_CODE __attribute__((noinline, section(".text.codeclose_case_late")))
#define TC_RO __attribute__((aligned(4), section(".rodata.codeclose_case_in_text")))
#define TC_BSS __attribute__((section(".bss.codeclose_case_late")))
#define TC_MAX 512 // tools/aot/textcase.py's MAX_CASES

typedef RValue (*TcFn)(VMContext* ctx);
bool VM_aotBindFront(VMContext* ctx, int32_t codeIndex, TcFn fn);
RValue aotx_executeLoop(VMContext* ctx);

// romfs:/textcase.bin (tools/aot/textcase.py): its header, then its entries (constant, case address / 4) by constant.
static struct {
    uint32_t code, length, span, digest, count;
    struct {
        int16_t key;
        uint16_t at;
    } cases[TC_MAX];
} tc TC_BSS;

// In this file's own constants: a string literal would go to .rodata.str1.1, where the link merges it with an equal
// string of another file and moves that file's constants.
static const char tcPath[] TC_RO = "romfs:/textcase.bin";
static const char tcMode[] TC_RO = "rb";
static const char tcLog[] TC_RO = "textcase: %lu direct, last %ld\n";

static int8_t tcState TC_BSS;  // 0: not read yet; 1: read, digest not checked yet; 2: checked; -1: off
static uint32_t tcHits TC_BSS; // direct jumps
static uint32_t tcLogged TC_BSS;
static int32_t tcFrame TC_BSS; // the frame of the last direct jump

// r converted to an int32 by the VFP, toward zero and saturating (NaN gives 0), so (GMLReal) k == r exactly when r
// is a whole number in the int32 range.
static inline int32_t tcInt(GMLReal r) {
    float t;
#ifdef USE_FLOAT_REALS
    __asm__("vcvt.s32.f32 %0, %1" : "=t"(t) : "t"(r));
#else
    __asm__("vcvt.s32.f64 %0, %P1" : "=t"(t) : "w"(r));
#endif
    int32_t k;
    __builtin_memcpy(&k, &t, sizeof k);
    return k;
}

static TC_CODE RValue tcFront(VMContext* ctx) {
    uint32_t at = ctx->ip;
    if (tcState == 1) {
        // The first run: the bytes the table was made from, switching on argument0.
        tcState = -1;
        if (at + tc.span <= ctx->codeEnd) {
            const uint8_t* bc = ctx->bytecodeBase + at;
            uint32_t h = 2166136261u;
            for (uint32_t j = 0; tc.span > j; j++) h = (h ^ bc[j]) * 16777619u;
            uint32_t var = *(const uint32_t*) (bc + 4) & 0x07FFFFFF;
            Vari* vari = &ctx->dataWin->vari;
            if (h == tc.digest && vari->variableCount > var && vari->variables[var].builtinVarId == BUILTIN_VAR_ARGUMENT0)
                tcState = 2;
        }
    }
    const RValue* v = ctx->scriptArgs;
    if (tcState == 2 && v != NULL && ctx->scriptArgCount > 0) {
        int32_t k = v->int32;
        bool whole = v->type == RVALUE_INT32;
        if (v->type == RVALUE_REAL) {
            k = tcInt(v->real);
            whole = (GMLReal) k == v->real;
        }
        if (whole) {
            vmWeakCopyInto(&ctx->stack.slots[ctx->stack.top++], v);
            uint32_t ip = at + tc.span - 4; // the chain's B: no case
            uint32_t lo = 0, hi = tc.count;
            while (hi > lo) {
                uint32_t mid = (lo + hi) >> 1;
                int32_t key = tc.cases[mid].key;
                if (key == k) {
                    ip = (uint32_t) tc.cases[mid].at << 2;
                    break;
                }
                if (k > key) lo = mid + 1;
                else hi = mid;
            }
            tcHits++;
            tcFrame = ctx->runner->frameCount;
            ctx->ip = ip;
        }
    }
    return aotx_executeLoop(ctx);
}

// The prefetchRoom chain's link after itemfront's (textfront's in builds without the writer front): reads the table
// at the first room change (UNDERTALE has one data.win), binds the front after each room change, logs the count when
// it changed, then the next link.
TC_CODE void CTR_PREFETCHROOM_TEXTCASE(Renderer* renderer) {
    Runner* runner = renderer != NULL ? renderer->runner : NULL;
    VMContext* ctx = runner != NULL ? runner->vmContext : NULL;
    DataWin* dw = ctx != NULL ? ctx->dataWin : NULL;
    if (dw != NULL && tcState == 0) {
        tcState = -1;
        FILE* f = fopen(tcPath, tcMode);
        if (f != NULL) {
            size_t n = fread(&tc, 1, sizeof tc, f);
            fclose(f);
            if (TC_MAX >= tc.count && n == 20 + 4 * tc.count && tc.count != 0 && dw->code.count > tc.code
                && dw->code.entries[tc.code].length == tc.length && tc.span >= 12)
                tcState = 1;
        }
    }
    if (tcState > 0 && VM_aotBindFront(ctx, (int32_t) tc.code, tcFront) && tcHits != tcLogged) {
        tcLogged = tcHits;
        logInfo(tcLog, (unsigned long) tcHits, (long) tcFrame);
    }
    CTR_PREFETCHROOM_AFTER_TEXTCASE(renderer);
}

#endif
