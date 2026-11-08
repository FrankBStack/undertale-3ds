#include "ctr_open_files.h"

#include <3ds.h>
#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <sys/iosupport.h>

#include "common.h"
#include "log.h"

#define TRACKED_MAX 96
#define TRACKED_PATH 88
#define FAILURES_LOGGED 5
#define KEEPERS_MAX 8
// Below this many files open, kept-open caches may keep one more. Each cache
// file opened again costs about 10 ms on an Old 3DS, so only a crowd sheds.
// On an Old 3DS an open failed with 18 open (Chapter 4's Titan climb, with
// 16 here): the game's own opens (music streams, sounds, the chapter's
// files) come on top of what the caches keep, so this leaves them six.
#define DEFAULT_LIMIT 12
// An open that failed waits this long at most for other threads' caches to
// close their files, trying again each time one does, and no longer once
// every cache asked has.
#define SHED_WAIT_MS 150
#define SHED_STEP_MS 2
#define HANDLES_BELIEVABLE 12
#define HANDLE_PROBE_MAX 4096

typedef struct {
    const void* key; // the devoptab's file or folder state
    bool folder;
    char path[TRACKED_PATH];
} OpenEntry;

typedef struct {
    void (*shed)(void* owner);
    void (*wake)(void* owner);
    void* owner;
    Thread thread; // the thread that closes its files (nullptr: the main thread)
    bool used;
    bool pending; // asked to shed at its thread's next CtrOpenFiles_poll
    // One more as its thread takes a request to shed (under lock) and one
    // more as it has closed its files, so odd while it sheds (change racefix;
    // in what was padding, so Keeper keeps its 20 bytes).
    uint8_t seq;
} Keeper;

// What a request to shed waits for (change racefix): need[i], the seq keeper i
// reaches once it has finished a shed it took after the request. The table's
// address comes along so that the late check below doesn't name `keepers`
// (naming it there reorders this file's statics).
typedef struct {
    const Keeper* keepers;
    uint8_t need[KEEPERS_MAX];
} ShedRequest;

static LightLock lock;
static OpenEntry entries[TRACKED_MAX];
static int files, folders, peak;
static int untracked; // opened while the list was full
static int failuresLogged;
static int limit = DEFAULT_LIMIT;
static int fakeLimit; // open_files_fake_max: refuse opens past this many, for testing (0: off)
static Keeper keepers[KEEPERS_MAX];
static volatile uint32_t sheds; // sheds finished, all caches; unread since change racefix (Keeper.seq), kept so the statics keep their places
static devoptab_t tracked;
static const devoptab_t* real;
static __thread int quietDepth; // inside CtrOpenFiles_beginCacheOpen

// change racefix (late text): those keepers in `asked` that have finished the shed req->need names for them (seq
// wraps at 256; a request lives 150 ms at most).
__attribute__((noinline, optimize("Os"), section(".text.racefix_late"))) static unsigned racefixShed(const ShedRequest* req, unsigned asked) {
    unsigned shed = 0;
    for (int i = 0; KEEPERS_MAX > i; i++) {
        if (0 <= (int8_t) (__atomic_load_n(&req->keepers[i].seq, __ATOMIC_ACQUIRE) - req->need[i])) shed |= 1u << i;
    }
    return shed & asked;
}

// Under lock.
static void add(const void* key, bool folder, const char* path) {
    for (int i = 0; TRACKED_MAX > i; i++) {
        if (entries[i].key != nullptr) continue;
        entries[i].key = key;
        entries[i].folder = folder;
        strncpy(entries[i].path, path, TRACKED_PATH - 1);
        entries[i].path[TRACKED_PATH - 1] = '\0';
        return;
    }
    untracked++;
}

// Under lock. False for one opened before the list was kept.
static bool removeKey(const void* key) {
    for (int i = 0; TRACKED_MAX > i; i++) {
        if (entries[i].key == key) {
            entries[i].key = nullptr;
            return true;
        }
    }
    if (0 == untracked) return false;
    untracked--;
    return true;
}

static bool isMissing(int err) {
    return err == ENOENT || err == EEXIST || err == ENOTDIR || err == EISDIR;
}

bool CtrOpenFiles_missing(int err) {
    return isMissing(err);
}

