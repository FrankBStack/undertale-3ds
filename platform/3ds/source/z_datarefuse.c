// datarefuse (change auditfixe, playblocker #8; R215c, maintainer 11-05: "if people want to try hard to put their custom
// data.win files in, thats fine with me. lets not stop the techy people ... i just dont want the BUILDER to accept a
// flakey data.win or non official game files"): the builder takes only an unmodified Steam or GOG data.win
// (tools/aot/data_versions.py --build-input). On the console, UNDERTALE warns about any other data.win and continues
// once the player presses A; only a data.win that can't be read stops.
//
// main.c's checkDataVersion logs the SHA-256 check and, when the file isn't known or couldn't be read, posts its one
// setup notice. For UNDERTALE, CMakeLists.txt points that one call here instead (CtrNotice_report=CtrDataRefuse_report
// on main.c only: main.c's code changes only its branch target). The tables know only the build's own input
// (DATA_VERSION_SIZE, ctr_data_version.h), so another Steam/GOG copy is unknown as well: the RomFS tables (offkill's
// object numbers, dskip, the font and smoothing verdicts) are made from that file.
//
// Unknown file: the log gets an "UNSUPPORTED data.win sha256=..." line, and every crash and hang report starts with the
// same line: crash.txt (a fatal or out-of-memory stop, and the lab guard's crash, failure and hang report) and each
// report in hang.txt (the writers' file calls come here, below). main.c's setup notice screen shows the warning below with "Press A to continue." Its dismissal
// is remembered in settings.ini for that file (the notice's key holds the SHA-256 and the path), as for every setup
// notice: a different file warns again. Runs with no one at the console (lab, bench, shots) log the notice and go on,
// as before. The session never applies offkill.bin/offdoom.bin (raw build-input object and variable numbers;
// __wrap_OffKill_roomChange below). The other RomFS tables check the file's key, bounds or code before use and fall
// back (change scoursol1); Old's dskip key (runner.c) indexes nothing: it only compares an instance's object and depth,
// so it stays on.
//
// Read error ("Could not verify data.win"): main.c's error screen (CtrMain_fatalScreen), which argcrash paints with
// its data-file title; the message (unchanged since X), in log.txt and crash.txt, says to copy data.win again.
//
// Layout (R243b): every late address the R215 build (A) had stays put. CtrDataRefuse_report keeps A's 44 B slot in
// .text_datarefuse, ahead of GOG's late code, as a branch to CtrDataRefuse_warn; the code is in .text_datarefuse_warn,
// after GOG's (late_reserve.ld; AFTER_GOGUT in tools/release/test_gogut_late_order.py). The late constants keep A's
// two (the mismatch stop's text is a never-read placeholder of its size now), the new ones follow in
// .rodata.datarefuse_warn, and the statics are last in late bss.
#if defined(ENABLE_WAD16) && (defined(__3DS__) || defined(DATAREFUSE_HOST_TEST))
#include <stdio.h>
#include <string.h>

#ifdef __3DS__
#include <3ds.h>
#else
#include "datarefuse_host_fs.h" // tools/analysis/test_datarefuse.py's stand-ins for the FS calls
#endif
#include "ctr_notice.h"
#include "log.h"

void CtrMain_fatalScreen(const char* fmt, ...) __attribute__((noreturn));

#define DATAREFUSE_CONST __attribute__((section(".rodata.datarefuse_late")))
#define DATAREFUSE_WARN_CONST __attribute__((section(".rodata.datarefuse_warn")))
#define DATAREFUSE_CODE __attribute__((noinline, section(".text_datarefuse_warn")))
#define DATAREFUSE_BSS __attribute__((section(".bss.datarefuse_late")))
// A's mismatch stop text (305 B), which nothing shows since R215c: zeros of the same size, never read, so A's late
// constants keep their places (RULES: a removed constant keeps a placeholder).
__attribute__((used)) static const char datarefuseMismatch[305] DATAREFUSE_CONST = { 0 };
static const char datarefuseUnreadable[] DATAREFUSE_CONST =
    "%s: %s\n"
    "data.win couldn't be read to check it. Copy data.win to\n"
    "the SD card again, then start the game again.\n";
// The setup notice's advice (3DS-only text; at most 191 characters and 38 a line, the bottom screen's console).
static const char datarefuseAdvice[] DATAREFUSE_WARN_CONST =
    "This isn't the data.win this game\n"
    "was built from, so it may crash or\n"
    "glitch. To be safe, run the builder\n"
    "again with your Steam or GOG copy.";
static const char datarefuseMarkFormat[] DATAREFUSE_WARN_CONST =
    "UNSUPPORTED data.win sha256=%.64s: not the file this build was made from\n";
static const char datarefuseLine[] DATAREFUSE_WARN_CONST = "%s";

