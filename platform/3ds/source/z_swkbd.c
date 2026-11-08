// swkbd (UNDERTALE only): Mettaton EX's essay (obj_essaystuff) gets the 3DS software keyboard.
//
// The game takes its PC path there (we report a desktop OS, so keyboard_present is 1): each step, a key press that is
// not an arrow, Backspace, Esc or a confirm/cancel control appends keyboard_lastchar to the essay. The 3DS has no
// keyboard, so keyboard_lastchar stayed "" and every essay was empty. Now the first step that finds a live essay asks
// for its prompt (scr_gettext, the PC wording), and once that frame has been handed to the GPU the libctru keyboard
// applet opens with it as the hint. The typed text then goes in the way PC delivers it, one character per step: the
// character's key goes down (keyboard_check_pressed(vk_anykey)) with keyboard_lastchar set to it, and comes up on the
// next step. The essay's own Step does the rest, so its timer, rating and Mettaton's replies are the game's. Cancel,
// HOME and anything but OK type nothing, which is what the build did before. X and Z are refused in the applet with
// the prompt's own "(No X or Z)": the game cannot take them (on PC they are confirm and cancel).
//
// The applet stops the game while it is open (libctru runs the same suspend and restore hooks as the HOME menu), so
// the player gets unlimited thinking time, unlike PC. After feeding it, hold 15 frames then expire the game's alarm.
// Text is capped to the remaining time at one character per step. The step after the applet gets a nominal delta_time
// instead of the time the applet was open (UNDERTALE does not read it; nothing else in the game clock jumps).
//
// Tests: while a benchmark runs the applet never opens; the text comes from swkbd_test.txt in the save folder (the
// bench "file" op writes it), and without that file nothing is typed, as before. A test file that starts with
// "#applet" opens the real applet instead (an emulator test that types into it).
//
// All of it is late code (late_reserve.ld), in a static library linked after libctru's original members (CMakeLists.txt).
#include <3ds.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_benchmark.h"
#include "ctr_renderer.h"
#include "ctr_wrap_chain.h"
#include "file_system.h"
#include "instance.h"
#include "int_rvalue_hashmap.h"
#include "log.h"
#include "runner.h"
#include "runner_keyboard.h"
#include "stb_ds.h"
#include "vm.h"

#define CODE __attribute__((noinline))
#define SLOT(name) __attribute__((section(".text.swkbd_late." #name)))
#define BSS __attribute__((no_reorder, section(".bss.late.swkbd")))
#define RO __attribute__((no_reorder, section(".rodata.swkbd_late")))

enum { SWKBD_IDLE, SWKBD_PENDING, SWKBD_FEEDING };
enum { SWKBD_MAX_CHARS = 300, SWKBD_TIME_MARGIN = 12 };

// Baseline storage order, pinned so moving applet callers does not reorder these existing objects.
static const char kShiftedDigits[] RO = ")!@#$%^&*(";
// US-layout virtual keys for the punctuation a PC player types (the shifted character shares its key).
static const char kPunct[] RO = ";:=+,<-_.>/?`~[{\\|]}'\"";
static const uint8_t kPunctKey[] RO = {186, 186, 187, 187, 188, 188, 189, 189, 190, 190, 191, 191,
                                       192, 192, 219, 219, 220, 220, 221, 221, 222, 222};
static const char kObject[] RO = "obj_essaystuff";
static const char kCantype[] RO = "cantype";
static const char kKeyboardPresent[] RO = "keyboard_present";
static const char kEndbuffer[] RO = "endbuffer";
static const char logOpen[] RO = "swkbd: essay %lu, keyboard for up to %d characters\n";
static const char kFromApplet[] RO = "keyboard";
static const char logTyped[] RO = "swkbd: essay %lu, %d characters to type (%s)\n";
static const char kGettext[] RO = "gml_Script_scr_gettext";
static const char kPrompt[] RO = "mett_essay_prompt_pc";
static const char kTestFile[] RO = "swkbd_test.txt";
static const char kAppletMarker[] RO = "#applet";  // a test file starting with this opens the real applet
static const char kFromTest[] RO = "test file";

