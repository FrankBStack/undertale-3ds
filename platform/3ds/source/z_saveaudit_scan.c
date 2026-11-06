// R333-1: libctru consumes an unconvertible/overlong entry before reporting its
// name error. Such an entry cannot be a game's ASCII save or backup. Keep all
// other failures fatal, and bound retries even if a corrupt directory sticks.
#if defined(ENABLE_WAD16) || defined(SAVEAUDIT_HOST_TEST)
#include <dirent.h>
#include <errno.h>
#include <stdbool.h>
#include "ctr_safe_save.h"

#define SS_CODE __attribute__((noinline, section(".text.late.saveaudit_scan")))
#define SS_RO __attribute__((section(".rodata.late.saveaudit_scan")))

void CtrMain_fatalScreen(const char* fmt, ...) __attribute__((noreturn));
DIR* CtrSaveaudit_scanOpen(const char* path);
struct dirent* CtrSaveaudit_scanNext(DIR* dir);
bool CtrSaveaudit_scanRecover(const char* path);

static const char ssReadError[] SS_RO =
    "The SD card or saves folder\ncould not be read or restored.\n"
    "Your saves were left alone.\nPress START to exit.\n"
    "Check the SD card, then try again.\n";
#ifdef CTRPORT_SAVEAUDIT_FATAL_TEST
static const char ssTestDirectory[] SS_RO = "sdmc:/3ds/undertale-3ds/saveaudit-fatal-test";
#endif

SS_CODE DIR* CtrSaveaudit_scanOpen(const char* path) {
#ifdef CTRPORT_SAVEAUDIT_FATAL_TEST
    // Test builds never enumerate the player's saves. The test bench seeds
    // this dedicated fixture directory; no fixture is created or changed here.
    (void)path;
    DIR* dir = opendir(ssTestDirectory);
    if (dir == NULL) CtrMain_fatalScreen(ssReadError);
#else
    DIR* dir = opendir(path);
    if (dir == NULL && errno != ENOENT) CtrMain_fatalScreen(ssReadError);
#endif
    return dir;
}

SS_CODE struct dirent* CtrSaveaudit_scanNext(DIR* dir) {
    for (unsigned skipped = 0; ; skipped++) {
        errno = 0;
#ifdef CTRPORT_SAVEAUDIT_FATAL_TEST
        // Exercise the real startup call and fatal UI, before any save is read.
        (void)dir;
        struct dirent* entry = NULL;
        errno = EIO;
#else
        struct dirent* entry = readdir(dir);
#endif
        if (entry != NULL || errno == 0) return entry;
        if ((errno == EILSEQ || errno == ENAMETOOLONG) && skipped < 64) continue;
        CtrMain_fatalScreen(ssReadError);
    }
}

SS_CODE bool CtrSaveaudit_scanRecover(const char* path) {
    if (!CtrSafeSave_recover(path)) CtrMain_fatalScreen(ssReadError);
    return true;
}
#endif
