// Native UT freezes both participant lists for one target event. Births may
// enter later events in the same pass, but cannot enter an event in progress.
#include "runner.h"
#include "data_win.h"
#include "instance.h"
#include "z_utlife_collision.h"
#include "string_compat.h"

#if defined(ENABLE_WAD16)
__attribute__((section(".text.late.parity_collision_membership"), noinline))
bool Utlife_nextCompatCollision(Runner* runner, UtlifeCollisionCursor* c) {
    c->eventStart = c->si == 0;
    for (;;) {
        if (c->ei >= c->list->eventCount) return false;
        if (c->si >= c->count) {
            c->si = 0;
            if (++c->ei >= c->list->eventCount) return false;
            Instance** bucket = runner->instancesByExactObject[c->object];
            c->count = (int32_t) arrlen(bucket);
            arrsetlen(runner->instanceSnapshots, c->base + c->count);
            if (c->count > 0)
                memcpy(&runner->instanceSnapshots[c->base], bucket, (size_t) c->count * sizeof(Instance*));
            c->eventStart = true;
            continue;
        }
        c->self = runner->instanceSnapshots[c->base + c->si++];
        if (!c->self->active || c->self->physicsBody || c->self->objectIndex != c->object) continue;
        c->evt = &c->list->events[c->ei];
        if (c->evt->codeId >= 0) return true;
    }
}

__attribute__((section(".text.late.parity_collision_membership"), noinline))
bool Utlife_collisionTargetsNeedSnapshot(const UtlifeCollisionCursor* c,
    int32_t cachedObject, int32_t targetObject, uint32_t cachedEpoch, uint32_t hitEpoch) {
    return cachedObject != targetObject || (c->eventFirst ? c->eventStart : cachedEpoch != hitEpoch);
}
#endif
