// Audio worker boost across shared lock sections (UNDERTALE Old 3DS only).
// Linked as its own appended late sections (.text_sfxboost, .rodata_sfxboost).
// Boost alone: no message drain, deferred sound request or PCM policy.
#include <3ds.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>

typedef struct CtrAudioSystem CtrAudioSystem;
CtrAudioSystem* CtrAudioSystem_create(void);
void logInfo(const char* format, ...);
extern CtrAudioSystem* volatile* const ctrAudioBoostTarget;

#define AUDIOBOOST_CODE __attribute__((noinline, section(".text_sfxboost")))
#define AUDIOBOOST_FIELD(ca, at, type) (*(type*)((char*)(ca) + (at)))

typedef struct {
    void* tls;
    char* system;
    s32 base;
    uint32_t depth;
    bool raised;
} AudioBoost;
#ifdef __3DS__
_Static_assert(sizeof(AudioBoost) == 20, "two boost states must request exactly 40 B");
#endif
// Allocator alignment leaves two low bits: inactive and reported. They live
// in the existing audio-object padding, not in another allocation or BSS.
// Mask them even on cleanup: allocation failure is the sentinel 1, then 3.
#ifdef CTRPORT_AUDIOBOOST_REPORT
static const char boostInactiveMessage[] __attribute__((section(".rodata_sfxboost"))) =
    "audio boost inactive";
#endif

static inline __attribute__((always_inline)) uintptr_t* boostRoot(void* ca) {
    return (uintptr_t*)((char*)ca + CTRPORT_AUDIOBOOST_STATE_AT);
}
static inline __attribute__((always_inline)) uintptr_t boostBits(void* ca) {
    return ca ? __atomic_load_n(boostRoot(ca), __ATOMIC_RELAXED) : 0;
}
static inline __attribute__((always_inline)) AudioBoost* boostState(void* ca) {
    return (AudioBoost*)(boostBits(ca) & ~(uintptr_t)3);
}

#ifdef CTRPORT_AUDIOBOOST_REPORT
static AUDIOBOOST_CODE void boostReport(void* ca) {
    if ((boostBits(ca) & 3) == 1 && threadGetCurrent() == NULL &&
        !(__atomic_fetch_or(boostRoot(ca), 2, __ATOMIC_RELAXED) & 2))
        logInfo(boostInactiveMessage);
}
#else
#define boostReport(ca) ((void)0)
#endif

AUDIOBOOST_CODE CtrAudioSystem* CtrAudioBoost_create(void) {
    CtrAudioSystem* ca = CtrAudioSystem_create();
    if (ca) {
        AudioBoost* state = calloc(2, sizeof(AudioBoost));
        *boostRoot(ca) = state ? (uintptr_t)state : 1;
        boostReport(ca);
    }
    return ca;
}

AUDIOBOOST_CODE void CtrAudioBoost_free(void* ca) {
    if (ca) free(boostState(ca));
    free(ca);
}

AUDIOBOOST_CODE void CtrAudioBoost_lock(LightLock* lock) {
    char* ca = (char*)*ctrAudioBoostTarget;
    // Only main emits a latched worker failure, before acquiring an audio lock.
    // A raise failure never performs logging/I/O inside a boosted section.
    boostReport(ca);
    AudioBoost* state = boostState(ca);
    if (ca && state && ((char*)lock == ca + CTRPORT_AUDIOBOOST_LOADLOCK_AT ||
                        (char*)lock == ca + CTRPORT_AUDIOBOOST_MSGLOCK_AT)) {
        Thread self = threadGetCurrent();
        int who = self == NULL ? -1
            : self == AUDIOBOOST_FIELD(ca, CTRPORT_AUDIOBOOST_LOADER_AT, Thread) ? 0
            : self == AUDIOBOOST_FIELD(ca, CTRPORT_AUDIOBOOST_OPENER_AT, Thread) ? 1 : -1;
        if (who >= 0) {
            AudioBoost* b = &state[who];
            // A second worker may fail while this worker is already raised.
            // Its existing nesting must still unwind at the outermost exit.
            if (b->depth || !(boostBits(ca) & 1)) {
                if (b->depth++ == 0) {
                    s32 decode = AUDIOBOOST_FIELD(ca, CTRPORT_AUDIOBOOST_PRIORITY_AT, s32), base = 0x3f;
                    s32 ceiling = decode > 0x18 ? decode - 1 : 0x18;
                    b->tls = getThreadLocalStorage();
                    b->system = ca;
                    Result result = svcGetThreadPriority(&base, CUR_THREAD_HANDLE);
                    if (R_SUCCEEDED(result) && base > ceiling)
                        result = svcSetThreadPriority(CUR_THREAD_HANDLE, ceiling);
                    b->raised = R_SUCCEEDED(result) && base > ceiling;
                    b->base = base;
                    if (!R_SUCCEEDED(result))
                        __atomic_fetch_or(boostRoot(ca), 1, __ATOMIC_RELAXED);
                }
            }
        }
    }
    LightLock_Lock(lock);
}

AUDIOBOOST_CODE void CtrAudioBoost_unlock(LightLock* lock) {
    LightLock_Unlock(lock);
    AudioBoost* state = boostState((void*)*ctrAudioBoostTarget);
    if (!state || (state[0].depth == 0 && state[1].depth == 0)) return;
    void* tls = getThreadLocalStorage();
    for (int i = 0; i < 2; i++) {
        AudioBoost* b = &state[i];
        if (b->depth == 0 || b->tls != tls) continue;
        if ((char*)lock != b->system + CTRPORT_AUDIOBOOST_LOADLOCK_AT &&
            (char*)lock != b->system + CTRPORT_AUDIOBOOST_MSGLOCK_AT) return;
        if (--b->depth == 0 && b->raised) {
            b->raised = false;
            svcSetThreadPriority(CUR_THREAD_HANDLE, b->base);
        }
        return;
    }
}
