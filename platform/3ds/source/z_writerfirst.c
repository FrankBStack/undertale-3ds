// writerfirst       codeclose, lever 2; UNDERTALE Old 3DS writerfront builds only): a text writer's first Draw takes
// writerfront's hand front instead of the generated function.
//
// Why: writerfront (z_writerfront.c) runs the dialogue writer's Draw as hand code, but only when every variable it
// reads is there. Two of them, the pen's x and y, are made by the Draw itself: its first instructions store them, and
// nothing before the first Draw does (the writer's Create and setup scripts write neither). So every writer's first
// Draw, in the frame its text box opens, went to the fallback: the 100 KB generated function, which looks up the
// font script and builds a one-letter string for every character (the SAVE Alphys frame 21891 drew two writers that
// way: about 25 ms of the frame's 30 ms draw on the o3DS; codeclose's results, "Lever 2").
//
// What: a wrapper bound over the Draw in writerfront's place, which then runs writerfront's front as before. When the
// pen's x and y are both missing and the vertical-text flag is plainly false (a real 0 or an int32 0: the game only
// ever stores the flag as PushI 0 or 1 through Pop.v.i, a real), and the three variables the Draw reads first (that
// flag and the start x and y) are there as plain numbers, it does the Draw's first stores itself, exactly as the
// bytecode does them on that branch:
//     0x00 Push.v self.<flag>; 0x08 Conv.v.b; 0x0C Bf 0x30          (false: on to 0x30)
//     0x30 Push.v self.<start x>; 0x38 Pop.v.v self.<pen x>
//     0x40 Push.v self.<start y>; 0x48 Pop.v.v self.<pen y>
// Each Push.v is a weak copy of the slot; each Pop.v.v (type2 variable: no int-to-real coercion) inserts the variable
// (IntRValueHashMap_getOrInsertUndefined, which the interpreter's and the generated code's write paths call) and copies
// the value in. Then it calls the function it wraps, which runs the Draw from its first instruction: those stores
// happen again, with the same values, into slots that now exist. Anything else (the flag true or of another type, a
// variable missing or not a plain number, either pen variable already there) calls the wrapped function unchanged.
//
// Exactness (the full argument is in the results file): the stores are the bytecode's own, in its order, on the only
// branch taken; the bytecode reads three variables that are present before them, so the instance's variable map gets
// the same two inserts in the same order and grows (or not) the same way; the values stored are overwritten by the
// wrapped function's own first stores before anything reads them; no builtin is called (no RNG draw, no draw call).
//
// Binding: the Draw's code entry by its length and name hash (writerfront's pins). At the wrapper's first run, with the
// bytes in memory, the 20 instruction words above (0x00-0x4C, the other branch included) are checked against their
// FNV-1a 32 digest with each variable operand's index masked out (the operand's reference type is kept), and the five
// variables are read from those operands (each a plain instance variable: varID >= 0, no builtin); on a mismatch the
// wrapper stays off and only calls the wrapped function. Bound at each room change through the prefetchRoom chain, after
// writerfront's link (itemfront -> writerfirst -> textcase), only while writerfront's front is the function bound
// (WriterFront_bind true), with VM_aotSwapFront over it; vm.c's late VM_aotBoundFn names it. writerfront's own rebinding
// then finds the wrapper and changes nothing.
//
// Count: the first Draws done and the frame of the last one, logged at the next room change when they changed
// ("writerfirst: N, last F"). Late text, constants and bss only.

#if defined(CTRPORT_WRITERFRONT) && defined(CTRPORT_DODGEFRONT) && defined(ENABLE_WAD16) && defined(__3DS__)

#include <stdbool.h>
#include <stdint.h>

#include "ctr_wrap_chain.h"
#include "data_win.h"
#include "instance.h"
#include "int_rvalue_hashmap.h"
#include "log.h"
#include "renderer.h"
#include "runner.h"
#include "vm.h"
#include "vm_builtins.h"
#include "vm_fastpath.h"

#define W1_CODE __attribute__((noinline, section(".text.codeclose_wf_late")))
#define W1_RO __attribute__((aligned(4), section(".rodata.codeclose_wf_in_text")))
#define W1_BSS __attribute__((section(".bss.codeclose_wf_late")))

typedef RValue (*W1Fn)(VMContext* ctx);
bool VM_aotSwapFront(VMContext* ctx, int32_t codeIndex, W1Fn fn, W1Fn generated);
W1Fn VM_aotBoundFn(VMContext* ctx, int32_t codeIndex);
bool WriterFront_bind(VMContext* ctx);

// The Draw's bytecode length and its name's FNV-1a 32 (UNDERTALE 1.08 Steam and GOG; z_writerfront.c's wfPin[0]).
#define W1_LENGTH 9404u
#define W1_NAME 0xC36C3191u
// FNV-1a 32 of the words 0x00-0x4C with the variable operands' low 27 bits zeroed (words 1, 5, 7, 10, 13, 15, 17, 19:
// W1_OPERANDS), UNDERTALE 1.08 Steam and GOG (pinned by a script).
#define W1_PIN 0xC796BDC6u
#define W1_OPERANDS 0x000AA4A2u
// The pen variables first: once a writer has drawn they exist, and the wrapper's one lookup ends there.
enum { W_PX, W_PY, W_FLAG, W_X, W_Y, W_N };
// The operand words of: the pen x's pop (0x38), the pen y's pop (0x48), the flag's push (0x00), the start x's push
// (0x30), the start y's push (0x40).
static const uint8_t w1Word[W_N] W1_RO = {15, 19, 1, 13, 17};
static const char w1Log[] W1_RO = "writerfirst: %lu, last %ld\n";

