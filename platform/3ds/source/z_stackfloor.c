// No thread gets a stack under 8 KiB (change stackfloor, 11-07; UNDERTALE only; docs/3ds-hardware.md, "The main stack is
// libctru's 32 KB and has room; the input sampler's 4 KB stack has 208 B left when it logs").
//
// A log line from a thread other than main costs about 3.5 KB of stack (platformLog's 1 KB frame, postLine's 2 KB record),
// and up to about 5 KB when the writer can't take it and platformLog formats and prints it itself. Two 4 KiB threads
// can log: the input sampler (its handover lines, 3,888 of 4,096 B measured) and libctru's APT event thread
// (ctr_apt_trace.c's DSP hook, in the resume window after a suspend or sleep: 6.6 KB static bound). libctru's GSP
// thread logs too, but ctr_exit_midfile.c already gives it 16 KiB. A thread's stack is the end of its threadCreate
// block, after its Thread_tag, so an overflow writes that tag and then the heap chunk header: silent corruption, not a
// fault. libctru's own sizes (aptInit and ndspInit ask for 4096) aren't ours to change, but every threadCreate in the
// link, libctru's included, goes through ctr_memory.c's wrap, so the floor goes there.
//
// CMake points ctr_memory.c's call of CtrExitGsp_threadCreate at CtrStackfloor_threadCreate: the same call, another
// target, so no instruction there changes. This file is late code, appended last (late_reserve.ld), so no other address
// moves. Threads raised from 4 KiB: the sampler, APT, ndsp and the lab guard's fallback on every boot, and the Rosalina
// watcher on Luma; 4 KiB of heap each.

#include <3ds.h>
#include <stdbool.h>
#include <stddef.h>

#define STACKFLOOR_BYTES 8192u

Thread CtrExitGsp_threadCreate(ThreadFunc entry, void* arg, size_t stackSize, int prio, int core, bool detached);
Thread CtrStackfloor_threadCreate(ThreadFunc entry, void* arg, size_t stackSize, int prio, int core, bool detached);

Thread CtrStackfloor_threadCreate(ThreadFunc entry, void* arg, size_t stackSize, int prio, int core, bool detached) {
    if (STACKFLOOR_BYTES > stackSize) stackSize = STACKFLOOR_BYTES;
    return CtrExitGsp_threadCreate(entry, arg, stackSize, prio, core, detached);
}