static char refusal[64] BSS;    // the prompt's last line, "(No X or Z)"
static uint16_t textPos BSS;
static uint16_t textLen BSS;
static int32_t capChars BSS;
static char text[SWKBD_MAX_CHARS + 1] BSS;
static uint8_t phase BSS;
static Runner* swRunner BSS;
static DataWin* swData BSS;
static int32_t essayObject BSS;  // object index + 1, 0 = not resolved, -1 = not in this game
static uint32_t handledId BSS;  // the essay instance already given its keyboard
static int32_t heldKey BSS;     // the simulated key still down, 0 = none
static int32_t idCantype BSS;   // varNameMap ids + 1, 0 = unresolved
static int32_t idKeyboardPresent BSS;
static int32_t idEndbuffer BSS;
static uint32_t essayId BSS;
static char hint[200] BSS;      // the prompt, UTF-8 (the applet keeps 64 UTF-16 units)
static bool resetDelta BSS;

#line 85
void __real_Runner_step(Runner* runner);
void __real_CtrRenderer_endFrame(Renderer* renderer);

SLOT(lookupVarId) CODE static int32_t lookupVarId(VMContext* ctx, const char* name) {
    ptrdiff_t slot = shgeti(ctx->varNameMap, (char*) name);
    return slot < 0 ? 0 : ctx->varNameMap[slot].value + 1;
}

SLOT(readInt) CODE static int32_t readInt(Instance* inst, int32_t idPlusOne) {
    if (idPlusOne <= 0) return 0;
    RValue* v = IntRValueHashMap_findSlot(&inst->selfVars, idPlusOne - 1);
    if (v == nullptr) return 0;
    switch (v->type) {
        case RVALUE_REAL: return (int32_t) v->real;
        case RVALUE_INT32: return v->int32;
#ifndef NO_RVALUE_INT64
        case RVALUE_INT64: return (int32_t) v->int64;
#endif
        case RVALUE_BOOL: return v->int32 != 0;
        default: return 0;
    }
}

SLOT(resolve) CODE static void resolve(Runner* runner) {
    swRunner = runner;
    swData = runner->dataWin;
    essayObject = -1;
    phase = SWKBD_IDLE;
    handledId = 0;
    heldKey = 0;
    for (uint32_t i = 0; swData->objt.count > i; i++) {
        const char* name = swData->objt.objects[i].name;
        if (name != nullptr && strcmp(name, kObject) == 0) {
            essayObject = (int32_t) i + 1;
            break;
        }
    }
    VMContext* ctx = runner->vmContext;
    idCantype = lookupVarId(ctx, kCantype);
    idKeyboardPresent = lookupVarId(ctx, kKeyboardPresent);
    idEndbuffer = lookupVarId(ctx, kEndbuffer);
}

// The live essay with the given id, or the first live one when id is 0.
SLOT(findEssay) CODE static Instance* findEssay(Runner* runner, uint32_t id) {
    Instance** list = runner->instancesByObject[essayObject - 1];
    for (ptrdiff_t i = 0; arrlen(list) > i; i++) {
        Instance* inst = list[i];
        if (!inst->destroyed && (id == 0 || inst->instanceId == id)) return inst;
    }
    return nullptr;
}

// scr_gettext("mett_essay_prompt_pc") with its line breaks as spaces into hint, its last line into refusal.
SLOT(readPrompt) CODE static void readPrompt(Runner* runner, Instance* essay) {
    hint[0] = refusal[0] = 0;
    VMContext* ctx = runner->vmContext;
    ptrdiff_t slot = shgeti(ctx->codeIndexByName, (char*) kGettext);
    if (slot < 0) return;
    RValue arg = RValue_makeString(kPrompt);
    struct Instance* savedSelf = ctx->currentInstance;
    struct Instance* savedOther = ctx->otherInstance;
    ctx->currentInstance = ctx->otherInstance = essay;
    RValue result = VM_callCodeIndex(ctx, ctx->codeIndexByName[slot].value, &arg, 1);
    ctx->currentInstance = savedSelf;
    ctx->otherInstance = savedOther;
    if (result.type == RVALUE_STRING && result.string != nullptr) {
        size_t n = strlen(result.string);
        if (n >= sizeof(hint)) n = sizeof(hint) - 1;
        memcpy(hint, result.string, n);
        hint[n] = 0;
        size_t last = 0;
        for (size_t i = 0; n > i; i++) {
            if (hint[i] == '#' || hint[i] == '&') {
                hint[i] = ' ';
                last = i + 1;
            }
        }
        size_t r = n - last;
        if (r >= sizeof(refusal)) r = sizeof(refusal) - 1;
        memcpy(refusal, hint + last, r);
        refusal[r] = 0;
    }
    RValue_free(&result);
}

