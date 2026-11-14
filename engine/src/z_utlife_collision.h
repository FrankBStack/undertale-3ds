#ifndef _BS_Z_UTLIFE_COLLISION_H_
#define _BS_Z_UTLIFE_COLLISION_H_

#include "runner.h"

#if defined(ENABLE_WAD16)
// One cursor per concrete self object; compatibility refreshes membership per
// target event. Callbacks can grow snapshots, so only the base index is kept.
typedef struct {
    int32_t base, count, object, si;
    uint32_t ei;
    FlattenedCollisionEventList* list;
    Instance* self;
    FlattenedCollisionEvent* evt;
    bool eventFirst;
    bool eventStart;
} UtlifeCollisionCursor;

bool Utlife_nextCollision(Runner* runner, UtlifeCollisionCursor* cursor);
bool Utlife_nextCompatCollision(Runner* runner, UtlifeCollisionCursor* cursor);
bool Utlife_collisionTargetsNeedSnapshot(const UtlifeCollisionCursor* cursor,
    int32_t cachedObject, int32_t targetObject, uint32_t cachedEpoch, uint32_t hitEpoch);
#endif

#endif