// The first few opens that fail for a reason other than a missing file, with
// what was open then.
static void noteFailure(const char* what, const char* path, int err) {
    if (isMissing(err)) return;
    LightLock_Lock(&lock);
    bool log = FAILURES_LOGGED > failuresLogged;
    if (log) failuresLogged++;
    LightLock_Unlock(&lock);
    if (!log) return;
    logWarn("Files: could not open %s %s (errno %d)\n", what, path, err);
    // The FS service's own answer, which errno doesn't keep.
    if (strncmp(path, "sdmc:/", 6) == 0) {
        FS_Archive sd = 0;
        Handle file = 0;
        Result archive = FSUSER_OpenArchive(&sd, ARCHIVE_SDMC, fsMakePath(PATH_EMPTY, ""));
        Result opened = archive;
        if (R_SUCCEEDED(archive)) {
            if (strcmp(what, "file") == 0) opened = FSUSER_OpenFile(&file, sd, fsMakePath(PATH_ASCII, path + 5), FS_OPEN_READ, 0);
            else opened = FSUSER_OpenDirectory(&file, sd, fsMakePath(PATH_ASCII, path + 5));
            if (R_SUCCEEDED(opened) && strcmp(what, "file") == 0) FSFILE_Close(file);
            else if (R_SUCCEEDED(opened)) FSDIR_Close(file);
            FSUSER_CloseArchive(sd);
        }
        logWarn("Files: opened again through FS: archive %08lX, %s %08lX\n", (unsigned long) archive, what, (unsigned long) opened);
    }
    CtrOpenFiles_log("then", true);
}

// Runs the calling thread's caches that were asked to shed. Never under lock.
static int shedOwn(void) {
    Thread self = threadGetCurrent();
    for (int i = 0; KEEPERS_MAX > i; i++) {
        LightLock_Lock(&lock);
        // Field copies, not a whole-Keeper copy: seq is stored unlocked by its owner thread (R172b).
        void (*shed)(void*) = keepers[i].shed;
        void* owner = keepers[i].owner;
        bool run = keepers[i].used && keepers[i].pending && keepers[i].thread == self;
        if (run) {
            __atomic_store_n(&keepers[i].pending, false, __ATOMIC_RELAXED); // read unlocked by __wrap_CtrOpenFiles_poll
            __atomic_store_n(&keepers[i].seq, (uint8_t) (keepers[i].seq + 1), __ATOMIC_RELAXED); // racefixShed reads it unlocked
        }
        LightLock_Unlock(&lock);
        if (!run) continue;
        shed(owner);
        __atomic_store_n(&keepers[i].seq, (uint8_t) (keepers[i].seq + 1), __ATOMIC_RELEASE); // its thread's own byte
        sheds++;
    }
    return 0; // unused; void would change how the compiler lays out this file's statics
}

// Asks every cache to close its kept-open files. Those of the calling thread
// close them now unless it is opening a cache file itself (its caller may
// hold one); the others at their thread's next poll. Returns which caches
// were asked (bit i: keeper i), and for each one in req->need[i] the value
// keepers[i].seq reaches once that cache has finished a shed it took after
// this request (those of this thread before this returns).
__attribute__((noinline)) static unsigned askToShed(bool own, ShedRequest* req) {
    // The function keeps its former 244 bytes, so that nothing after it
    // moves: subsection 1 follows the body and its literal pool, zero-filled.
#if defined(__3DS__) && defined(NDEBUG) && !defined(__OPTIMIZE_SIZE__) // the optimized Release layout only
    __asm__(".pushsection .text.askToShed, 1\n.org 244\n.popsection");
#endif
    Thread self = threadGetCurrent();
    unsigned asked = 0;
    req->keepers = keepers;
    LightLock_Lock(&lock);
    for (int i = 0; KEEPERS_MAX > i; i++) {
        Keeper* k = &keepers[i];
        if (!k->used) continue;
        if (k->thread == self && !own) continue;
        __atomic_store_n(&k->pending, true, __ATOMIC_RELEASE); // pairs with __wrap_CtrOpenFiles_poll's acquire
        // A shed running now (odd) may have started too early to see this
        // request: then the one after it.
        uint8_t seq = __atomic_load_n(&k->seq, __ATOMIC_RELAXED); // its thread's shedOwn stores it unlocked
        req->need[i] = seq + 2 + (seq & 1);
        asked |= 1u << i;
        if (k->thread == self) continue;
        // Woken under the lock: a keeper's thread removes it (under the lock)
        // before its owner is freed, so the owner is alive here. After the
        // unlock a stopping tile reader could already be freed
        // (CtrTileReader_stop). A wake only signals an event.
        if (k->wake != nullptr) k->wake(k->owner);
    }
    LightLock_Unlock(&lock);
    if (own) shedOwn();
    return asked;
}

