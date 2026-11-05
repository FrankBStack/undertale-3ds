// overlayread (change auditfixe3, SCOURSOL3-002 + R195b + R195c + R195d, both games): a whole-file read returns the
// whole file, says the file isn't there only when the card's open of it says so, or stops the game; it never hands the
// game part of a file, nor a file that is there as missing.
//
// engine/src/overlay_file_system.c's readFileText and readFileBinary seek to the end, take ftell as the size, seek
// back and fread, and report success with whatever fread returned: an SD read error part way gave the game a prefix
// of file0 or undertale.ini as if it were the whole file, and a failed seek or ftell went unnoticed too (a size of -1
// became a 0-byte allocation). When the save folder couldn't be listed at boot (indexed false: an SD error on opendir)
// every read of ctr_file_system.c goes to the overlay (ctrReadFileText and ctrReadFileBinary), and so does a read of
// any name that isn't a plain file of the save folder. main.c's bundle overlay reads go there as well.
//
// Reporting a failed read as failure is no answer either (R195, c26rev6 NO-GO): the callers take nullptr / false as
// "no such file". ctrReadFile* cache it as missing (cfs->exists, knownMissing), file_exists then says false, ini_open
// parses an empty INI whose next changed ini_close writes over the real one (and the update after that drops the
// .bak), file_text_open_read gives an empty handle, and file_bin_open(name, 2) and its close write 0 bytes over it. The
// same held for ctr_file_system.c's own readWhole (R195c): a save the index lists but the writer hadn't preloaded is
// read there, and any failure, an fopen refused with EIO or a crowded card's FS OutOfResource among them, came back as
// "missing". So every whole-file read goes through overlayreadPath: the overlay's, and those two of ctr_file_system.c
// (readSaveFile and readIndexed's bundle read, through CtrFileSystem_readWhole, from their first open: R195d).
//
// - "Missing" is decided at the source (R195d, c26rev R195c): only the operation's own fopen of the file says it, by the
//   errno taken right after that fopen returns null, before anything else can set errno. A not-found errno is ENOENT
//   or ENOTDIR (libctru's archive_dev.c maps the SD card's two not-found results to ENOENT), EISDIR, or one that says no
//   such name can exist (EINVAL, ENAMETOOLONG, EILSEQ: libctru's invalid-path answers). libctru passes every result it
//   doesn't know through as errno, so an I/O error, a card gone from its slot or the FS service's OutOfResource
//   (0xD860466C, docs/3ds-hardware.md) is never one of those; EEXIST isn't either (a read-only open has no business
//   giving it). Nothing is inferred after the fact: a failure of any step after a successful open (seek, ftell, fread,
//   fclose) is a failed read whatever errno it leaves (finding 2: readWhole's errno after a whole read said nothing about
//   its fopen), and a failed stat proves nothing (finding 1: libctru's archive_stat tries a file open, then on any
//   failure a folder open, and reports only the folder open's answer, so a refused file open can come back as
//   "not found"). A stat is believed only when it finds something: after an fopen fails for another reason, a folder
//   there means no file (the FS service's answer for that isn't one libctru maps).
// - The overlay's choice of copy is made the same way: the save folder's copy is opened first, and only that open's
//   not-found answer, on the operation's first attempt, sends it to the bundle folder's copy (a folder in the save
//   folder doesn't, as the overlay's stat-based choice didn't). overlay_file_system.c's resolveForRead chose with a stat.
// - "Missing" is believed only as the first answer (c26rev R195b finding 1): once an attempt has failed, a missing
//   answer is one more failed attempt, and the path being tried is the one tried again, so a short read followed by a
//   reopen that says ENOENT can't come back as "missing" (nor read the bundle folder's copy instead).
// - A complete read (both seeks, a size from 0 to INT32_MAX, fread returned every byte) is the file, whatever ferror or
//   fclose say after it: the bytes are all there, as the base overlay took them (R195b (a)).
// - Anything else is tried again, and if it still fails the game stops on main.c's error screen (CtrMain_fatalScreen,
//   the non-returning screen "Saving failed" uses), which writes the saves already queued and exits: the caller never
//   gets to save defaults over the file (R195b (b)). A file that opened but couldn't be read whole gets
//   OVERLAYREAD_TRIES tries OVERLAYREAD_GAP_NS apart (a card hiccup). A file that couldn't be opened gets
//   OVERLAYREAD_OPEN_TRIES tries OVERLAYREAD_OPEN_GAP_NS apart, about 1 s of sleeps (sleeps and attempts are bounded,
//   not the SD service's own time): a crowded card frees up as the other threads' kept-open files close.
//   ctr_open_files.c's sdmc open already asks every cache to close its kept-open files and waits up to 150 ms for them
//   inside each open that fails for a reason other than a missing file (RETRY_OPEN), so each of those tries has freed
//   what the caches hold; what is left open is the game's own (music streams, sounds). Only the main thread stops: a
//   read on another thread (an external texture page, ctr_textures.c; neither game has one) fails after its first try,
//   as before, since that screen runs the APT loop.
// - The overlay's fileExists answers by the same rule (overlayreadLook): a stat that finds something is a yes, and
//   after a failed stat the fopen decides, so file_exists can't call a save that is there missing either.
// Each failed attempt frees its buffer and closes the file before the next.
//
// How: OverlayFileSystem_create is reached through the linker (-Wl,--wrap=OverlayFileSystem_create, CMakeLists.txt;
// its callers, ctr_file_system.c and main.c, only change their branch target). The wrap copies the overlay's vtable
// once into late bss, points its whole-file readers and fileExists here, and gives each new overlay that copy;
// nothing in overlay_file_system.c changes. ctr_file_system.c's CtrFileSystem_readStrict (its readWhole, kept for the
// caller count readWhole's code was built with) has no caller now. No string literals and no header allocator
// (safeMalloc's inline body brings its message and __FILE__ as mergeable strings, docs/3ds-hardware.md "Mergeable late
// strings can move original constants in earlier inputs"): the messages are named arrays. Code, constants and statics
// are late (late_reserve.ld: .text_overlayread, .rodata_overlayread, .bss.overlayread_late).
#include <3ds.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "ctr_file_system.h" // CtrFileSystem_readWhole, for readSaveFile and readIndexed
#include "log.h"
#include "overlay_file_system.h"

