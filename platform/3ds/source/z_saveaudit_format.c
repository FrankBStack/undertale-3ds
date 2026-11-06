// Native UNDERTALE 1.08 save encoding. PC reference cases and synthetic fault
// tests live in saveaudit_parity.py and test_saveaudit_format.py. Keep the shared
// engine and DELTARUNE unchanged; register before the existing INI cache guards.
#if defined(ENABLE_WAD16) || defined(SAVEAUDIT_HOST_TEST)
// The header emits a private out-of-line conversion helper. Give this added
// late definition its own name rather than adding a sixth existing-name entry
// to check_layout's frozen symbol group.
#define RValue_toRealOther Saveaudit_toRealOther
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ini.h"
#include "runner.h"
#include "utils.h"
#include "vm.h"
#include "stb_ds.h"

#define SF_CODE __attribute__((noinline, section(".text.late.saveaudit_format")))
#define SF_RO __attribute__((section(".rodata.late.saveaudit_format")))
#define SF_BSS __attribute__((section(".bss.late.saveaudit_format")))

void __real_VMBuiltins_registerAll(VMContext* ctx);
void CtrSaveaudit_registerAll(VMContext* ctx);

static const char sfNames[] SF_RO = "file_text_write_real\0file_text_writeln\0ini_open\0ini_close";
static const char sfWriteString[] SF_RO = "file_text_write_string";
static const char sfClose[] SF_RO = "ini_close";
static const char sfNumber[] SF_RO = "%.6g";
static const char sfNewline[] SF_RO = "\r\n";
static BuiltinFunc sfOriginal[4] SF_BSS;
static BuiltinFunc sfString SF_BSS;

SF_CODE static RValue sfWriteReal(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 2) return sfOriginal[0](ctx, args, count);
    char text[64];
    size_t length = (size_t) snprintf(text, sizeof(text), sfNumber, (double) RValue_toReal(args[1]));
    // The native Windows CRT spells exponents with at least three digits.
    char* exponent = strchr(text, 'e');
    if (exponent != NULL && strlen(exponent + 1) == 3) {
        memmove(exponent + 3, exponent + 2, 3);
        exponent[2] = '0';
        length++;
    }
    text[length++] = ' ';
    text[length] = 0;
    RValue forwarded[2] = {args[0], RValue_makeString(text)};
    return sfString(ctx, forwarded, 2);
}

SF_CODE static RValue sfWriteln(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 1) return sfOriginal[1](ctx, args, count);
    RValue forwarded[2] = {args[0], RValue_makeString(sfNewline)};
    return sfString(ctx, forwarded, 2);
}

// Native parse prepends sections/keys. A dirty close of a reopened file reverses
// its previous order; cache the emitted order so a cache hit behaves like a parse.
// A clean close neither reverses the cache nor publishes a new file.
SF_CODE static void sfReverse(IniFile* ini) {
    for (int i = 0, j = ini->count - 1; i < j; i++, j--) {
        IniSection temporary = ini->sections[i];
        ini->sections[i] = ini->sections[j];
        ini->sections[j] = temporary;
    }
    for (int i = 0; i < ini->count; i++) {
        IniSection* section = &ini->sections[i];
        for (int j = 0, k = section->count - 1; j < k; j++, k--) {
            char* temporary = section->keys[j];
            section->keys[j] = section->keys[k];
            section->keys[k] = temporary;
            temporary = section->values[j];
            section->values[j] = section->values[k];
            section->values[k] = temporary;
        }
    }
}

SF_CODE static char* sfSerialize(const IniFile* ini) {
    size_t length = 1;
    for (int i = 0; i < ini->count; i++) {
        const IniSection* section = &ini->sections[i];
        length += strlen(section->name) + 4; // [name]\r\n
        for (int j = 0; j < section->count; j++) {
            length += strlen(section->keys[j]) + strlen(section->values[j]) + 5;
        }
    }
    char* text = safeMalloc(length);
    char* cursor = text;
    for (int i = 0; i < ini->count; i++) {
        const IniSection* section = &ini->sections[i];
        size_t size = strlen(section->name);
        *cursor++ = '[';
        memcpy(cursor, section->name, size);
        cursor += size;
        *cursor++ = ']'; *cursor++ = '\r'; *cursor++ = '\n';
        for (int j = 0; j < section->count; j++) {
            size = strlen(section->keys[j]);
            memcpy(cursor, section->keys[j], size);
            cursor += size;
            *cursor++ = '='; *cursor++ = '"';
            size = strlen(section->values[j]);
            memcpy(cursor, section->values[j], size);
            cursor += size;
            *cursor++ = '"'; *cursor++ = '\r'; *cursor++ = '\n';
        }
    }
    *cursor = 0;
    return text;
}

SF_CODE static RValue sfIniClose(VMContext* ctx, RValue* args, int32_t count) {
    Runner* runner = ctx->runner;
    if (runner->currentIni == NULL) return sfOriginal[3](ctx, args, count);
    if (runner->currentIniDirty) sfReverse(runner->currentIni);
    char* serialized = sfSerialize(runner->currentIni);
    if (runner->currentIniDirty && runner->currentIniPath != NULL) {
        FileSystem* fs = runner->fileSystem;
        fs->vtable->writeFileText(fs, runner->currentIniPath, serialized);
    }
    if (runner->cachedIni != NULL) Ini_free(runner->cachedIni);
    free(runner->cachedIniPath);
    runner->cachedIni = runner->currentIni;
    runner->cachedIniPath = runner->currentIniPath;
    runner->currentIni = NULL;
    runner->currentIniPath = NULL;
    return RValue_makeOwnedString(serialized);
}

SF_CODE static RValue sfIniOpen(VMContext* ctx, RValue* args, int32_t count) {
    Runner* runner = ctx->runner;
    // Preserve the existing same-path no-op. The proven native case is opening
    // another file: commit the prior dirty INI through the outer cache guard.
    const char* path = count > 0 && args[0].type == RVALUE_STRING ? args[0].string : NULL;
    if (count > 0 && runner->currentIni != NULL && runner->currentIniDirty &&
        (path == NULL || runner->currentIniPath == NULL || strcmp(path, runner->currentIniPath) != 0)) {
        RValue closed = VM_findBuiltin(ctx, sfClose)(ctx, NULL, 0);
        if (closed.type == RVALUE_STRING && closed.ownsReference) free((char*) closed.string);
    }
    return sfOriginal[2](ctx, args, count);
}

SF_CODE void CtrSaveaudit_registerAll(VMContext* ctx) {
    __real_VMBuiltins_registerAll(ctx);
    sfString = VM_findBuiltin(ctx, sfWriteString);
    const char* name = sfNames;
    // Local table may be pooled by the compiler; the linker retains this whole
    // object's helper code and constants at the end of our late sections.
    const BuiltinFunc replacements[4] = {sfWriteReal, sfWriteln, sfIniOpen, sfIniClose};
    for (int i = 0; i < 4; i++, name += strlen(name) + 1) {
        ptrdiff_t index = shgeti(ctx->builtinMap, (char*) name);
        if (index < 0 || ctx->builtinMap[index].value == replacements[i]) continue;
        sfOriginal[i] = ctx->builtinMap[index].value;
        ctx->builtinMap[index].value = replacements[i];
    }
}
#endif