// Whether the open_files_fake_max test setting refuses another open, as the
// FS service does once too many are open.
static bool fakeFull(struct _reent* r) {
    if (0 >= fakeLimit) return false;
    LightLock_Lock(&lock);
    bool full = files + folders >= fakeLimit;
    LightLock_Unlock(&lock);
    if (full) r->_errno = EMFILE;
    return full;
}

__attribute__((noinline)) static int attemptOpen(struct _reent* r, void* fileStruct, const char* path, int flags, int mode) {
    return fakeFull(r) ? -1 : real->open_r(r, fileStruct, path, flags, mode);
}

__attribute__((noinline)) static DIR_ITER* attemptDirOpen(struct _reent* r, DIR_ITER* dirState, const char* path) {
    return fakeFull(r) ? nullptr : real->diropen_r(r, dirState, path);
}

static int openCount(void) {
    LightLock_Lock(&lock);
    int count = files + folders;
    LightLock_Unlock(&lock);
    return count;
}

// Opens through `attempt` and, should that fail with the card's files
// crowded, has the caches close theirs and tries again each time another of
// them has (this thread's at once). Once every cache it asked has finished
// a shed it took after this request, it stops: nothing else it
// waits for frees an open (it used to sleep out the rest of SHED_WAIT_MS,
// twice for cacheFile, whose own caches it doesn't ask). A shed that answered
// another request doesn't count (c26rev r93 F1: counting every shed let a
// second shed of one cache stand in for another cache still to close).
#define RETRY_OPEN(ok, attempt)                                                                   \
    do {                                                                                          \
        if (ok || isMissing(r->_errno)) break;                                                    \
        int failedErrno = r->_errno;                                                              \
        int crowd = openCount();                                                                  \
        bool own = 0 == quietDepth;                                                               \
        ShedRequest req;                                                                          \
        unsigned asked = askToShed(own, &req);                                                    \
        unsigned shed = 0; /* those asked that have shed for this request */                      \
        int waited = 0; /* ms */                                                                  \
        while (!(ok) && asked != shed && SHED_WAIT_MS > waited) {                                 \
            unsigned now = racefixShed(&req, asked);                                              \
            if (now == shed) {                                                                    \
                svcSleepThread(SHED_STEP_MS * 1000000ll);                                         \
                waited += SHED_STEP_MS;                                                           \
                continue;                                                                         \
            }                                                                                     \
            shed = now;                                                                           \
            attempt;                                                                              \
        }                                                                                         \
        if (ok) logInfo("Files: opened %s once kept-open files were closed (%d were open, errno " \
                        "%d; %.0f ms)\n", path, crowd, failedErrno, (double) waited);             \
    } while (0)

static int trackedOpen(struct _reent* r, void* fileStruct, const char* path, int flags, int mode) {
    // Keeps its former 560 bytes (as askToShed).
#if defined(__3DS__) && defined(NDEBUG) && !defined(__OPTIMIZE_SIZE__) // the optimized Release layout only
    __asm__(".pushsection .text.trackedOpen, 1\n.org 560\n.popsection");
#endif
    int fd = attemptOpen(r, fileStruct, path, flags, mode);
    RETRY_OPEN(0 <= fd, fd = attemptOpen(r, fileStruct, path, flags, mode));
    if (0 > fd) {
        // The caller tells a missing file from a crowded card by errno.
        int err = r->_errno;
        noteFailure("file", path, err);
        r->_errno = err;
        return fd;
    }
    LightLock_Lock(&lock);
    add(fileStruct, false, path);
    files++;
    if (files + folders > peak) peak = files + folders;
    LightLock_Unlock(&lock);
    return fd;
}

static int trackedClose(struct _reent* r, void* fileStruct) {
    LightLock_Lock(&lock);
    if (removeKey(fileStruct)) files--;
    LightLock_Unlock(&lock);
    return real->close_r(r, fileStruct);
}

