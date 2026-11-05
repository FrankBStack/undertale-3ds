// wrapfix (change auditfixe, SCOURT2-001, UNDERTALE): draw_text_ext keeps every letter of a word wider than its wrap
// width, and lets that word run past the width on its own line, as GameMaker 1.4 does on PC.
//
// TextUtils_wrapText (engine/src/text_utils.h) breaks a line at its last space. When the line holds no space before
// the first letter that doesn't fit, it ended the line just before that letter and then started the next line one byte
// further on (start = ++end), so that letter was lost at each break: "ABCDE" at a width of two letters drew "AB" over
// "DE". UNDERTALE reaches it in Mettaton EX's essay (the essay's Draw event, the answer typed on the software keyboard,
// z_swkbd.c): a long word with no spaces lost a letter at every line break.
//
// The PC game (change auditfixe's pcref runs of the owner's UNDERTALE 1.08, the essay's own draw with its answer set,
// runs auditfixe-essaywrap-2..4) never breaks inside a word. A word with no space before it on
// the line takes the line up to the next space, or to the end of the text, and runs past the width:
//   100 letters                    one line, running off the screen
//   "HELLO <40 letters> KL ..."    "HELLO" / the 40 letters / "KL WORDS FIT HERE"
//   "AB CD <40 letters>  EF"       "AB CD" / the 40 letters / " EF" (the second space starts the next line)
//   "<40 letters>#BB CC DD"        the 40 letters and "BB" on one line / "CC DD"
//   "HI#<40 letters> EF"           "HI" / the 40 letters / "EF"
// The run to the next space goes on past a line break (# or chr(10)), and the PC draws that line as one: the break
// takes no room and doesn't start a new line (the fourth case, the same for # and for chr(10)). This is GameMaker
// HTML5's Split_TextBlock, which TextUtils_wrapText ports except for this branch: when no space comes before the
// overflow, it moves the line's end forward to the next space or the end of the text. Here the line's breaks are
// left out of what is drawn, since the renderer would start a new line at each; on PC they draw nothing. chr(13) is
// left out the same way: the renderer breaks on it too (TextUtils_isNewlineChar), though the PC wasn't run with one,
// and the essay can't take it (Enter confirms; z_swkbd.c takes printable characters only).
//
// Runs of spaces (change auditfixe, the space-run crash; pcref runs auditfixe-essaywrap-5..7): the PC doesn't count a
// line's leading spaces against the width ("A", 88 spaces, "B" draws "A" over 87 spaces and "B": 522 px of spaces in
// a width of 450), and when a line breaks in a run of spaces, the next line starts one past the run's first space, so
// the run's other spaces come before it:
//   "A", 74 spaces, "B"               "A" / 73 spaces and "B"
//   "AB CD", 70 spaces, "EF GH"       "AB CD" / 69 spaces and "EF GH" (wider than 450 with them, not broken)
//   "AB", 3 spaces, a 30-letter word  "AB" / 2 spaces and the word
//   74 spaces, "B C"                  one line
// TextUtils_wrapText counted them, and its trim of a line's trailing spaces wasn't bounded at the line's start: when a
// line's leading spaces filled the width, the trim went below the start and the copy's length went negative, a crash
// (in the essay: a letter, about 150 spaces and a letter). Here leading spaces aren't counted, the trim stops at the
// line's start, and the next line starts where the PC's does. One layout still differs: "AB", 5 spaces and a 40-letter
// word draws "AB" / a space and the word here; the PC draws "AB", an empty line, 2 spaces and the word, then the word
// again on a fourth line (run 7), which no rule above explains. No letter is lost either way.
//
// Every other line comes out as before: Wrapfix_wrapText is TextUtils_wrapText with only those changes (marked
// "wrapfix"), and without its no-wrap path (a width below zero goes on to the builtin it replaced, unchanged). Prose
// with single spaces and no line starting with one never meets the space rules. In
// UNDERTALE the essay's draw is the only call of any builtin that wraps text (draw_text_ext, its _transformed and
// colour forms, string_height_ext: a DataWin census of every code entry), so no other text moves.
//
// How: TextUtils_wrapText is code that must not move or change size (vm_builtins.c's .text.TextUtils_wrapText, kept
// in place by vm_builtins_layerfix_layout.inc), so vm_builtins.c doesn't change. VM_create's builtin chain reaches
// UtKill_registerAll from z_utflames.c (vm_builtins.h, COLFLIP_REGISTER_ALL), through the linker here
// (-Wl,--wrap=UtKill_registerAll, CMakeLists.txt). After it, draw_text_ext's map entry points at wrapfixDrawTextExt,
// before the VM's function cache and the AOT code's builtin slots are filled from the map; nothing later in the chain
// replaces draw_text_ext. wrapfixDrawTextExt is builtin_draw_text_ext and drawTextExtCommonColor's plain-colour path
// (draw_text_ext draws in the current colour) with Wrapfix_wrapText. Text that isn't a string, a call with fewer than
// five arguments and a width below zero go on to the builtin it replaced, unchanged; UNDERTALE draws only its answer
// string here, at a width of 450.
// Code, constants and the replaced builtin's pointer are late (late_reserve.ld: .text_wrapfix, .rodata.wrapfix_in_text,
// .bss.wrapfix_late). DELTARUNE doesn't build this.
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#if defined(ENABLE_WAD16) && !defined(ENABLE_WAD17)
// RValue_toReal and RValue_toInt32 call collision_gm14.c's copies of what isn't a real, as alarm_gm14.c does, so this
// file adds no copy of its own (rvalue.h, RVALUE_OTHER_EXTERN).
#define RValue_toRealOther Colflip14_toRealOther
#define RValue_toInt32Other Colflip14_toInt32Other
#define RVALUE_OTHER_EXTERN
#include "vm.h"
#include "runner.h"
#include "renderer.h"
#include "utils.h"
#include "stb_ds.h"

