// The existing main-thread repair queue also carries present-but-bad streams.
#ifdef ENABLE_WAD16
#include "ctr_notice.h"
#include <string.h>
static const char upd1AudioKind[] __attribute__((section(".rodata.late.upd1"))) = "Audio unavailable";
static const char upd1MissingKind[] __attribute__((section(".rodata.late.upd1"))) = "Missing audio";
__attribute__((noinline, section(".text.late.upd1")))
void Upd1_audioNotice(const char* kind, const char* path) {
    CtrNotice_missing(strcmp(kind, upd1MissingKind) == 0 ? upd1AudioKind : kind, path);
}
#endif
