#ifndef Z_PARITY_RESTORE_H
#define Z_PARITY_RESTORE_H

// UT draw keys are available on the release path; other configurations keep
// the original room lookup and its exact call target.
#if defined(UTORDER_ON)
static SavedRoomState* ParityRestore_entry(Runner* runner, int32_t roomIndex);
#else
#define ParityRestore_entry FreewinsRoom_entry
#endif

#endif