SLOT(refuseXZ) CODE static SwkbdCallbackResult refuseXZ(void* user, const char** ppMessage, const char* typed, size_t len) {
    (void) user;
    for (size_t i = 0; len > i && typed[i] != 0; i++) {
        char c = typed[i];
        if (c == 'x' || c == 'X' || c == 'z' || c == 'Z') {
            *ppMessage = refusal;
            return SWKBD_CALLBACK_CONTINUE;
        }
    }
    return SWKBD_CALLBACK_OK;
}

// The key a PC player presses for c, 0 for a character the essay cannot take.
SLOT(keyFor) CODE static int32_t keyFor(char c) {
    if (c >= 'a' && c <= 'z') c = (char) (c - 'a' + 'A');
    if (c == 'X' || c == 'Z') return 0;
    if ((c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') || c == ' ') return (uint8_t) c;
    for (int32_t i = 0; kShiftedDigits[i] != 0; i++) {
        if (kShiftedDigits[i] == c) return '0' + i;
    }
    for (int32_t i = 0; kPunct[i] != 0; i++) {
        if (kPunct[i] == c) return kPunctKey[i];
    }
    return 0;
}

// Keep only what the essay can take (printable ASCII, no X or Z), up to the cap.
SLOT(takeText) CODE static void takeText(const char* source) {
    textLen = textPos = 0;
    for (const char* p = source; *p != 0 && capChars > textLen; p++) {
        if (keyFor(*p) != 0) text[textLen++] = *p;
    }
    text[textLen] = 0;
    if (textLen != 0) phase = SWKBD_FEEDING;
}

// Keep the original 60 B entry so every existing late symbol retains its address.
SLOT(finishFeed) CODE __attribute__((naked)) static void finishFeed(Runner*) {
    __asm__("b essayendFinish\n.fill 14, 4, 0xe7f000f0\n");
}
#line 206

SLOT(feedStep) CODE static void feedStep(Runner* runner) {
    RunnerKeyboardState* kb = runner->keyboard;
    if (heldKey != 0) {
        RunnerKeyboard_simulateRelease(kb, heldKey);
        heldKey = 0;
    }
    Instance* essay = findEssay(runner, essayId);
    if (essay == nullptr || readInt(essay, idCantype) != 1 || textPos >= textLen) {
        finishFeed(runner);
        return;
    }
    // A real button pressed on this step makes the essay skip the step's character (as a second key would on PC),
    // so that character waits for the next step.
    for (int32_t key = 2; GML_KEY_COUNT > key; key++) {
        if (kb->keyPressed[key]) {
            kb->lastChar[0] = 0;
            return;
        }
    }
    char c = text[textPos++];
    heldKey = keyFor(c);
    RunnerKeyboard_simulatePress(kb, heldKey);
    kb->lastChar[0] = c;
    kb->lastChar[1] = 0;
    if (kb->stringLen < (int32_t) sizeof(kb->string) - 1) {
        kb->string[kb->stringLen++] = c;
        kb->string[kb->stringLen] = 0;
    }
}

SLOT(watchStep) CODE static void watchStep(Runner* runner) {
    if (runner->instancesByObject == nullptr) return;
    Instance** list = runner->instancesByObject[essayObject - 1];
    if (arrlen(list) == 0) return;
    Instance* essay = findEssay(runner, 0);
    if (essay == nullptr || essay->instanceId == handledId) return;
    if (readInt(essay, idKeyboardPresent) == 0 || readInt(essay, idCantype) != 1) return;
    handledId = essay->instanceId;
    // Character k is taken by the k-th step from the next one, after that step's alarm tick: the essay's alarm[0]
    // must still be running then. Once endbuffer runs out with no character typed, the game cuts the alarm to 10.
    int32_t left = essay->alarm[0];
    if (readInt(essay, idEndbuffer) < 2 && left > 11) left = 11;
    capChars = left - SWKBD_TIME_MARGIN;
    if (capChars > SWKBD_MAX_CHARS) capChars = SWKBD_MAX_CHARS;
    if (capChars < 1) return;
    essayId = essay->instanceId;
    if (CtrBench_running()) {
        char* source = runner->fileSystem->vtable->readFileText(runner->fileSystem, kTestFile);
        if (source == nullptr) return;
        bool applet = true;
        for (int32_t i = 0; kAppletMarker[i] != 0; i++) applet = applet && source[i] == kAppletMarker[i];
        if (!applet) {
            takeText(source);
            free(source);
            logInfo(logTyped, (unsigned long) essayId, (int) textLen, kFromTest);
            return;
        }
        free(source);
    }
    readPrompt(runner, essay);
    phase = SWKBD_PENDING;
}

SLOT(CTR_STEP_SWKBD) CODE void CTR_STEP_SWKBD(Runner* runner) {
    if (runner != swRunner || runner->dataWin != swData) resolve(runner);
    if (resetDelta) {
        resetDelta = false;
        uint32_t speed = runner->currentRoom != nullptr && runner->currentRoom->speed != 0 ? runner->currentRoom->speed : 30;
        runner->deltaTime = (GMLReal) (int32_t) (1000000u / speed);
    }
    if (essayObject > 0) {
        if (phase == SWKBD_FEEDING) feedStep(runner);
        else if (phase == SWKBD_IDLE) watchStep(runner);
    }
    __real_Runner_step(runner);
}

// Keep the original 208 B entry, including its unexecuted tail (same size on Old and New).
SLOT(openKeyboard) CODE __attribute__((naked)) static void openKeyboard(void) {
    __asm__("b essayendOpen\n.fill 51, 4, 0xe7f000f0\n");
}
#line 301

SLOT(CTR_ENDFRAME_SWKBD) CODE void CTR_ENDFRAME_SWKBD(Renderer* renderer) {
    CTR_ENDFRAME_AFTER_SWKBD(renderer);
    if (phase == SWKBD_PENDING) openKeyboard();
}

// Applet-only finish, appended to the late text. capChars is no longer needed after takeText: negative
// values reuse its storage as the 15-frame hold countdown. A regular bench keeps its positive character cap and
// therefore reaches the original finish path, without changing the game's alarm. No new data or BSS.
#define ESSAYEND __attribute__((used, noinline, section(".text.late.essayend")))

ESSAYEND static void essayendFinish(Runner* runner) {
    if (heldKey != 0) RunnerKeyboard_simulateRelease(runner->keyboard, heldKey);
    heldKey = 0;
    runner->keyboard->lastChar[0] = 0;
    phase = SWKBD_IDLE;
    if (capChars >= 0) return;
    Instance* essay = findEssay(runner, essayId);
    if (essay == nullptr || readInt(essay, idCantype) != 1) {
        capChars = 0;
        return;
    }
    if (++capChars < 0) {
        phase = SWKBD_FEEDING;
        return;
    }
    // Runner_step ticks alarms before Step: the game's Alarm 0 sets cantype=0/con=1, then its Draw evaluates
    // the essay, awards the rating, saves the flag and starts the reply. Never extend an already expired alarm.
    if (essay->alarm[0] > 1) essay->alarm[0] = 1;
}

ESSAYEND static void essayendOpen(void) {
    phase = SWKBD_IDLE;
    logInfo(logOpen, (unsigned long) essayId, (int) capChars);
    SwkbdState swkbd;
    swkbdInit(&swkbd, SWKBD_TYPE_QWERTY, 2, capChars);
    swkbdSetHintText(&swkbd, hint);
    swkbdSetValidation(&swkbd, SWKBD_ANYTHING, SWKBD_FILTER_CALLBACK, 0);
    swkbdSetFilterCallback(&swkbd, refuseXZ, nullptr);
    char typed[SWKBD_MAX_CHARS * 3 + 1];
    typed[0] = 0;
    swkbdInputText(&swkbd, typed, sizeof(typed));
    resetDelta = true;
    textLen = textPos = 0;  // Cancel/empty must not replay a previous essay's text.
    if (swkbdGetResult(&swkbd) == SWKBD_D1_CLICK1) {
        takeText(typed);
        logInfo(logTyped, (unsigned long) essayId, (int) textLen, kFromApplet);
    }
    capChars = -15;
    phase = SWKBD_FEEDING;  // Also count the hold when Cancel or OK supplies no characters.
}