static DIR_ITER* trackedDirOpen(struct _reent* r, DIR_ITER* dirState, const char* path) {
    // Keeps its former 576 bytes (as askToShed).
#if defined(__3DS__) && defined(NDEBUG) && !defined(__OPTIMIZE_SIZE__) // the optimized Release layout only
    __asm__(".pushsection .text.trackedDirOpen, 1\n.org 576\n.popsection");
#endif
    DIR_ITER* dir = attemptDirOpen(r, dirState, path);
    RETRY_OPEN(dir != nullptr, dir = attemptDirOpen(r, dirState, path));
    if (dir == nullptr) {
        int err = r->_errno;
        noteFailure("folder", path, err);
        r->_errno = err;
        return dir;
    }
    LightLock_Lock(&lock);
    add(dirState, true, path);
    folders++;
    if (files + folders > peak) peak = files + folders;
    LightLock_Unlock(&lock);
    return dir;
}

static int trackedDirClose(struct _reent* r, DIR_ITER* dirState) {
    LightLock_Lock(&lock);
    if (removeKey(dirState)) folders--;
    LightLock_Unlock(&lock);
    return real->dirclose_r(r, dirState);
}

void CtrOpenFiles_track(void) {
    if (real != nullptr) return;
    const devoptab_t* sd = GetDeviceOpTab("sdmc");
    if (sd == nullptr || sd->open_r == nullptr || sd->close_r == nullptr) return;
    LightLock_Init(&lock);
    real = sd;
    tracked = *sd;
    tracked.open_r = trackedOpen;
    tracked.close_r = trackedClose;
    if (sd->diropen_r != nullptr && sd->dirclose_r != nullptr) {
        tracked.diropen_r = trackedDirOpen;
        tracked.dirclose_r = trackedDirClose;
    }
    // Replaces the device of the same name in place.
    if (0 > AddDevice(&tracked)) real = nullptr;
}

void CtrOpenFiles_setLimit(int max, int fakeMax) {
    if (0 < max) limit = max;
    fakeLimit = fakeMax;
    if (0 < fakeLimit) logInfo("Files: kept-open files close once %d are open; opens past %d refused (test)\n", limit, fakeLimit);
    else logInfo("Files: kept-open files close once %d are open\n", limit);
}

bool CtrOpenFiles_mayKeep(void) {
    if (real == nullptr) return true;
    LightLock_Lock(&lock);
    bool may = limit > files + folders;
    LightLock_Unlock(&lock);
    return may;
}

int CtrOpenFiles_addKeeper(void (*shed)(void* owner), void (*wake)(void* owner), void* owner) {
    // Keeps its former 156 bytes (as askToShed): written whole now, seq too,
    // which came out shorter.
#if defined(__3DS__) && defined(NDEBUG) && !defined(__OPTIMIZE_SIZE__) // the optimized Release layout only
    __asm__(".pushsection .text.CtrOpenFiles_addKeeper, 1\n.org 156\n.popsection");
#endif
    if (real == nullptr) return -1;
    LightLock_Lock(&lock);
    int id = -1;
    for (int i = 0; KEEPERS_MAX > i && 0 > id; i++) {
        if (keepers[i].used) continue;
        // seq starts again at 0. A request still waiting on the keeper that
        // last had this slot (removed within its 150 ms) then waits it out,
        // as it would for a removed keeper anyway, or stops one wait early
        // if its need was past 128.
        // Field by field (change creddodge ofpoll): __wrap_CtrOpenFiles_poll reads thread, pending and used without
        // the lock, so those are atomic stores, used last.
        Thread self = threadGetCurrent();
        Keeper* k = &keepers[i];
        k->shed = shed;
        k->wake = wake;
        k->owner = owner;
        __atomic_store_n(&k->seq, (uint8_t) 0, __ATOMIC_RELAXED);
        __atomic_store_n(&k->thread, self, __ATOMIC_RELAXED);
        __atomic_store_n(&k->pending, false, __ATOMIC_RELAXED);
        __atomic_store_n(&k->used, true, __ATOMIC_RELAXED);
        id = i;
    }
    LightLock_Unlock(&lock);
    return id;
}

void CtrOpenFiles_removeKeeper(int id) {
    if (0 > id || KEEPERS_MAX <= id) return;
    LightLock_Lock(&lock);
    __atomic_store_n(&keepers[id].used, false, __ATOMIC_RELAXED); // read unlocked by __wrap_CtrOpenFiles_poll
    LightLock_Unlock(&lock);
}

void CtrOpenFiles_poll(void) {
    if (real == nullptr) return;
    shedOwn();
}

void CtrOpenFiles_beginCacheOpen(void) {
    quietDepth++;
}