#ifndef WRAPFIX_CODE
#define WRAPFIX_CODE __attribute__((noinline, optimize("Os"), section(".text_wrapfix")))
#endif

// text_utils.h's helpers allocate through safeMalloc, whose failure message and file names are strings; here they
// allocate through wrapfixAlloc, so this file holds no string but the builtin's name (a merged string would land in
// the main string pool and move what follows it). A failed allocation still stops the game, as safeMalloc does.
WRAPFIX_CODE static void* wrapfixAlloc(size_t size) {
    void* ret = malloc(size);
    if (ret == nullptr) abort();
    return ret;
}
#undef safeMalloc
#define safeMalloc(size) wrapfixAlloc(size)
#include "text_utils.h"
#ifndef WRAPFIX_RO
#define WRAPFIX_RO __attribute__((section(".rodata.wrapfix_in_text")))
#endif
#ifndef WRAPFIX_BSS
#define WRAPFIX_BSS __attribute__((section(".bss.wrapfix_late")))
#endif

void __real_UtKill_registerAll(VMContext* ctx);
void __wrap_UtKill_registerAll(VMContext* ctx);

static const char wrapfixName[] WRAPFIX_RO = "draw_text_ext";
static BuiltinFunc wrapfixPrevious WRAPFIX_BSS; // builtin_draw_text_ext

