// UT compatibility collision traversal: self object, target event, self instance,
// target instance. Geometry and callback execution stay in the retained runner.
#include "runner.h"
#include "data_win.h"
#include "instance.h"
#include "z_utlife_collision.h"

#if defined(ENABLE_WAD16)
__attribute__((section(".text.late.parity_collision"), noinline))
bool Utlife_nextCollision(Runner* runner, UtlifeCollisionCursor* c) {
    if (c->eventFirst) return Utlife_nextCompatCollision(runner, c);
    for (;;) {
        // Non-compatibility WAD16 keeps the original self-first walk and
        // its event-list selection at entry to each self instance.
        if (c->si >= c->count) return false;
        if (c->ei == 0) {
            c->self = runner->instanceSnapshots[c->base + c->si];
            if (!c->self->active || c->self->physicsBody) { ++c->si; continue; }
            c->list = &runner->flattenedCollisionEvents[c->self->objectIndex];
        }
        if (c->ei >= c->list->eventCount) { c->ei = 0; ++c->si; continue; }
        c->evt = &c->list->events[c->ei++];
        if (c->evt->codeId >= 0) return true;
    }
}
#endif