// The line above with the file's SHA-256, for crash and hang reports; empty while the file is known. Set once (main.c
// checks data.win once a boot) and published whole: the line from its second byte on is written first, then its first
// byte is stored with release order. Report writers load that byte with acquire order (CtrDataRefuse_reportWrite), so a
// report on another thread sees either no line or all of it, and nothing locks, so a crash can't strand a lock.
static char datarefuseMark[144] DATAREFUSE_BSS;

// main.c's call (through CtrDataRefuse_report's old slot): kind is "Unknown data.win (<SHA-256>)" or "Could not verify
// data.win"; the advice is DELTARUNE's.
void CtrDataRefuse_warn(const char* kind, const char* path, const char* advice);
DATAREFUSE_CODE void CtrDataRefuse_warn(const char* kind, const char* path, const char* advice) {
    (void) advice;
    if (kind[0] == 'C') CtrMain_fatalScreen(datarefuseUnreadable, kind, path);
    if (datarefuseMark[0] == '\0') {
        const char* digest = strchr(kind, '(');
        snprintf(datarefuseMark + 1, sizeof(datarefuseMark) - 1, datarefuseMarkFormat + 1,
                 digest != NULL ? digest + 1 : kind);
        __atomic_store_n(&datarefuseMark[0], datarefuseMarkFormat[0], __ATOMIC_RELEASE);
    }
    logWarn(datarefuseLine, datarefuseMark);
#ifdef DATAREFUSE_WARN_TEST
    void CtrDataRefuse_armTest(void);
    CtrDataRefuse_armTest();
#endif
    CtrNotice_report(kind, path, datarefuseAdvice);
}

#ifdef __3DS__
// A's CtrDataRefuse_report, 44 B where A had it (late text before GOG's code): main.c's call lands here and branches to
// CtrDataRefuse_warn. The rest of the slot is filler (udf) that nothing runs.
__asm__(".pushsection .text_datarefuse, \"ax\", %progbits\n"
        "\t.balign 4\n"
        "\t.global CtrDataRefuse_report\n"
        "\t.type CtrDataRefuse_report, %function\n"
        "\t.arm\n"
        "CtrDataRefuse_report:\n"
        "\tb CtrDataRefuse_warn\n"
        "\t.fill 10, 4, 0xe7f000f0\n"
        "\t.size CtrDataRefuse_report, . - CtrDataRefuse_report\n"
        "\t.popsection\n");
#else
void CtrDataRefuse_report(const char* kind, const char* path, const char* advice);
void CtrDataRefuse_report(const char* kind, const char* path, const char* advice) { CtrDataRefuse_warn(kind, path, advice); }
#endif

// Crash and hang reports start with the line (R243 finding 2). The three report writers' file writes come here
// (CMakeLists.txt points FSFILE_Write here in z_argcrash.c, ctr_lab.c and ctr_watchdog.c; only call targets change):
// z_argcrash.c's writeCrashFile (crash.txt for a fatal or out-of-memory stop) and ctr_lab.c's writeReportFile (crash.txt:
// the guard's crash, failure and hang report) empty the file, then write the report at 0; ctr_watchdog.c's
// appendReportToFile (hang.txt) writes the report at the file's end. Each writes its report in one call, flushed
// (FS_WRITE_FLUSH). So a report's start is a flushed write at 0, or a flushed write at the file's end, and the line goes
// in there first, then the report after it. A write at 0 needs no size check (R243c review): crash.txt has two writers,
// and when one empties it and the other then writes its own report, the file's end no longer says where the first
// one's report starts. Two reports in crash.txt at once each still start at 0 with the line; whose text follows it is
// left to them. z_argcrash.c's debug screenshots write their header unflushed, and set their full size first, so their
// one flushed write (the last row) isn't at the file's end. Nothing is kept between calls (R243b review): each write
// asks its own file, so reports written at once on two threads (a fatal stop's crash.txt and the watchdog's hang.txt)
// each get their line. None of the report's buffer is used: a full 8,191 B report keeps every byte, and the summary the
// crash screen is chosen from (__wrap_svcOutputDebugString's) isn't touched. An official file's writes go straight on,
// with no extra file call.
//
// A short line write is finished in further writes (each writes at least a byte, so at most the line's length of
// them); a failed one, or one that writes nothing, cuts the file back to where the line began, and the report goes
// there. That cut's result isn't checked, so the report follows no part of a line only when the cut works; if the card
// keeps failing, the line is best effort, as the report is. Reports are far below 4 GiB, so the line's positions are
// 32-bit.
Result CtrDataRefuse_reportWrite(Handle file, u32* written, u64 offset, const void* buffer, u32 size, u32 flags);
DATAREFUSE_CODE Result CtrDataRefuse_reportWrite(Handle file, u32* written, u64 offset, const void* buffer, u32 size,
                                                 u32 flags) {
    u64 end;
    if (__atomic_load_n(&datarefuseMark[0], __ATOMIC_ACQUIRE) != '\0' && (flags & FS_WRITE_FLUSH) != 0 &&
        (offset == 0 || (R_SUCCEEDED(FSFILE_GetSize(file, &end)) && end == offset))) {
        const char* line = datarefuseMark;
        u32 length = (u32) strlen(line), left = length, at = (u32) offset;
        for (;;) {
            u32 done = 0;
            if (R_FAILED(FSFILE_Write(file, &done, at, line, left, 0)) || done == 0) {
                FSFILE_SetSize(file, offset);
                break;
            }
            if (done >= left) {
                offset += length;
                break;
            }
            line += done;
            left -= done;
            at += done;
        }
    }
    return FSFILE_Write(file, written, offset, buffer, size, flags);
}

