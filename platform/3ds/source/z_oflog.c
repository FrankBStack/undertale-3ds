// oflog (first update, change bootmask, review decision 11-07; UNDERTALE only): no handle census on room changes.
//
// main.c logs CtrOpenFiles_log("room", false) on every room change. Where the kernel won't say how many handles the
// process holds, ctr_open_files.c counts them on Azahar by filling the handle table with copies of the process handle
// (freeHandles: about 4,046 duplicates and as many closes), 61 ms of the room-change frame on Azahar, either model.
// Consoles always answer: 217,274 "Files (...)" lines in 20,638 console logs all give a believable count, so they
// never reach the census. Through --wrap (platform/3ds/CMakeLists.txt), a call without the listing goes to the real
// function only when the count is believable, as the real function checks it; otherwise this logs that the count is
// unknown, without the file counts. The listing calls ("then" after a failed open, "after unloading") still take the
// census, so the room-change line is the only one that changes, and only on Azahar.
//
// Its own file and late (platform/3ds/late_reserve.ld: its code and its one string after bootahead's), so no earlier
// code or constant moves. No statics.

#include <3ds.h>
#include <stdbool.h>

#include "log.h"

#define OFLOG_HANDLES_BELIEVABLE 12 // ctr_open_files.c's HANDLES_BELIEVABLE

// An array, not a string literal: a literal goes in a mergeable string section, and the linker's string merging then
// pooled an earlier late object's string differently (z_writerfront.o's 3 B), which moved every later late address.
static const char oflogUnknown[] = "Files (%s): kernel handles unknown\n";

void __real_CtrOpenFiles_log(const char* where, bool list);
void __wrap_CtrOpenFiles_log(const char* where, bool list);

void __wrap_CtrOpenFiles_log(const char* where, bool list) {
    s64 handles = -1;
    if (list || (R_SUCCEEDED(svcGetProcessInfo(&handles, CUR_PROCESS_HANDLE, 4)) && OFLOG_HANDLES_BELIEVABLE <= handles &&
                 handles <= 0x10000)) {
        __real_CtrOpenFiles_log(where, list);
        return;
    }
    logInfo(oflogUnknown, where);
}