#ifdef __3DS__
#define OVERLAYREAD_CODE __attribute__((noinline, section(".text_overlayread")))
#define OVERLAYREAD_RO __attribute__((section(".rodata_overlayread")))
#define OVERLAYREAD_BSS __attribute__((section(".bss.overlayread_late")))
#else // tools/analysis/test_overlay_reads.py
#define OVERLAYREAD_CODE __attribute__((noinline))
#define OVERLAYREAD_RO
#define OVERLAYREAD_BSS
#endif
#define OVERLAYREAD_TRIES 3
#define OVERLAYREAD_GAP_NS (20ll * 1000000ll)
#define OVERLAYREAD_OPEN_TRIES 10
#define OVERLAYREAD_OPEN_GAP_NS (100ll * 1000000ll)

// What one attempt found.
enum { OVERLAYREAD_READ, OVERLAYREAD_ABSENT, OVERLAYREAD_NO_OPEN, OVERLAYREAD_NO_READ };

OverlayFileSystem* __real_OverlayFileSystem_create(const char* bundlePath, const char* savePath);
OverlayFileSystem* __wrap_OverlayFileSystem_create(const char* bundlePath, const char* savePath);
// main.c's fatalScreen (a global name for it at the end of main.c): shows the message, waits for START, exits.
void CtrMain_fatalScreen(const char* fmt, ...) __attribute__((noreturn));

static FileSystemVtable overlayreadVtable OVERLAYREAD_BSS;
static FileSystemVtable* overlayreadOriginal OVERLAYREAD_BSS;
static const char overlayreadNoMemory[] OVERLAYREAD_RO = "FATAL: malloc(%zu) failed in an overlay read\n";
static const char overlayreadFailed[] OVERLAYREAD_RO = "Files: couldn't %s %s (errno %d) after %d tries\n";
static const char overlayreadOpenVerb[] OVERLAYREAD_RO = "open";
static const char overlayreadReadVerb[] OVERLAYREAD_RO = "read";
static const char overlayreadMode[] OVERLAYREAD_RO = "rb"; // a literal would be a mergeable string
// The error screen's text (3DS-only wording; the log console is 40 columns).
static const char overlayreadUnreadable[] OVERLAYREAD_RO =
    "Couldn't read %s\nfrom the SD card. It wasn't changed.\nTurn the system off, check the card,\nand try again.\n";

OVERLAYREAD_CODE static void* overlayreadAlloc(size_t size) {
    void* data = malloc(size);
    if (data == nullptr) { // safeMalloc's end, without its inline strings
        logError(overlayreadNoMemory, size);
        abort();
    }
    return data;
}

// Whether a failed fopen says nothing is there (see the top). EEXIST isn't one (c26rev R195c finding 3): a read-only
// open has no business giving it, so it is a failure like any other answer this list doesn't name.
OVERLAYREAD_CODE static bool overlayreadAbsent(int err) {
    return err == ENOENT || err == ENOTDIR || err == EISDIR || err == EINVAL || err == ENAMETOOLONG || err == EILSEQ;
}

