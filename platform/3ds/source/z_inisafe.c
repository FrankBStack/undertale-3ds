// inisafe (change auditfixe, DEEP-01, both games): the INI cache must not outlive a change to the file.
//
// ini_close keeps the closed file's parsed contents (runner->cachedIni, vm_builtins.c) so that the next ini_open of
// that file needn't read and parse it again. GameMaker's ini_open reads the file every time, so whatever changes a
// file between that close and that open must be seen by the open. A game that resets its progress closes its INI,
// deletes the file and opens it again: with the cache still there, that open got the deleted file back, and its close
// wrote every deleted key out again (tools/analysis/test_ini_cache_coherence.py plays the whole sequence).
//
// So each builtin that writes, replaces, renames or deletes a file drops the cached copy first, whatever the file (a
// path can be spelt more than one way; the next ini_open then just reads and parses one small file, which the 3DS
// file system serves from its own copy of the save files). file_text_close drops it for a file read as well (this
// engine writes a text file at its close; telling the two apart costs more code than the one parse it saves), and so
// does file_bin_close (the 3DS file system publishes a binary file's bytes at its close, ctrBinaryClose). A plain
// ini_close and ini_open still use the cache.
//
// The open INI (runner->currentIni) stays as it is: GameMaker holds it in memory until ini_close writes it out, and
// ini_close writes it only if something was written to it (unchanged here). But ini_close also keeps what it closes
// as the cache, and a clean INI that was open while a file changed is the file as it was before the change: so a
// change made while an INI is open marks that INI (inisafeStale), and a clean close of the marked INI drops the cache
// it has just made (the next ini_open reads the file). A dirty close wrote that INI to the file: its cache matches.
//
// How: VMBuiltins_registerAll is reached through the linker (-Wl,--wrap=VMBuiltins_registerAll, CMakeLists.txt). After
// it has registered everything, each of the builtins below is looked up by name, kept, and its map entry pointed at a
// stub that drops the cache and goes on to it. vm_builtins.c doesn't change at all (its text, string pool and every
// registration stay byte for byte; tools/buildcache/colexact_compile.py fingerprints that pool), and the callers of
// VMBuiltins_registerAll only change their branch target. The stubs run no GML and touch no instance or variable, as
// the builtins they lead to (all "pure" in tools/aot/builtin_audit.py), so the AOT code's cached slots stay valid.
//
// On the 3DS each stub is two instructions (its index into ip, a branch to inisafeDispatch), and inisafeDispatch
// branches to the builtin with every argument register, lr and sp as the VM left them: a builtin returns an RValue
// through r0's pointer, which a C wrapper can't pass on as a tail call (44 B a wrapper instead of 8). The host (the
// test) has C wrappers around the same inisafeForget.
//
// Code, constants and statics are late (late_reserve.ld: .text_inisafe, .rodata.inisafe_in_text after it, and
// .bss.inisafe_late), named outside .text.late.* and .bss.late.* so no catch-all takes them first.
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include "ini.h"
#include "runner.h"
#include "vm.h"
#include "stb_ds.h"

#define INISAFE_CODE __attribute__((noinline, section(".text_inisafe")))
#define INISAFE_RO __attribute__((section(".rodata.inisafe_in_text")))
#define INISAFE_BSS __attribute__((section(".bss.inisafe_late")))

void __real_VMBuiltins_registerAll(VMContext* ctx);
void __wrap_VMBuiltins_registerAll(VMContext* ctx);

#define INISAFE_COUNT 14 // the stubs; ini_close, after them, has a wrapper of its own

// GameMaker empties a file at file_text_open_write, this engine writes it at file_text_close: both drop the copy.
// buffer_save_async writes at once, or at buffer_async_group_end inside a group: both drop it too. One string, each
// name ended by its NUL, in stub order, then ini_close.
static const char inisafeNames[] INISAFE_RO =
    "file_delete\0file_rename\0file_copy\0file_text_open_write\0file_text_close\0file_bin_open\0"
    "file_bin_write_byte\0file_bin_rewrite\0directory_destroy\0buffer_save\0buffer_save_ext\0buffer_save_async\0"
    "buffer_async_group_end\0file_bin_close\0ini_close";
static BuiltinFunc inisafeReal[INISAFE_COUNT + 1] INISAFE_BSS;
static IniFile* inisafeStale INISAFE_BSS; // the open INI a file changed under, until the next ini_close

INISAFE_CODE static void inisafeDrop(Runner* runner) {
    if (runner->cachedIni != nullptr) {
        Ini_free(runner->cachedIni);
        runner->cachedIni = nullptr;
    }
    free(runner->cachedIniPath);
    runner->cachedIniPath = nullptr;
}

