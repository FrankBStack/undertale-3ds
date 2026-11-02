// pacerflush (change pacer gbot, 2026-11-02): the consoles' write-back with the game on either screen.
//
// creddodge P41 (11-02, stage75zm, XL + o2DS): with the game on the bottom screen and Other screen Off, main paid
// 0.33-0.40 ms a frame more than with it on top, outside Step and Draw. main.c's CtrScreens_flushConsoles wrote the
// top screen's consoles back (192,000 B through GSP) at every frame's start, printed on or not; with the game on top,
// main writes its consoles' screen back only while they show (flushBottomScreen at the frame's end). With them
// showing, flushBottomScreen also wrote back the game's own GPU-written bottom buffer (153,600 B) every frame.
//
// main.c's two GSP calls now come here with the same arguments (only the branch targets differ, so main.o's code and
// layout stay as they were): CtrScreens_noteConsoles (the frame's start) notes the top consoles' framebuffer and
// writes nothing back; CtrScreens_flushConsoleScreen (flushBottomScreen: the frame's end while the consoles show, and
// the setup and error screens) writes back the consoles' screen: the bottom one as before, or, while they are on the
// top screen, that one. So the game on either screen pays one write-back of its consoles' screen a frame while they
// show and none while they don't. While they are off nothing prints on them (the log's console lines are dropped and
// the stats aren't printed); every other CPU writer of that screen (the counter, the first-boot hint, a screenshot's
// notice, the options menu, the error screens' clears, the moves) writes its own pixels back. The top consoles hold
// 400 columns of pixels to the bottom one's 320: their write-back is 192,000 B to 153,600 B.
//
// Before any frame has noted them (a setup notice or error screen before the first frame), the bottom screen's is
// written back, as before. Placed last in the late text and bss (late_reserve.ld, "pacerflush"), so nothing moves.

#include <3ds.h>
#include <stdbool.h>

#define PACERFLUSH_TEXT __attribute__((noinline, section(".text.pacerflush_late")))

extern bool CtrScreens_consolesOnTop; // ctr_screens.c

static const void* pacerflushTop __attribute__((section(".bss.pacerflush_late")));
static u32 pacerflushTopBytes __attribute__((section(".bss.pacerflush_late")));

Result CtrScreens_noteConsoles(const void* fb, u32 bytes);
Result CtrScreens_flushConsoleScreen(const void* bottom, u32 bytes);

PACERFLUSH_TEXT Result CtrScreens_noteConsoles(const void* fb, u32 bytes) {
    pacerflushTop = fb;
    pacerflushTopBytes = bytes;
    return 0;
}

PACERFLUSH_TEXT Result CtrScreens_flushConsoleScreen(const void* bottom, u32 bytes) {
    if (CtrScreens_consolesOnTop && pacerflushTop != NULL) return GSPGPU_FlushDataCache(pacerflushTop, pacerflushTopBytes);
    return GSPGPU_FlushDataCache(bottom, bytes);
}
