// UTSCOURD F4 (change auditfixe2; regaudit F4): included by ctr_data_version.c on a line that was blank, just before
// CtrDataVersion_check, so no line of that file moves and the change stays append-only (RULES 3adf7ac34).
//
// UNDERTALE: the check's one allocation, its 64 KB read buffer, goes to CtrDataVersion_buffer (ctr_data_version.c's
// end), which calls malloc as before and notes whether it failed. The check still answers CTR_DATA_UNREADABLE then,
// and z_datarefuse.c still stops with its "couldn't be read" message, but the crash screen (z_argcrash.c's
// argcrashPaintMem) shows the out-of-memory title instead of the SD card one: the card was fine, memory ran out.
// Declared malloc-like, so GCC treats the call exactly as it treated malloc's: only the call's target changes.
//
// DELTARUNE: nothing here, so its object doesn't change.

#ifndef CTR_DATA_VERSION_MEM_H
#define CTR_DATA_VERSION_MEM_H

#if defined(ENABLE_WAD16) && (defined(__3DS__) || defined(CTR_DATA_VERSION_MEM_HOST_TEST))
#include <stdbool.h>
#include <stddef.h>
void* CtrDataVersion_buffer(size_t size) __attribute__((malloc, alloc_size(1)));
// Whether the latest CtrDataVersion_buffer call failed (z_argcrash.c's argcrashPaintMem reads it).
extern volatile bool ctrDataVersionNoMemory;
#define malloc CtrDataVersion_buffer
#endif

#endif