// Drops the cached INI, marks the open one, and returns the builtin stub `which` stands for.
__attribute__((used)) INISAFE_CODE static BuiltinFunc inisafeForget(VMContext* ctx, uint32_t which) {
    Runner* runner = ctx->runner;
    inisafeDrop(runner);
    if (runner->currentIni != nullptr) inisafeStale = runner->currentIni;
    return inisafeReal[which];
}

// ini_close as it is (its write, its result), but a clean close of a marked INI leaves no cache behind. A marked INI
// that was freed without a close (ini_open of another file) only costs a later clean close one parse, if a new INI
// gets its address.
INISAFE_CODE static RValue inisafeIniClose(VMContext* ctx, RValue* args, int32_t argCount) {
    Runner* runner = ctx->runner;
    bool stale = runner->currentIni != nullptr && runner->currentIni == inisafeStale && !runner->currentIniDirty;
    inisafeStale = nullptr;
    RValue result = inisafeReal[INISAFE_COUNT](ctx, args, argCount);
    if (stale) inisafeDrop(runner);
    return result;
}

#if defined(__arm__)
// A builtin's registers on entry: r0 the RValue to fill, r1 ctx, r2 args, r3 argCount. r4 is pushed only to keep
// the stack 8-byte aligned at the call (6 words); nothing changes it.
__attribute__((naked, noinline, used, section(".text_inisafe"))) static void inisafeDispatch(void) {
    __asm__("push {r0-r4, lr}\n\t"
            "mov r0, r1\n\t"
            "mov r1, ip\n\t"
            "bl inisafeForget\n\t"
            "mov ip, r0\n\t"
            "pop {r0-r4, lr}\n\t"
            "bx ip");
}

#define INISAFE_STUB(n) "mov ip, #" #n "\n\tb inisafeDispatch\n\t"
#define INISAFE_STUB_SIZE 8u
__attribute__((naked, noinline, section(".text_inisafe"))) static void inisafeStubs(void) {
    __asm__(INISAFE_STUB(0) INISAFE_STUB(1) INISAFE_STUB(2) INISAFE_STUB(3) INISAFE_STUB(4) INISAFE_STUB(5)
            INISAFE_STUB(6) INISAFE_STUB(7) INISAFE_STUB(8) INISAFE_STUB(9) INISAFE_STUB(10) INISAFE_STUB(11)
            INISAFE_STUB(12) INISAFE_STUB(13));
}
#undef INISAFE_STUB

INISAFE_CODE static BuiltinFunc inisafeStub(uint32_t i) {
    return i == INISAFE_COUNT ? inisafeIniClose : (BuiltinFunc) ((uintptr_t) inisafeStubs + INISAFE_STUB_SIZE * i);
}
#else
#define INISAFE_STUB(n) \
    static RValue inisafe##n(VMContext* ctx, RValue* args, int32_t argCount) { \
        return inisafeForget(ctx, n)(ctx, args, argCount); \
    }
INISAFE_STUB(0) INISAFE_STUB(1) INISAFE_STUB(2) INISAFE_STUB(3) INISAFE_STUB(4) INISAFE_STUB(5) INISAFE_STUB(6)
INISAFE_STUB(7) INISAFE_STUB(8) INISAFE_STUB(9) INISAFE_STUB(10) INISAFE_STUB(11) INISAFE_STUB(12) INISAFE_STUB(13)
#undef INISAFE_STUB

static BuiltinFunc inisafeStub(uint32_t i) {
    static const BuiltinFunc stubs[INISAFE_COUNT + 1] = {
        inisafe0, inisafe1, inisafe2, inisafe3, inisafe4, inisafe5, inisafe6,
        inisafe7, inisafe8, inisafe9, inisafe10, inisafe11, inisafe12, inisafe13, inisafeIniClose,
    };
    return stubs[i];
}
#endif

// Every VM_create registers the builtins afresh (a fresh map), so each one finds the originals again; a name already
// pointing at its stub (or missing) is left as it is.
INISAFE_CODE void __wrap_VMBuiltins_registerAll(VMContext* ctx) {
    __real_VMBuiltins_registerAll(ctx);
    const char* name = inisafeNames;
    for (uint32_t i = 0; INISAFE_COUNT >= i; i++, name += strlen(name) + 1) {
        ptrdiff_t index = shgeti(ctx->builtinMap, (char*) name);
        BuiltinFunc stub = inisafeStub(i);
        if (0 > index || ctx->builtinMap[index].value == stub) continue;
        inisafeReal[i] = ctx->builtinMap[index].value;
        ctx->builtinMap[index].value = stub;
    }
}