// ===[ wrapfix wrap ]===
// TextUtils_wrapText (text_utils.h) but for the overflow with no space before it and runs of spaces (marked
// "wrapfix"). A width below zero (no wrap) never gets here: wrapfixDrawTextExt hands that call to the builtin it
// replaced, which draws it as this would (TextUtils_wrapText's no-wrap path splits at line breaks only). flatten:
// text_utils.h's glyph lookup and UTF-8 decoder go inside, not into out-of-line copies named as other files' are.
WRAPFIX_CODE __attribute__((flatten))
static PreprocessedText Wrapfix_wrapText(Font* font, const char* text, int32_t maxWidth) {
    PreprocessedText ret = {0};
    int32_t len = 0;
    if (text != nullptr)
        len = (int32_t) strlen(text);

    if (0 == len) {
        ret.text = text;
        ret.owning = false;
        return ret;
    }

    int32_t linewidth = maxWidth;

    // Worst case: each byte becomes itself plus a '\n' separator.
    char* out = (char *)safeMalloc((size_t) len * 2 + 1);
    int32_t outLen = 0;
    bool wroteAny = false;

    ret.text = out;
    ret.owning = true;

    const char* pNew = text;
    int32_t start = 0;
    int32_t end = 0;

    while (len > start) {
        float total = 0.0f;

        // Skip leading whitespace. wrapfix: drawn, but not counted against the width (as on PC), so the skip runs to
        // the line's first other character.
        while (len > end && pNew[end] == ' ') end++;

        // Loop through string and get the number of chars that will fit in the line.
        while (len > end && (float) linewidth > total) {
            if (pNew[end] == '\n') break;
            int32_t tentative = end;
            uint16_t cp = TextUtils_decodeUtf8(pNew, len, &tentative);
            FontGlyph* glyph = TextUtils_findGlyph(font, cp);
            float size = (glyph != nullptr) ? (float) glyph->shift : 0.0f;
            float newTotal = total + size;
            if (newTotal > (float) linewidth) break;
            total = newTotal;
            end = tentative;
        }

        // END of line
        if (len > end && pNew[end] == '\n') {
            if (wroteAny) out[outLen++] = '\n';
            memcpy(out + outLen, pNew + start, (size_t) (end - start));
            outLen += end - start;
            wroteAny = true;
        } else {
            // NOT a new line, but we didn't move on: a single char doesn't even fit.
            if (end == start) {
                out[outLen] = '\0';
                return ret;
            }

            bool overlong = false; // wrapfix: no space before the overflow
            if (end != len) {
                bool nextNotSpace = (end + 1 >= len) || (pNew[end + 1] != ' ');
                if ((pNew[end] != ' ') || (pNew[end] != ' ' && nextNotSpace)) {
                    int32_t e = end;
                    while (e > start) {
                        e--;
                        if (pNew[e] == ' ') break; // FOUND start of word
                    }

                    if (e != start) {
                        end = e;
                    } else {
                        // wrapfix: the line runs on to the next space or the end of the text (GameMaker 1.4 on
                        // PC, and HTML5's Split_TextBlock), past any line break in it.
                        while (len > end && pNew[end] != ' ') end++;
                        overlong = true;
                    }
                }
            }
            int32_t _end = end;
            while (_end > start && pNew[_end - 1] == ' ') _end--; // wrapfix: never below the line's start

            if (_end != start) {
                if (wroteAny) out[outLen++] = '\n';
                if (overlong) {
                    // wrapfix: one line, as the PC draws it; its breaks take no room there.
                    for (int32_t i = start; _end > i; i++) {
                        if (!TextUtils_isNewlineChar(pNew[i])) out[outLen++] = pNew[i];
                    }
                } else {
                    memcpy(out + outLen, pNew + start, (size_t) (_end - start));
                    outLen += _end - start;
                }
                wroteAny = true;
            }
            // wrapfix: the next line starts one past the first space of the gap that ends this one (as on PC); the
            // gap's other spaces come before it.
            if (len > end) end = _end;
        }
        start = ++end;
    }
    out[outLen] = '\0';
    return ret;
}
// ===[ wrapfix wrap end ]===

// builtin_draw_text_ext and drawTextExtCommonColor (vm_builtins.c), its plain-colour path, with Wrapfix_wrapText.
// flatten: text_utils.h's preprocessing goes inside, not into an out-of-line copy whose name vm_builtins.c's also has.
WRAPFIX_CODE __attribute__((flatten)) static RValue wrapfixDrawTextExt(VMContext* ctx, RValue* args, int32_t argCount) {
    Runner* runner = ctx->runner;
    if (5 > argCount || args[2].type != RVALUE_STRING || args[2].string == nullptr || runner->renderer == nullptr ||
        0 > RValue_toInt32(args[4]))
        return wrapfixPrevious(ctx, args, argCount);

    float x = (float) RValue_toReal(args[0]);
    float y = (float) RValue_toReal(args[1]);
    int32_t separation = RValue_toInt32(args[3]);
    int32_t width = RValue_toInt32(args[4]);

    int32_t fontIndex = runner->renderer->drawFont;
    if (0 > fontIndex || (uint32_t) fontIndex >= runner->dataWin->font.count) return RValue_makeUndefined();
    Font* font = &runner->dataWin->font.fonts[fontIndex];

    PreprocessedText processedText = TextUtils_preprocessGmlTextIfNeeded(runner, args[2].string);
    PreprocessedText wrappedText = Wrapfix_wrapText(font, processedText.text, width);
    runner->renderer->vtable->drawText(runner->renderer, wrappedText.text, x, y, 1.0f, 1.0f, 0.0f, (float) separation);
    PreprocessedText_free(wrappedText);
    PreprocessedText_free(processedText);
    return RValue_makeUndefined();
}

// Every VM_create registers the builtins afresh; an entry already pointing here, or the name missing, is left alone.
WRAPFIX_CODE void __wrap_UtKill_registerAll(VMContext* ctx) {
    __real_UtKill_registerAll(ctx);
    ptrdiff_t idx = shgeti(ctx->builtinMap, (char*) wrapfixName);
    if (0 > idx || ctx->builtinMap[idx].value == nullptr || ctx->builtinMap[idx].value == wrapfixDrawTextExt) return;
    wrapfixPrevious = ctx->builtinMap[idx].value;
    ctx->builtinMap[idx].value = wrapfixDrawTextExt;
}
#endif
