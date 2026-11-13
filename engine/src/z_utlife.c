// Outside Room uses native inclusive right/bottom in the UT compatibility
// runtime. Keep that conversion local to this consumer, not collision geometry.
#include "z_utlife.h"

#if defined(ENABLE_WAD16)
__attribute__((noinline, section(".text.late.utlife")))
InstanceBBox Utlife_outsideRoomBBox(Runner* runner, Instance* inst) {
    // Reuse the retained bbox through its existing adapter. This avoids a new
    // call-graph edge to a static in runner.c and a duplicate generic bbox body.
    InstanceBBox bbox = Colexact_sharedBBox(runner, inst);
    if (IS_WAD16_OR_BELOW(runner) && runner->collisionCompatibilityMode && bbox.valid) {
        bbox.right -= 1.0;
        bbox.bottom -= 1.0;
    }
    return bbox;
}
#endif