OVERLAYREAD_CODE static char* overlayreadJoin(const char* dir, const char* name) {
    size_t dirLen = strlen(dir), nameLen = strlen(name);
    char* full = overlayreadAlloc(dirLen + nameLen + 1);
    memcpy(full, dir, dirLen);
    memcpy(full + dirLen, name, nameLen + 1);
    return full;
}

// Where the overlay reads relativePath from (resolveForRead's rule, without its stat): the path to try first, to free,
// and in *outBundle (to free; null when there is no other) the bundle folder's copy, to be tried only if the first
// path's own open says nothing is there. backslashes become slashes; an absolute or already resolved path is used as
// it is; otherwise the save folder's copy comes first.
OVERLAYREAD_CODE static char* overlayreadResolve(OverlayFileSystem* ofs, const char* relativePath, char** outBundle) {
    size_t len = strlen(relativePath);
    char* normalized = overlayreadAlloc(len + 1);
    for (size_t i = 0; len >= i; i++) normalized[i] = relativePath[i] == '\\' ? '/' : relativePath[i];
    *outBundle = nullptr;
    if (normalized[0] == '/' || strncmp(normalized, ofs->savePath, strlen(ofs->savePath)) == 0 ||
        strncmp(normalized, ofs->bundlePath, strlen(ofs->bundlePath)) == 0)
        return normalized;
    *outBundle = overlayreadJoin(ofs->bundlePath, normalized);
    char* saveFull = overlayreadJoin(ofs->savePath, normalized);
    free(normalized);
    return saveFull;
}

// One attempt at the whole file at fullPath, with a NUL after it (in *outData only when OVERLAYREAD_READ).
// OVERLAYREAD_ABSENT only from this attempt's own fopen: its errno, taken before anything else runs, is a not-found one
// (*outErr), or the open failed and a stat then succeeds on a folder (*outErr EISDIR; a stat is believed only when it
// finds something). Every other failure of the open is OVERLAYREAD_NO_OPEN, and any failure after a successful open is
// OVERLAYREAD_NO_READ, whatever errno the seek, read or close leave (c26rev R195c finding 2).
OVERLAYREAD_CODE static int overlayreadOnce(const char* fullPath, int32_t maxSize, uint8_t** outData, int32_t* outSize,
                                            int* outErr) {
    errno = 0;
    FILE* f = fopen(fullPath, overlayreadMode);
    if (f == nullptr) {
        *outErr = errno;
        if (overlayreadAbsent(*outErr)) return OVERLAYREAD_ABSENT;
        // A folder of that name: no file there (the FS service's answer for it isn't one libctru maps).
        struct stat st;
        if (stat(fullPath, &st) != 0 || !S_ISDIR(st.st_mode)) return OVERLAYREAD_NO_OPEN;
        *outErr = EISDIR;
        return OVERLAYREAD_ABSENT;
    }
    long size = fseek(f, 0, SEEK_END) == 0 ? ftell(f) : -1;
    bool ok = 0 <= size && maxSize >= size && fseek(f, 0, SEEK_SET) == 0;
    uint8_t* data = nullptr;
    if (ok) {
        data = overlayreadAlloc((size_t) size + 1);
        ok = fread(data, 1, (size_t) size, f) == (size_t) size;
    }
    *outErr = errno;
    (void) fclose(f); // every byte was read: ferror or a failed close changes nothing
    if (!ok) {
        free(data);
        return OVERLAYREAD_NO_READ;
    }
    data[size] = '\0';
    *outData = data;
    *outSize = (int32_t) size;
    return OVERLAYREAD_READ;
}

// One look for something at fullPath (the overlay's fileExists: files and folders alike): OVERLAYREAD_READ when a stat
// finds it or, the stat having failed, an fopen opens it; OVERLAYREAD_ABSENT only when that fopen's own errno is a
// not-found one; else OVERLAYREAD_NO_OPEN. A failed stat proves nothing (c26rev R195c finding 1: libctru's
// archive_stat answers with its folder open after a refused file open).
OVERLAYREAD_CODE static int overlayreadLook(const char* fullPath, int* outErr) {
    struct stat st;
    if (stat(fullPath, &st) == 0) return OVERLAYREAD_READ;
    errno = 0;
    FILE* f = fopen(fullPath, overlayreadMode);
    *outErr = errno;
    if (f != nullptr) {
        (void) fclose(f);
        return OVERLAYREAD_READ;
    }
    return overlayreadAbsent(*outErr) ? OVERLAYREAD_ABSENT : OVERLAYREAD_NO_OPEN;
}

