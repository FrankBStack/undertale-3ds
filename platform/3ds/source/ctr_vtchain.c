// vtchain (change flowerhw, 2026-11-03): test builds only (CMake CTRPORT_VTCHAIN_CHECK); never in a Release build.
//
// The renderer's table is a chain of copies: each wrapper copies the table in front (or the renderer's own) and puts
// its own in front of it (smalltext, natsurf6, nslice, the tower decorations). A copy cannot be followed, so each
// install notes (its table, the table it copied) here, through CTR_VTCHAIN_NOTE (ctr_renderer.h). A table that goes
// on in front of a chain already holding it is a loop: its entries reach the copy that calls back into it. That was
// smalltext going on again over the tower decorations' table at a room change, which spun text drawn by the
// renderer forever. Such an install logs the chain and stops the run at once (an undefined instruction, so the crash
// report shows where), rather than hanging in the first text the wrapper hands on.
//
// A note whose copied table is not in the record starts a new chain: the renderer's own table (a fresh renderer, a
// new chapter) or a table installed without a note (test-only wrappers such as halfcensus).
#ifdef CTRPORT_VTCHAIN_CHECK
#include <stdint.h>

#include "ctr_renderer.h"
#include "log.h"

#define VTC_MAX 16

static struct {
    const void* outer[VTC_MAX];
    const void* under[VTC_MAX];
    const char* who[VTC_MAX];
    uint32_t count;
} vtc;

static const char* const vtcNames[] = {"natsurf6", "nslice", "tower decorations", "smalltext"};

static const char* vtcName(int who) {
    return who >= 0 && (int) (sizeof(vtcNames) / sizeof(vtcNames[0])) > who ? vtcNames[who] : "?";
}

static int32_t vtcFind(const void* table) {
    for (uint32_t i = 0; vtc.count > i; i++) {
        if (vtc.outer[i] == table) return (int32_t) i;
    }
    return -1;
}

void CtrVtchain_note(const void* renderer, const void* outer, const void* under, int whoId) {
    const char* who = vtcName(whoId);
    if (vtcFind(under) < 0) vtc.count = 0; // a new chain
    uint32_t depth = 0;
    for (const void* t = under; t != nullptr && VTC_MAX >= depth; depth++) {
        int32_t i = vtcFind(t);
        if (t == outer) {
            logError("vtchain: LOOP: %s's table %p goes on renderer %p in front of a chain that already holds it:\n", who, outer,
                     renderer);
            for (const void* u = under; u != nullptr;) {
                int32_t k = vtcFind(u);
                logError("vtchain:   %p (%s)\n", u, 0 > k ? "the renderer's own" : vtc.who[k]);
                if (0 > k || u == outer) break;
                u = vtc.under[k];
            }
            __builtin_trap();
        }
        if (0 > i) break;
        t = vtc.under[i];
    }
    int32_t at = vtcFind(outer);
    if (0 > at) {
        if (vtc.count >= VTC_MAX) vtc.count = 0;
        at = (int32_t) vtc.count++;
    }
    vtc.outer[at] = outer;
    vtc.under[at] = under;
    vtc.who[at] = who;
    logInfo("vtchain: %s's table %p on renderer %p, in front of %p (%lu below)\n", who, outer, renderer, under, (unsigned long) depth);
}
#endif
