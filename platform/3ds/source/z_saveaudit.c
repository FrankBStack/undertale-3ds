// UNDERTALE startup must finish recovery and enumeration before the game sees saves.
// ctr_file_system.c alone redirects these three calls (CMakeLists.txt), retaining
// its original bodies and layout. No per-frame path, shared libc call, or writer
// retry changes. See test_saveaudit_startup.py for synthetic loss reproductions.
#if defined(ENABLE_WAD16) || defined(SAVEAUDIT_HOST_TEST)
#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include "ctr_safe_save.h"

#define SA_CODE __attribute__((noinline, section(".text.late.saveaudit")))
#define SA_RO __attribute__((section(".rodata.late.saveaudit")))

void CtrMain_fatalScreen(const char* fmt, ...) __attribute__((noreturn));
DIR* CtrSaveaudit_opendir(const char* path);
struct dirent* CtrSaveaudit_readdir(DIR* dir);
bool CtrSaveaudit_recover(const char* path);

static const char saOpenError[] SA_RO =
    "Couldn't open the save folder.\nTurn the system off, check the card,\nand try again.\n";
static const char saReadError[] SA_RO =
    "Couldn't finish reading the save folder.\nTurn the system off, check the card,\nand try again.\n";
static const char saRecoverError[] SA_RO =
    "Couldn't restore %s\nfrom its backup. It wasn't removed.\nTurn the system off, check the card,\nand try again.\n";

SA_CODE DIR* CtrSaveaudit_opendir(const char* path) {
    DIR* dir = opendir(path);
    // Only a genuinely absent folder permits a first boot with no saves.
    // In particular, a failed recovery open cannot be followed by a successful
    // index open that sees .bak but leaves its live name absent.
    if (dir == NULL && errno != ENOENT) CtrMain_fatalScreen(saOpenError);
    return dir;
}

SA_CODE struct dirent* CtrSaveaudit_readdir(DIR* dir) {
    // libsysbase readdir_r converts libctru dirnext's ENOENT end marker to
    // errno 0. Other failures propagate. Clear unrelated errno from the loop
    // body before each call; a partial list must never become a missing save.
    errno = 0;
    struct dirent* entry = readdir(dir);
    if (entry == NULL && errno != 0) CtrMain_fatalScreen(saReadError);
    return entry;
}

SA_CODE bool CtrSaveaudit_recover(const char* path) {
    // A warning followed by gameplay is unsafe here: default progress could
    // rotate the sole good backup out on a later successful write.
    if (!CtrSafeSave_recover(path)) CtrMain_fatalScreen(saRecoverError, path);
    return true;
}
#endif
