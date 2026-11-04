#ifndef _BS_Z_UTLIFE_H_
#define _BS_Z_UTLIFE_H_

#include "collision.h"

#if defined(ENABLE_WAD16)
// Only Outside Room consumes inclusive compatibility bounds. Other bbox users
// keep the engine's exclusive right/bottom, including Outside View.
InstanceBBox Utlife_outsideRoomBBox(Runner* runner, Instance* inst);
#define UTLIFE_OUTSIDE_ROOM_BBOX(runner, inst) Utlife_outsideRoomBBox(runner, inst)
#else
#define UTLIFE_OUTSIDE_ROOM_BBOX(runner, inst) Collision_computeBBox(runner, inst)
#endif

#endif
