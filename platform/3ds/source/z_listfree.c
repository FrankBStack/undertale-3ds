// listfree (change stepdrift, 2026-11-14; UNDERTALE): after a room change, the per-object instance lists that are still
// empty are freed and made null.
//
// runner->instancesByExactObject[o] and instancesByObject[o] are stb_ds lists, each its own heap block. A list is
// allocated by its object's first instance and was only ever emptied, at room changes and resets
// (Runner_clearAllObjectLists) or as instances went. Every event pass of every step reads the length of each
// responder's non-null exact list, and the other object queries read the inclusive lists the same way. A null list
// costs nothing; a non-null one, empty or not, costs a load from its own block, which on Old 3DS (16 KB data cache,
// no L2) is a data-cache miss. So the more rooms a session had visited, the more empty lists each step read, and the
// same scene ran slower late in a session than fresh. Measured on o3ds (change stepdrift, rows
// longsess-soak-stepdrift-n8-{A,P}-fresh-gog-o3ds): 3,670 more such reads cost 0.76 ms more Step, all of it data-hazard
// stall cycles, about one data-cache read miss per read.
//
// This runs at the end of the room change: its link in the Runner_handlePendingRoomChange chain sits between game over
// and utwindow (CMakeLists.txt), and it frees only after utwindow and the real function return (utwindow touches no
// instance list). By then the old room's instances are gone, the new room's (and the persistent ones) are in their
// lists, and no event runs. Lists that hold instances are kept with their blocks; the next arrput gives a freed list a block
// again. Nothing holds a list pointer across a room change: every reader takes the pointer in the call (dispatch and
// `with` copy the instances out; the z_* fast paths and platform readers use it locally), and room changes run
// outside event loops (change stepdrift's holder check; the assistant round-3 review's census of all 114 references).
// It frees nothing in a frame without a room change (pendingRoom -1), and changes no game state or RNG.
#ifdef ENABLE_WAD16
#include "runner.h"
#include "stb_ds.h"

#define LF_TEXT __attribute__((noinline, section(".aacout.text.listfree")))

void __real_Runner_handlePendingRoomChange(Runner* runner);
void CtrListfree_pendingRoom(Runner* runner);

static LF_TEXT void lfFreeEmpty(Instance*** lists, uint32_t count) {
    if (lists == nullptr) return;
    for (uint32_t i = 0; count > i; i++) {
        if (lists[i] != nullptr && arrlen(lists[i]) == 0) arrfree(lists[i]);
    }
}

LF_TEXT void CtrListfree_pendingRoom(Runner* runner) {
    int32_t pending = runner->pendingRoom;
    __real_Runner_handlePendingRoomChange(runner);
    if (pending == -1) return;
    uint32_t count = runner->dataWin->objt.count;
    lfFreeEmpty(runner->instancesByObject, count);
    lfFreeEmpty(runner->instancesByExactObject, count);
}
#endif
