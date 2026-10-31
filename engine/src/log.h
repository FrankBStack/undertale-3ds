#ifndef _BS_LOG_H
#define _BS_LOG_H

#include <stdio.h>
#include <stdbool.h>
#include <stdarg.h>

typedef enum {
	LOG_TYPE_NORMAL=0,
	LOG_TYPE_WARNING=1,
	LOG_TYPE_ERROR=2,
	LOG_TYPE_DEBUG=3
} logType;

#define ANSI_COLOUR_CODE_RESET "\033[0m"
#define ANSI_COLOUR_CODE_BOLD_YELLOW "\033[1;33m"
#define ANSI_COLOUR_CODE_BOLD_RED "\033[1;31m"
#define ANSI_COLOUR_CODE_BOLD_PURPLE "\033[1;35m"

void logInfo(const char* fmt, ...);
void vLogInfo(const char* fmt, va_list va);

void logWarn(const char* fmt, ...);
void vLogWarn(const char* fmt, va_list va);

void logError(const char* fmt, ...);
void vLogError(const char* fmt, va_list va);

void logDebug(const char* fmt, ...);
void vLogDebug(const char* fmt, va_list va);

// freebytes H1 (lane freebytes, 2026-10-31): on UNDERTALE Old 3DS only, late code that never runs in a played frame is
// compiled for size (CTR_COLD_OS, as ctr_display.h's), and whole cold functions of the loading screen move into the
// holes that leaves (CTR_H1_SEC(own section, hole section); late_reserve.ld places each hole's section). Every other
// target keeps each function's own section and compiles it as before. At the header's end, so no line number moves.
#ifndef CTR_COLD_OS
#if defined(ENABLE_WAD16) && defined(CTRPORT_TARGET_O3DS)
#define CTR_COLD_OS __attribute__((optimize("Os")))
#else
#define CTR_COLD_OS
#endif
#endif
#ifndef CTR_H1_SEC
#if defined(ENABLE_WAD16) && defined(CTRPORT_TARGET_O3DS)
#define CTR_H1_SEC(own, hole) hole
#else
#define CTR_H1_SEC(own, hole) own
#endif
#endif
// z_loadscreen.c's LS_CODE for a function that fills the H1 hole named by the string literal `hole`.
#ifndef CTR_H1_LS
#define CTR_H1_LS(hole) __attribute__((noinline, section(CTR_H1_SEC(".text.late.loadscreen", ".text.h1hole." hole))))
#endif

#endif /* _BS_LOG_H */
