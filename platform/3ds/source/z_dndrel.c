// dndrel (change auditfixe, SCOURS3-002, UNDERTALE): GameMaker's Move Free action with Relative checked adds its motion
// to the instance's instead of replacing it.
//
// vm_builtins.c registers action_set_motion as builtin_motion_set ("GMS1 D&D thingie"), which never reads the D&D
// Relative flag (ctx->actionRelativeFlag, set by action_set_relative and reset at event entry). GameMaker
// 1.4's Move Free with Relative adds the new motion to the old one, as motion_add does: the PC game (change scours3's
// reference run, the same save and attack) moves the bullet below at speed 2.41, hspeed -1.48, vspeed 1.91, the sum of
// its aim at the heart and the nudge.
// UNDERTALE's three action_set_motion call sites all run with Relative on (blt_direct, blt_thatch, blt_laser Create).
// blt_direct is the one that matters: it first aims at the heart (action_move_point, about 2.5 px a frame), then nudges
// itself with action_set_motion(0, +-0.2). Replacing left the bullet crawling along the battle box's edge at about 0.2
// (Froggit in a multi-monster fight, Undyne's date: change scours3 measured 0.12 on the 3DS against 2.41 on PC). The
// other two have no motion before theirs, so adding gives the same motion as replacing.
//
// The other D&D actions UNDERTALE calls with Relative on are action_move_to (blt_hoopbullet2, already relative in
// vm_builtins.c); every other action_* it calls runs with Relative off (DataWin census: action_set_relative is called
// only in those five events).
//
// How: VM_create's builtin chain ends in Hitbox_registerAll (vm_builtins.h, COLFLIP_REGISTER_ALL, UNDERTALE builds),
// reached through the linker (-Wl,--wrap=Hitbox_registerAll, CMakeLists.txt). After it, action_set_motion's map entry
// is pointed at dndrelSetMotion, which goes on to motion_add's builtin when Relative is on and to the one it replaced
// otherwise. vm_builtins.c doesn't change; the entry is swapped before the VM's function cache and the AOT code's
// builtin slots are filled from the map. Code, constants and statics are late (late_reserve.ld: .text_dndrel,
// .rodata.dndrel_in_text, .bss.dndrel_late).
#if defined(ENABLE_WAD16) // (Hitbox_registerAll is UNDERTALE's: collision_gm14.c)
#include <stddef.h>
#include <stdint.h>

#include "vm.h"
#include "stb_ds.h"

#define DNDREL_CODE __attribute__((noinline, section(".text_dndrel")))
#define DNDREL_RO __attribute__((section(".rodata.dndrel_in_text")))
#define DNDREL_BSS __attribute__((section(".bss.dndrel_late")))

void __real_Hitbox_registerAll(VMContext* ctx);
void __wrap_Hitbox_registerAll(VMContext* ctx);

static const char dndrelNames[] DNDREL_RO = "action_set_motion\0motion_add";
static BuiltinFunc dndrelSet DNDREL_BSS; // action_set_motion's builtin (motion_set's)
static BuiltinFunc dndrelAdd DNDREL_BSS; // motion_add's

DNDREL_CODE static RValue dndrelSetMotion(VMContext* ctx, RValue* args, int32_t argCount) {
    return (ctx->actionRelativeFlag ? dndrelAdd : dndrelSet)(ctx, args, argCount);
}

// Every VM_create registers the builtins afresh; an entry already pointing here, or a name missing, is left alone.
DNDREL_CODE void __wrap_Hitbox_registerAll(VMContext* ctx) {
    __real_Hitbox_registerAll(ctx);
    ptrdiff_t set = shgeti(ctx->builtinMap, (char*) dndrelNames);
    ptrdiff_t add = shgeti(ctx->builtinMap, (char*) dndrelNames + sizeof "action_set_motion");
    if (0 > set || 0 > add || ctx->builtinMap[set].value == dndrelSetMotion) return;
    dndrelSet = ctx->builtinMap[set].value;
    dndrelAdd = ctx->builtinMap[add].value;
    ctx->builtinMap[set].value = dndrelSetMotion;
}
#endif
