// E2: bounded diagnostic heading; the crash screen retains the full build ID.
#ifdef ENABLE_WAD16
#ifdef CTRPORT_PLAYER_SHOTS
#define UPD1_STATS_FOOTER "SELECT+START exit, SELECT+L shot"
#else
#define UPD1_STATS_FOOTER "SELECT+START exit               "
#endif
const char Upd1_statsFormat[] __attribute__((section(".rodata.late.upd1"))) =
    "\x1b[0;0H\x1b[1;36mundertale-3ds\x1b[0m%.0s (%.18s)\x1b[K\n"
    "%s, SELECT for options\x1b[K\n"
    "frame %-7d %-25.25s\n"
    "fps %5.1f/%-3lu step %5.2f max %6.2f ms\n"
    "cpu draw %5.2f ms  gpu %5.2f ms     \n"
    "%4lu draws %5lu verts  heap %5.1f MB\n"
    UPD1_STATS_FOOTER;
#endif
