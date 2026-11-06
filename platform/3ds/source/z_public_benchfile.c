// Public UT builds ignore the lab's on-card bench trigger. Explicit --bench stays in main's original argv path.
#include <errno.h>
#include <string.h>
#include <sys/stat.h>

#if defined(ENABLE_WAD16) && defined(CTRPORT_PUBLIC_BENCH_FILE)
static const char benchPath[] __attribute__((section(".rodata.p51_in_text"))) = CTRPORT_GAME_DIR "/benchrun.txt";
int __real_bootHookStat(const char* path, struct stat* st);

__attribute__((noinline, noipa, section(".text_p51")))
int __wrap_bootHookStat(const char* path, struct stat* st) {
    if (strcmp(path, benchPath) == 0) {
        errno = ENOENT;
        return -1;
    }
    return __real_bootHookStat(path, st);
}
#endif
