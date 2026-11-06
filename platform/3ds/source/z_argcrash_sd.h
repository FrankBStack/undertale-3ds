// UTSCOURD-001 (change auditfixe2): included by z_argcrash.c on a line that was blank, so no line of that file moves
// (__LINE__ is in its constants) and the change stays append-only (RULES 3adf7ac34). It names the two calls that file
// redirects; the code is at z_argcrash.c's end.
//
// UNDERTALE: the friendly crash screen tells an SD card read stop (the overlay reader's or the data.win check's)
// from missing game files. __wrap_svcOutputDebugString's call of the real svcOutputDebugString goes to
// argcrashSdOut, which notes whether the latest "[ERROR] Fatal: " line is an SD read, and argcrashPaintScreens's
// call of argcrashPaintFixed goes to argcrashPaintSd, which paints the SD card title for CRASH_DATAWIN after such a
// line and hands every other screen to argcrashPaintFixed. UTSCOURD F4: that call reaches argcrashPaintSd through
// argcrashPaintMem, which paints the data.win check's allocation failure as out of memory (ctr_data_version_mem.h).
//
// DELTARUNE: both calls are as before (no late code to spare on the Old 3DS), so its object doesn't change.

#ifndef Z_ARGCRASH_SD_H
#define Z_ARGCRASH_SD_H

#ifdef ENABLE_WAD16
static Result argcrashSdOut(const char* str, s32 length);
static void argcrashPaintSd(u8* fb, u16 fbW, u16 fbH, GSPGPU_FramebufferFormat fmt, bool isTop, ArgcrashKind kind,
                            bool exiting);
// UTSCOURD F4: the paint call goes first to argcrashPaintMem, which passes it on to argcrashPaintSd.
static void argcrashPaintMem(u8* fb, u16 fbW, u16 fbH, GSPGPU_FramebufferFormat fmt, bool isTop, ArgcrashKind kind,
                             bool exiting);
static Result saveauditFatalOut(const char* str, s32 length);
static void saveauditFatalPaint(u8* fb, u16 fbW, u16 fbH, GSPGPU_FramebufferFormat fmt, bool isTop,
                               ArgcrashKind kind, bool exiting);
#define ARGCRASH_SD_DEBUG_OUT saveauditFatalOut
#define ARGCRASH_SD_PAINT saveauditFatalPaint
#else
#define ARGCRASH_SD_DEBUG_OUT __real_svcOutputDebugString
#define ARGCRASH_SD_PAINT argcrashPaintFixed
#endif

#endif
