// Item 8 (auditfixh): query caps on the snap hooks' original table under state hashing.
// Menu open/save only. All existing installers and render-time callbacks keep their slots.
#include "ctr_renderer.h"
#include "renderer.h"

#if defined(ENABLE_WAD16)
// The hash session owns its callback and saved table; keep their selector there.
extern RendererVtable* StateHash_menuTable(Renderer* renderer);

__attribute__((noinline, optimize("Os"), section(".text.late.auditfixh")))
CtrDisplayCaps CtrRenderer_capsAuditfixh(Renderer* renderer) {
    RendererVtable* outer = renderer->vtable;
    // Smalltext can copy the hash table, so compare the callback, not the table's address.
    // StateHash_end leaves its original pointer set: a fresh renderer is recognized by
    // its callback too, and must pass through the ordinary first-install path.
    renderer->vtable = StateHash_menuTable(renderer);
    CtrDisplayCaps caps = CtrRenderer_getDisplayCaps(renderer);
    // No caps-chain link replaces the table: uthud/soulshake patch slots in place,
    // and itemverdict/the real caps query do not change the vtable. Restoring the
    // saved outer table therefore preserves every install and keeps hashing active.
    renderer->vtable = outer;
    return caps;
}
#endif
