// bakkeep (change auditfixe, SCOURSOL2-001, both games): a game file_rename or file_delete never removes the only copy
// of a save that a failed write left in its .bak.
//
// CtrSafeSave_write moves the live save to <name>.bak before it puts the new bytes in place; if both that and the
// rollback fail (a failing card), the last good bytes are only in the .bak, and the next boot's CtrSafeSave_recover
// puts them back. But ctrRenameFile and ctrDeleteFile (ctr_file_system.c) first call CtrSafeSave_forgetBackup, which
// unlinks the .bak so recovery cannot undo the rename or delete: with the live file missing, the rename then failed
// and nothing held the save any more. UNDERTALE renames a save file it has just checked with file_exists
// (the Draw events of Asgore's last cutscene and of the Omega Flowey master object). On PC GameMaker's file_rename
// moves the file that is there; it never loses it.
//
// So CtrSafeSave_forgetBackup is reached through the linker (-Wl,--wrap=CtrSafeSave_forgetBackup, CMakeLists.txt):
// the wrap first runs CtrSafeSave_recover, which puts a stranded .bak back at the live path only when the live file
// is missing (no change when it is there, the ordinary case: one stat), then forgets the backup as before. If the
// recovery fails, it returns false and keeps the .bak; both callers then note a save failure and return false, and
// the next boot recovers it. The rename then moves the recovered bytes (the last ones the card confirmed; the failed
// write's are gone either way, and the exit still says saving failed). Code is late (late_reserve.ld: .text_bakkeep).
#include <stdbool.h>

#include "ctr_safe_save.h"

#ifndef BAKKEEP_CODE
#define BAKKEEP_CODE __attribute__((noinline, section(".text_bakkeep")))
#endif

bool __real_CtrSafeSave_forgetBackup(const char* path);
bool __wrap_CtrSafeSave_forgetBackup(const char* path);

BAKKEEP_CODE bool __wrap_CtrSafeSave_forgetBackup(const char* path) {
    return CtrSafeSave_recover(path) && __real_CtrSafeSave_forgetBackup(path);
}