void CtrOpenFiles_endCacheOpen(void) {
    quietDepth--;
}

// Azahar answers svcGetSystemInfo's type 0x20000; a console doesn't.
static bool onEmulator(void) {
    s64 out = 0;
    return R_SUCCEEDED(svcGetSystemInfo(&out, 0x20000, 0));
}

// How many more handles the process's table takes, found by filling it with
// copies of the process handle (then closed). Only where the kernel won't
// say how many are in use (Azahar): meanwhile every other thread's opens
// would fail.
static int freeHandles(void) {
    static Handle probe[HANDLE_PROBE_MAX];
    int count = 0;
    while (HANDLE_PROBE_MAX > count && R_SUCCEEDED(svcDuplicateHandle(&probe[count], CUR_PROCESS_HANDLE))) count++;
    for (int i = 0; count > i; i++) svcCloseHandle(probe[i]);
    return count;
}

void CtrOpenFiles_log(const char* where, bool list) {
    // svcGetProcessInfo 4: kernel handles in use; 5: the most at once. Azahar
    // answers with junk, so only a believable count is shown (a process holds
    // a dozen or more for its threads and services alone).
    s64 handles = -1, handlesPeak = -1;
    if (R_FAILED(svcGetProcessInfo(&handles, CUR_PROCESS_HANDLE, 4)) || HANDLES_BELIEVABLE > handles || handles > 0x10000) handles = -1;
    if (R_FAILED(svcGetProcessInfo(&handlesPeak, CUR_PROCESS_HANDLE, 5)) || HANDLES_BELIEVABLE > handlesPeak || handlesPeak > 0x10000) {
        handlesPeak = -1;
    }
    char kernel[64];
    if (0 <= handles) snprintf(kernel, sizeof(kernel), "%d kernel handles (most %d)", (int) handles, (int) handlesPeak);
    else if (onEmulator()) snprintf(kernel, sizeof(kernel), "room for %d more kernel handles", freeHandles());
    else snprintf(kernel, sizeof(kernel), "kernel handles unknown");
    if (real == nullptr) {
        logInfo("Files (%s): %s; SD card opens not tracked\n", where, kernel);
        return;
    }
    LightLock_Lock(&lock);
    int f = files, d = folders, p = peak, u = untracked;
    LightLock_Unlock(&lock);
    logInfo("Files (%s): %d files and %d folders open on the SD card (most %d), %s\n", where, f, d, p, kernel);
    if (!list) return;
    // One entry at a time: the threads that log a failure have small stacks.
    for (int i = 0; TRACKED_MAX > i; i++) {
        OpenEntry e;
        LightLock_Lock(&lock);
        e = entries[i];
        LightLock_Unlock(&lock);
        if (e.key != nullptr) logInfo("Files:   %s%s\n", e.folder ? "folder " : "", e.path);
    }
    if (0 < u) logInfo("Files:   and %d more not listed\n", u);
}


// change creddodge ofpoll (late text): every CtrOpenFiles_poll (main's each frame, and the loader, tile reader and
// audio opener threads') looks at the keepers without the lock first and goes on to shedOwn only when one of the
// calling thread's keepers is pending. shedOwn took the lock once a keeper, every frame, and on the o2ds the main
// thread waited 19-22 ms there for an audio thread preempted while holding it (creddodge bfprobe, 11-04). Only
// shedOwn clears `pending`, under the lock, after it checks it again, so this check cannot shed early or twice; a
// flag set after this read is seen at the thread's next poll, as one set just after the poll always was. Every
// write of the three fields read here is an atomic store (askToShed's request a release store, which this acquire
// pairs with; the others under the lock), so the unlocked reads race with no plain access (review R172 F1). Reached
// through --wrap; the real poll is unchanged.
void __real_CtrOpenFiles_poll(void);
__attribute__((optimize("Os"), section(".text_ofpoll"))) void __wrap_CtrOpenFiles_poll(void) {
    Thread self = threadGetCurrent();
    for (int i = 0; KEEPERS_MAX > i; i++) {
        if (!__atomic_load_n(&keepers[i].pending, __ATOMIC_ACQUIRE)) continue;
        if (__atomic_load_n(&keepers[i].used, __ATOMIC_RELAXED) && __atomic_load_n(&keepers[i].thread, __ATOMIC_RELAXED) == self) {
            __real_CtrOpenFiles_poll();
            return;
        }
    }
}
