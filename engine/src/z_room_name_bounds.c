// SCOURS3-004: a save can provide a negative or out-of-range room number.
// Keep the helper separate so compiling it cannot reorder vm_builtins' pool.
#include "data_win.h"

#if defined(PLATFORM_3DS) && defined(__GNUC__)
#define ROOM_BOUNDS_CODE __attribute__((noinline, noipa, optimize("Os"), section(".auditfixg_r2_room_text")))
#define ROOM_BOUNDS_STRING __attribute__((section(".rodata.auditfixg_r2_room_in_text")))
#else
#define ROOM_BOUNDS_CODE
#define ROOM_BOUNDS_STRING
#endif

// Placed in the appended code block: consumes no late-rodata reserve and does
// not change any existing string, constant, or pointer in vm_builtins.o.
static const char roomNameUndefined[] ROOM_BOUNDS_STRING = "<undefined>";

ROOM_BOUNDS_CODE const char* auditfixgR2RoomName(const DataWin* dw, int32_t id) {
    return (uint32_t) id < dw->room.count ? dw->room.rooms[id].name : roomNameUndefined;
}
