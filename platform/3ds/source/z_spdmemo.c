// spdmemo (change creddodge, both games): a two-entry memo in front of Instance_computeSpeedFromComponents, reached through
// the linker (-Wl,--wrap=Instance_computeSpeedFromComponents in CMakeLists.txt), so the original stays where it is,
// unchanged, and every caller's branch only changes its target.
//
// Speed and direction come from the hspeed and vspeed bits alone, except when both compare equal to zero (the old
// direction is kept, then rounded). Pairs with a NaN or infinite component are conservatively uncached: they always
// take the original (some of them do not depend on the old direction, but they are not worth a cache). "Equal to
// zero" includes denormals: the main thread runs with FPSCR FZ=1 (docs/3ds-hardware.md, "The
// main thread's FPSCR is 0x03000010"), so a denormal hspeed takes the original's hspeed == 0 branch. Such pairs (both
// exponent fields zero) take the original every time and are never stored; r2b's bit-only zero test stored them
// (tools/analysis/check_spdmemo.py, FZ emulated on the host, catches it). Any other pair the original computed is
// kept with the direction and speed it wrote; a later call with the same two bit patterns writes those two floats
// back, the bits the original would write again. The UT credits pinwheel writes ~74 names' hspeed a frame (83 at
// most) with a few distinct pairs: one entry hits 89.5% of them, two 99.9% (creditlong0 dodger, f3300-3500).
//
// Code and statics are late (late_reserve.ld: .text_spdmemo and .bss.spdmemo_late, named outside .text.late.* and
// .bss.late.* so no catch-all takes them first; a name not starting ".bss." would be PROGBITS, not NOBITS).
#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "instance.h"

#define SPD_LATE __attribute__((noinline, section(".text_spdmemo")))

typedef struct {
    uint32_t h, v;
    float direction, speed;
} SpdEntry;

static struct {
    SpdEntry e[2];
    uint32_t used;  // entries filled (0..2)
} spd __attribute__((section(".bss.spdmemo_late")));

#ifdef CTRPORT_SPDCOUNT
uint32_t ctrSpdCalls, ctrSpdHits, ctrSpdHits2, ctrSpdSkip;
#endif

void __real_Instance_computeSpeedFromComponents(Instance* inst);
void __wrap_Instance_computeSpeedFromComponents(Instance* inst) SPD_LATE;

void __wrap_Instance_computeSpeedFromComponents(Instance* inst) {
    uint32_t h, v;
    memcpy(&h, &inst->hspeed, sizeof(h));
    memcpy(&v, &inst->vspeed, sizeof(v));
#ifdef CTRPORT_SPDCOUNT
    ctrSpdCalls++;
#endif
    for (uint32_t i = 0; spd.used > i; i++) {
        if (spd.e[i].h == h && spd.e[i].v == v) {
#ifdef CTRPORT_SPDCOUNT
            if (i == 0) ctrSpdHits++;
            else ctrSpdHits2++;
#endif
            inst->direction = spd.e[i].direction;
            inst->speed = spd.e[i].speed;
            return;
        }
    }
    __real_Instance_computeSpeedFromComponents(inst);
    // Stored only when the result needs nothing but the two bit patterns: not both zero or denormal (FZ), neither NaN
    // nor infinite.
    if (((h | v) & 0x7f800000u) != 0 && (h & 0x7f800000u) != 0x7f800000u && (v & 0x7f800000u) != 0x7f800000u) {
        spd.e[1] = spd.e[0];
        spd.e[0].h = h;
        spd.e[0].v = v;
        spd.e[0].direction = inst->direction;
        spd.e[0].speed = inst->speed;
        if (2 > spd.used) spd.used++;
    }
#ifdef CTRPORT_SPDCOUNT
    else {
        ctrSpdSkip++;
    }
#endif
}