static DataWin* w1Checked W1_BSS; // the data.win w1Code is for
static int32_t w1Code W1_BSS;     // the Draw's code index, or -1
static int8_t w1State W1_BSS;     // 0: bytes not checked yet; 1: checked; -1: off
static W1Fn w1Prev W1_BSS;        // the wrapped function (writerfront's front)
static int32_t w1Id[W_N] W1_BSS;  // varIDs
static uint32_t w1Hits W1_BSS;
static uint32_t w1Logged W1_BSS;
static int32_t w1Frame W1_BSS;

// The first run's check of the instructions at ip (the entry's start): 1 when they are the ones above, with w1Id set.
static W1_CODE int8_t w1Check(VMContext* ctx) {
    uint32_t at = ctx->ip;
    if (at + 80 > ctx->codeEnd) return -1;
    const uint32_t* w = (const uint32_t*) (ctx->bytecodeBase + at);
    uint32_t h = 2166136261u;
    for (int i = 0; 20 > i; i++) {
        uint32_t v = (W1_OPERANDS >> i) & 1u ? w[i] & 0xF8000000u : w[i];
        for (int b = 0; 32 > b; b += 8) h = (h ^ ((v >> b) & 0xFFu)) * 16777619u;
    }
    if (h != W1_PIN) return -1;
    Vari* vari = &ctx->dataWin->vari;
    for (int k = 0; W_N > k; k++) {
        uint32_t index = w[w1Word[k]] & 0x07FFFFFFu;
        if (index >= vari->variableCount) return -1;
        Variable* v = &vari->variables[index];
        if (0 > v->varID || v->builtinVarId != BUILTIN_VAR_UNKNOWN) return -1;
        w1Id[k] = v->varID;
    }
    return 1;
}

static W1_CODE RValue w1Front(VMContext* ctx) {
    if (w1State == 0) w1State = w1Check(ctx);
    Instance* self = (Instance*) ctx->currentInstance;
    if (w1State > 0 && self != NULL) {
        // Read only: both pen variables missing, then the flag and the start position present as plain numbers
        // (int32 or real).
        IntRValueHashMap* m = &self->selfVars;
        const RValue* s[W_N];
        int k = 0;
        for (; W_N > k; k++) {
            s[k] = IntRValueHashMap_findSlot(m, w1Id[k]);
            if (W_FLAG > k ? s[k] != NULL : s[k] == NULL || !vmIsPlainNumber(s[k]->type)) break;
        }
        if (k == W_N) {
            // s[W_FLAG] is set only when the loop ran to the end.
            const RValue* flag = s[W_FLAG];
            if (flag->type == RVALUE_REAL ? flag->real == (GMLReal) 0 : flag->int32 == 0) {
                // Both pushes' weak copies first: the first insert may grow the map and move every slot.
                RValue a, b;
                vmWeakCopyInto(&a, s[W_X]);
                vmWeakCopyInto(&b, s[W_Y]);
                *IntRValueHashMap_getOrInsertUndefined(m, w1Id[W_PX]) = a;
                *IntRValueHashMap_getOrInsertUndefined(m, w1Id[W_PY]) = b;
                w1Hits++;
                w1Frame = ctx->runner->frameCount;
            }
        }
    }
    return w1Prev(ctx);
}

// The prefetchRoom chain's link after itemfront's: finds the Draw (once per data.win), wraps writerfront's front when it
// is the function bound, logs the count when it changed, then the next link.
W1_CODE void CTR_PREFETCHROOM_WRITERFIRST(Renderer* renderer) {
    Runner* runner = renderer != NULL ? renderer->runner : NULL;
    VMContext* ctx = runner != NULL ? runner->vmContext : NULL;
    DataWin* dw = ctx != NULL ? ctx->dataWin : NULL;
    if (dw != NULL && w1Checked != dw) {
        w1Checked = dw;
        w1Code = -1;
        w1State = 0;
        for (uint32_t i = 0; dw->code.count > i; i++) {
            CodeEntry* code = &dw->code.entries[i];
            if (code->length != W1_LENGTH || code->name == NULL) continue;
            uint32_t nh = 2166136261u;
            for (const char* c = code->name; *c != '\0'; c++) nh = (nh ^ (uint8_t) *c) * 16777619u;
            if (nh != W1_NAME) continue;
            if (w1Code != -1) {
                w1Code = -2; // two entries: off
                break;
            }
            w1Code = (int32_t) i;
        }
    }
    if (dw != NULL && w1Code >= 0 && WriterFront_bind(ctx)) {
        W1Fn prev = VM_aotBoundFn(ctx, w1Code);
        if (prev != NULL && prev != w1Front) {
            w1Prev = prev;
            (void) VM_aotSwapFront(ctx, w1Code, w1Front, prev);
        }
    }
    if (w1Hits != w1Logged) {
        w1Logged = w1Hits;
        logInfo(w1Log, (unsigned long) w1Hits, (long) w1Frame);
    }
    CTR_PREFETCHROOM_AFTER_WRITERFIRST(renderer);
}

#endif
