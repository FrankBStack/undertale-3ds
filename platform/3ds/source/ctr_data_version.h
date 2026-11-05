#pragma once

#include <stdbool.h>

typedef enum CtrDataVersionResult {
    CTR_DATA_KNOWN,
    CTR_DATA_UNKNOWN,
    CTR_DATA_UNREADABLE
} CtrDataVersionResult;

// Boot/chapter-load only. Receipt identity: revision, full path, size, stat time and bound archive time.
// A trusted builder receipt is not an independent per-boot content proof (see builder-version-receipts.md).
// Cache failure never prevents checking or running. progress keeps the watchdog alive.
CtrDataVersionResult CtrDataVersion_check(const char* path, const char* game, const char* part,
                                        const char* cachePath, void (*progress)(void), bool* cached, char digest[65]);

// datarefuse (playblocker #8): an UNDERTALE build knows only the data.win it was built from. build.sh passes that
// file's size (CTRPORT_DATA_SIZE, CMakeLists.txt) after tools/aot/data_versions.py checked it; every other row of
// the tables (data_versions.inc) gets its size with the lowest bit flipped. A row matches only a file of its size
// whose SHA-256 is its digest, and the digest is that of a file of the row's real size, so such a row matches nothing.
// The flip, not a 0, keeps the code that reads the tables as it was: GCC folds a 0 into the late table's size compare
// (8 B shorter, and every later late function moved). Without it (DELTARUNE, or no data found at build time) all rows
// stay as they are.
#ifdef CTRPORT_DATA_SIZE
#define DATA_VERSION_SIZE(size) ((size) == CTRPORT_DATA_SIZE ? (size) : (size) ^ 1ULL)
#else
#define DATA_VERSION_SIZE(size) (size)
#endif
