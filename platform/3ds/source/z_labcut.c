// The original writer close and FIN drain keep their frozen slots. Only the
// lab-only sender join is appended, last in the late-text integration queue.
#include <3ds.h>
#include "ctr_exit.h"
#include "ctr_exit_files.h"
#include "ctr_lab.h"

void __real_CtrExit_closeLog(void);

__attribute__((noipa, section(".text.late.labcut"))) void __wrap_CtrExit_closeLog(void) {
    __real_CtrExit_closeLog();
    if (__atomic_load_n(&CtrExit_started, __ATOMIC_ACQUIRE) && CtrLab_active()) {
        Thread sender = *CtrExit_filesLinkState.thread;
        // Includes the sender's 5 s FIN/EOF drain. Failure enters the existing
        // cancellation worker; this bounds the added join, not FS/SOC teardown.
        if (sender != NULL && threadJoin(sender, 10000000000ULL) != 0) CtrExitFiles_closeFailed();
    }
}