// romfs:/offkill.bin and offdoom.bin hold the build input's object and variable numbers, which z_offkill.c reads with
// no check against the data.win on the card (change scoursol1, "Swapped data.win"): with another file they could destroy
// the wrong instance or index past its object list. A warned session never applies them: Utsw_handleRoomChange's
// call (--wrap=OffKill_roomChange, CMakeLists.txt) does only what that call replaced, CtrBench_handleRoomChange, as
// a build without the files does. The official file takes the real call. The main thread set the line, so a plain
// load. Weak: builds without UTSW_ON have no OffKill_roomChange, and nothing calls this there.
struct Runner;
void CtrBench_handleRoomChange(struct Runner* runner);
void __real_OffKill_roomChange(struct Runner* runner) __attribute__((weak));
void __wrap_OffKill_roomChange(struct Runner* runner);
DATAREFUSE_CODE void __wrap_OffKill_roomChange(struct Runner* runner) {
    if (datarefuseMark[0] != '\0') CtrBench_handleRoomChange(runner);
    else __real_OffKill_roomChange(runner);
}

#ifdef DATAREFUSE_WARN_TEST
// Test builds only (CTRPORT_DATAWARN_TEST, CMakeLists.txt): with datawarntest.txt in the game folder (it holds N, the
// setup notices to answer: the warning and any notice after it, such as a missing credits.txt's), each notice's 30th
// frame saves both screens' framebuffers (datawarn_<n>_top.raw, datawarn_<n>_bottom.raw: u16 width, height, format,
// 0, then the bytes) and its 32nd reads A as pressed, through a wrap of hidKeysDown. After N presses it stops.
static int datarefuseTestFrame __attribute__((section(".bss.datarefuse_late")));
static int datarefuseTestLeft __attribute__((section(".bss.datarefuse_late")));
static int datarefuseTestShown __attribute__((section(".bss.datarefuse_late")));

DATAREFUSE_CODE void CtrDataRefuse_armTest(void) {
    FILE* f = fopen(CTRPORT_GAME_DIR "/datawarntest.txt", "r");
    if (f == NULL) return;
    int presses = 1;
    if (fscanf(f, "%d", &presses) != 1 || presses < 1 || presses > 4) presses = 1;
    fclose(f);
    datarefuseTestLeft = presses;
    datarefuseTestFrame = 1;
    logInfo("[datawarn-test] armed for %d notice(s)\n", presses);
}

DATAREFUSE_CODE static void datarefuseDump(gfxScreen_t screen, const char* name) {
    char path[96];
    snprintf(path, sizeof(path), CTRPORT_GAME_DIR "/datawarn_%d_%s.raw", datarefuseTestShown + 1, name);
    u16 size[4] = { 0, 0, (u16) gfxGetScreenFormat(screen), 0 };
    u8* fb = gfxGetFramebuffer(screen, GFX_LEFT, &size[0], &size[1]);
    u32 bytes = size[2] == GSP_RGBA8_OES ? 4 : size[2] == GSP_BGR8_OES ? 3 : 2;
    FILE* f = fopen(path, "wb");
    if (f == NULL || fb == NULL) {
        if (f != NULL) fclose(f);
        return;
    }
    bool ok = fwrite(size, 1, sizeof(size), f) == sizeof(size) && fwrite(fb, bytes, (size_t) size[0] * size[1], f) ==
                                                                     (size_t) size[0] * size[1];
    if (fclose(f) != 0) ok = false;
    logInfo("[datawarn-test] %s %ux%u format %u: %s\n", path, size[0], size[1], size[2], ok ? "saved" : "FAILED");
}

u32 __real_hidKeysDown(void);
u32 __wrap_hidKeysDown(void);
DATAREFUSE_CODE u32 __wrap_hidKeysDown(void) {
    u32 down = __real_hidKeysDown();
    if (datarefuseTestFrame == 0) return down;
    if (++datarefuseTestFrame == 30) {
        datarefuseDump(GFX_TOP, "top");
        datarefuseDump(GFX_BOTTOM, "bottom");
    }
    if (datarefuseTestFrame < 32) return down;
    datarefuseTestShown++;
    datarefuseTestFrame = --datarefuseTestLeft > 0 ? 1 : 0;
    logInfo("[datawarn-test] A pressed on notice %d's frame 32\n", datarefuseTestShown);
    return down | KEY_A;
}
#endif

#endif
