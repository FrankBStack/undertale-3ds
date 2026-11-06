// regaudit F2: a sticky lightweight event using libctru's public address arbiter.
// Keep this separate from ctr_apt_trace.c so its old pools/static anchors retain
// their exact ordering. No strings, heap allocations or kernel handles are added.
#include <3ds.h>
#include "ctr_apt_trace.h"

#define TRACE_F2_CODE __attribute__((noinline, noipa, optimize("Os"), section(".auditfixg_f2_heartbeat_text")))
static s32 auditfixgF2Closed __attribute__((section(".bss_auditfixg_f2_heartbeat,\"aw\",%nobits @")));
void auditfixgF2Join(void);
void __real__exit(int status) __attribute__((noreturn));

TRACE_F2_CODE void auditfixgF2Wait(s64 timeout) {
    // The kernel compares the sticky word while registering the wait, closing
    // the signal-before-wait race. Never clear it during shutdown.
    if (!__atomic_load_n(&auditfixgF2Closed, __ATOMIC_ACQUIRE))
        syncArbitrateAddressWithTimeout(&auditfixgF2Closed, ARBITRATION_WAIT_IF_LESS_THAN_TIMEOUT, 1, timeout);
}

TRACE_F2_CODE void auditfixgF2Wake(void) {
    // No worker-owned lock: even a crash interrupting a waiter cannot block
    // signalling. Zero initial state is valid before init/during creation.
    __atomic_store_n(&auditfixgF2Closed, 1, __ATOMIC_RELEASE);
    syncArbitrateAddress(&auditfixgF2Closed, ARBITRATION_SIGNAL, -1);
}

TRACE_F2_CODE __attribute__((noreturn)) void auditfixgF2Exit(int status) {
    CtrAptTrace_stop();
    // Every status keeps libctru's FS/HID/APT/srv and loader-return chain.
    // The join owner already bounds failed workers before heap teardown.
    auditfixgF2Join();
    __real__exit(status);
}

// Preserve the following SDK adapter's address: 116 B of code plus 12 B slack.
// This input has a hard 128 B limit; growth beyond it must fail assembly.
#if defined(__3DS__) && defined(NDEBUG)
__asm__(".pushsection .auditfixg_f2_heartbeat_text,\"ax\",%progbits\n.subsection 1\n.org 128, 0\n.popsection\n");
#endif
