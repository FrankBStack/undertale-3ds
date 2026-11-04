// Mid-frame submission. Compiled only for the approved DELTARUNE New trial.
#ifndef CTRPORT_CTR_GPU_KICK_H
#define CTRPORT_CTR_GPU_KICK_H
#include <3ds.h>
#include <stdbool.h>
#include <stdint.h>

#ifdef CTR_GPU_KICK
// Physical busy remains CtrGpu_busy; these are the allocator's whole-frame fence.
bool CtrKick_retirementBusy(void);
uint32_t CtrKick_retirementDue(void);
// Called only with the allocator lock released. The recording thread drains
// submitted work, then runs/resumes the unsent part instead of waiting on itself.
void CtrKick_pressureWait(s64 nanos);
void CtrKick_setDrain(void (*drain)(void*), void* context);
// Rev2: no prefix in a frame that loads or sync-copies textures (or right
// after one that loaded); textureBusy says whether tiles are loading now.
void CtrKick_setTextureProbe(bool (*textureBusy)(void*));
// Per frame: begin takes whether the frame before loaded tiles, setFrame its number.
void CtrKick_frameBegin(bool loadedBefore);
void CtrKick_setFrame(uint32_t frame);
#ifdef CTR_KICK_FORCE_PRESSURE
void CtrMemory_kickPressureTest(void);
#endif
#endif
#endif