// After a failed attempt (got, err) on the main thread: stops the game once the tries are used up, else waits for the
// next (hold, the caller's own allocation, is freed before a stop). A read failure gets OVERLAYREAD_TRIES, any other
// OVERLAYREAD_OPEN_TRIES.
OVERLAYREAD_CODE static void overlayreadAgain(const char* path, int got, int err, int tries, void* hold) {
    bool read = got == OVERLAYREAD_NO_READ;
    if (tries >= (read ? OVERLAYREAD_TRIES : OVERLAYREAD_OPEN_TRIES)) {
        logWarn(overlayreadFailed, read ? overlayreadReadVerb : overlayreadOpenVerb, path, err, tries);
        free(hold);
        CtrMain_fatalScreen(overlayreadUnreadable, path);
    }
    svcSleepThread(read ? OVERLAYREAD_GAP_NS : OVERLAYREAD_OPEN_GAP_NS);
}

// The whole file (look false) or whether something is there (look true): true with it, false when it isn't there (or,
// off the main thread, couldn't be read or looked up). On the main thread a file that is there but can't be read stops
// the game. ofs null: path is a full path already (ctr_file_system.c); otherwise a relative one, resolved in ofs.
// The save folder's copy is opened first; only that open's own not-found answer, on the operation's first attempt, sends
// it to the bundle folder's copy (and a folder there doesn't, as the overlay's stat-based choice didn't). A failure is
// sticky for the rest of the operation (c26rev R195b finding 1): after one, a not-found answer is one more failure, and
// the path being tried is the one tried again.
OVERLAYREAD_CODE static bool overlayreadPath(OverlayFileSystem* ofs, const char* path, bool look, int32_t maxSize,
                                             uint8_t** outData, int32_t* outSize) {
    char* bundle = nullptr;
    char* pinned = ofs != nullptr ? overlayreadResolve(ofs, path, &bundle) : nullptr;
    bool suspect = false;
    for (int tries = 1;; tries++) {
        int err = 0;
        int got = OVERLAYREAD_ABSENT;
        for (int pass = 0; got == OVERLAYREAD_ABSENT && 2 > pass; pass++) {
            if (pass == 1) { // the save folder's copy isn't there: the bundle folder's
                if (suspect || bundle == nullptr || err == EISDIR) break;
                free(pinned);
                pinned = bundle;
                bundle = nullptr;
            }
            const char* at = pinned != nullptr ? pinned : path;
            got = look ? overlayreadLook(at, &err) : overlayreadOnce(at, maxSize, outData, outSize, &err);
        }
        if (got == OVERLAYREAD_READ || (got == OVERLAYREAD_ABSENT && !suspect) || threadGetCurrent() != nullptr) {
            free(pinned);
            free(bundle);
            return got == OVERLAYREAD_READ;
        }
        free(bundle);
        bundle = nullptr;
        suspect = true;
        overlayreadAgain(path, got, err, tries, pinned);
    }
}

// ctr_file_system.c's readSaveFile and readIndexed's bundle read: the guarded read from the first open (c26rev R195c
// finding 2: no readWhole first, whose errno can't say which of its steps failed).
OVERLAYREAD_CODE bool CtrFileSystem_readWhole(const char* fullPath, int32_t maxSize, uint8_t** outData,
                                              int32_t* outSize) {
    return overlayreadPath(nullptr, fullPath, false, maxSize, outData, outSize);
}

OVERLAYREAD_CODE static bool overlayreadBinary(FileSystem* fs, const char* relativePath, uint8_t** outData,
                                               int32_t* outSize) {
    return overlayreadPath((OverlayFileSystem*) fs, relativePath, false, INT32_MAX, outData, outSize);
}

OVERLAYREAD_CODE static char* overlayreadText(FileSystem* fs, const char* relativePath) {
    uint8_t* data = nullptr;
    int32_t size = 0;
    return overlayreadBinary(fs, relativePath, &data, &size) ? (char*) data : nullptr;
}

// The overlay's fileExists, answered as the reads are (c26rev R195c finding 1: the same rule, no negative answer from a
// stat).
OVERLAYREAD_CODE static bool overlayreadExists(FileSystem* fs, const char* relativePath) {
    return overlayreadPath((OverlayFileSystem*) fs, relativePath, true, 0, nullptr, nullptr);
}

OVERLAYREAD_CODE OverlayFileSystem* __wrap_OverlayFileSystem_create(const char* bundlePath, const char* savePath) {
    OverlayFileSystem* ofs = __real_OverlayFileSystem_create(bundlePath, savePath);
    if (overlayreadOriginal == nullptr) {
        overlayreadOriginal = ofs->base.vtable;
        overlayreadVtable = *ofs->base.vtable;
        overlayreadVtable.readFileText = overlayreadText;
        overlayreadVtable.readFileBinary = overlayreadBinary;
        overlayreadVtable.fileExists = overlayreadExists;
    }
    if (ofs->base.vtable == overlayreadOriginal) ofs->base.vtable = &overlayreadVtable;
    return ofs;
}
