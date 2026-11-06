// bulletsplit (change creddodge; UNDERTALE Old 3DS writerfront builds only): the credits pinwheel's run of bullets draws
// its text after the run's last Draw event, in one loop, instead of inside each event.
//
// Why: a bullet's Draw event is about 11 KB of code (dispatch, the event's regions, collision_line, sin and cos) and
// its text about 16-20 KB more (drawTextImpl, the glyph emit, the batch flush, citro3d). Taken in turn, once per bullet,
// the two together miss a 16 KB I-cache on nearly every line (P46's 40k misses a frame, about 6 ms of the pinwheel's
// Draw on the o3DS); taken apart, each loop stays in the cache after its first bullet. The peak frames have no other
// exact lever left.
//
// What: a wrapper bound over the event. While the generated function runs, the renderer table's drawText is bsCapture,
// which copies its arguments and the five draw fields the text reads. After the event: if the next drawable the room
// loop will run is another bullet at the same depth, the copies wait for it; otherwise they are all drawn now, in order,
// each with its own draw fields, and those fields are put back.
//
// Exactness (the full argument is in the results file):
// - The event and its hit event are pinned by their bytecode's FNV-1a 64 digests. Between them they call only
//   draw_set_halign, draw_set_font, draw_set_color (each only stores a renderer field), lengthdir_x / y, abs,
//   collision_line, event_user(1) and draw_text_transformed: so nothing but the text draws, no RNG, no sound, no
//   instance is made or destroyed, and no game state reads anything the text draw writes.
// - The text calls keep their order and arguments, and each sees the fields it would have seen. The drawTextImpl path
//   reads the instance only through the current object (the same object here) and the draw depth (the same depth: the
//   wait requires it).
// - Nothing else draws while copies wait. The wait is taken only where the room loop's next step is this code: no list
//   change pending, no draw skip, the entries up to the next bullet are ones the loop passes over (an instance not
//   active or not visible). utkDrawArmed runs between the two but arms nothing for an object with a Draw event.
//   Any other entry, a span, a tile, the list's end or another object means the copies are drawn before the event
//   returns. So a menu, a room change, Draw End or a frame's end never meet a waiting copy; bsLate counts it if they did.
// - No room in the copies (a run longer than BS_MAX, or too much text) only draws what waits, sooner, in order. A string
//   too long for the block goes the normal way after that.
//
// Binding: at each room change through the prefetchRoom chain, after writerfirst's link, over the generated function
// (VM_aotSwapFront, as writerfront). bsSwitch[1] is the one test switch: 0 leaves the wrapper unbound. Test builds flip
// that word in the 3dsx so an off arm is the same binary. Late text, constants and bss only.

#if defined(CTRPORT_WRITERFRONT) && defined(CTRPORT_DODGEFRONT) && defined(ENABLE_WAD16) && defined(__3DS__)

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "aot/vm_aot.h"
#include "ctr_wrap_chain.h"
#include "data_win.h"
#include "instance.h"
#include "log.h"
#include "renderer.h"
#include "runner.h"
#include "stb_ds.h"
#include "vm.h"

#define BS_CODE __attribute__((noinline, section(".text_bulletsplit")))
#define BS_RO __attribute__((aligned(4), section(".rodata.bulletsplit_in_text")))
#define BS_BSS __attribute__((section(".bss.bulletsplit_late")))

typedef RValue (*BsFn)(VMContext* ctx);
bool VM_aotSwapFront(VMContext* ctx, int32_t codeIndex, BsFn fn, BsFn generated);

// The most that wait. The pinwheel fills it (diag: a 64-entry run, up to 82 texts a frame): full flushes and carries on.
#define BS_MAX 64
#define BS_TEXT 2048

typedef struct {
    float x, y, xscale, yscale, angle, lineSeparation;
    float alpha;
    uint32_t color;
    int32_t font, halign, valign;
    uint32_t at; // in bsText
} BsCopy;

typedef void (*BsDrawText)(Renderer* renderer, const char* text, float x, float y, float xscale, float yscale, float angleDeg,
                           float lineSeparation);

// The event, then its hit event: length, the name's FNV-1a 32, the digest's low and high words (UNDERTALE 1.08, Steam
// and GOG).
static const uint32_t bsPin[2][4] BS_RO = {{2300u, 0x81282B11u, 0xD3E7E710u, 0x5B1F010Au},
                                           {116u, 0x75FF07DDu, 0x854BD334u, 0xFD181C52u}};
// A marker and the switch: flip.py finds the marker in the 3dsx to set the word after it to 0 (an off arm).
static const volatile uint32_t bsSwitch[2] BS_RO = {0x53504C54u, 1u};
static const char bsLog[] BS_RO = "bulletsplit: %ld\n";
static const char bsCountLog[] BS_RO = "bulletsplit: %lu runs, %lu texts, longest %lu, late %lu\n";

static DataWin* bsChecked BS_BSS; // the data.win below is for
static int32_t bsCode BS_BSS;     // the event's code index, or -1
static BsFn bsGen BS_BSS;         // its generated function
static BsDrawText bsReal BS_BSS;  // the table's own drawText while bsCapture stands in
static int32_t bsCursor BS_BSS;   // where in the drawables the running instance was last found
static int32_t bsFrame BS_BSS;    // the frame of what waits
static uint32_t bsN BS_BSS;       // copies waiting
static uint32_t bsAt BS_BSS;      // bsText used
static uint32_t bsRuns BS_BSS, bsTexts BS_BSS, bsLongest BS_BSS, bsLate BS_BSS, bsLogged BS_BSS;
static BsCopy bsCopies[BS_MAX] BS_BSS;
static char bsText[BS_TEXT] BS_BSS;

// Draws what waits, in order, each with its own draw fields; the fields as they were after. The real drawText, so a state
// hash's wrapper sees them as it would have.
static BS_CODE void bsFlush(Renderer* r) {
    uint32_t n = bsN;
    if (n == 0) return;
    BsDrawText real = bsReal;
    uint32_t color = r->drawColor;
    float alpha = r->drawAlpha;
    int32_t font = r->drawFont, halign = r->drawHalign, valign = r->drawValign;
    for (uint32_t i = 0; n > i; i++) {
        const BsCopy* c = &bsCopies[i];
        r->drawColor = c->color;
        r->drawAlpha = c->alpha;
        r->drawFont = c->font;
        r->drawHalign = c->halign;
        r->drawValign = c->valign;
        real(r, bsText + c->at, c->x, c->y, c->xscale, c->yscale, c->angle, c->lineSeparation);
    }
    r->drawColor = color;
    r->drawAlpha = alpha;
    r->drawFont = font;
    r->drawHalign = halign;
    r->drawValign = valign;
    bsN = 0;
    bsAt = 0;
    bsRuns++;
    bsTexts += n;
    if (n > bsLongest) bsLongest = n;
}

// The table's drawText during the event. The text is only borrowed from the builtin: it is copied.
static BS_CODE void bsCapture(Renderer* r, const char* text, float x, float y, float xscale, float yscale, float angleDeg,
                              float lineSeparation) {
    uint32_t size = (uint32_t) strlen(text) + 1;
    if (bsN == BS_MAX || size > BS_TEXT - bsAt) {
        bsFlush(r);
        if (size > BS_TEXT) {
            bsReal(r, text, x, y, xscale, yscale, angleDeg, lineSeparation);
            return;
        }
    }
    BsCopy* c = &bsCopies[bsN++];
    c->x = x;
    c->y = y;
    c->xscale = xscale;
    c->yscale = yscale;
    c->angle = angleDeg;
    c->lineSeparation = lineSeparation;
    c->alpha = r->drawAlpha;
    c->color = r->drawColor;
    c->font = r->drawFont;
    c->halign = r->drawHalign;
    c->valign = r->drawValign;
    c->at = bsAt;
    memcpy(bsText + bsAt, text, size);
    bsAt += size;
}

// Whether the room loop's next step after self's event is another event of this code at the same depth. Every entry it
// passes over here is one utkDrawRoom skips without running anything.
static BS_CODE bool bsNextRuns(const Runner* runner, const Instance* self) {
    if (runner->drawableListSortDirty || runner->drawableListStructureDirty || !runner->drawEnabled) return false;
    const Drawable* list = runner->cachedDrawables;
    int32_t n = (int32_t) arrlen(list);
    int32_t at = bsCursor;
    if (at >= n || list[at].type != DRAWABLE_INSTANCE || list[at].elementOrder != 0 || list[at].instance != self) {
        for (at = 0; n > at; at++) {
            if (list[at].type == DRAWABLE_INSTANCE && list[at].elementOrder == 0 && list[at].instance == self) break;
        }
        if (at == n) return false;
    }
    int32_t depth = list[at].depth;
    for (int32_t j = at + 1; n > j; j++) {
        const Drawable* e = &list[j];
        if (e->type != DRAWABLE_INSTANCE || e->layerOrder != 0 || e->elementOrder != 0) return false;
        const Instance* q = e->instance;
        if (!q->active || !q->visible) continue;
        if (q->objectIndex != self->objectIndex || e->depth != depth) return false;
        bsCursor = j;
        return true;
    }
    return false;
}

static BS_CODE RValue bsFront(VMContext* ctx) {
    Runner* runner = ctx->runner;
    Renderer* r = runner->renderer;
    Instance* self = (Instance*) ctx->currentInstance;
    // A frame that isn't shown takes the normal way (a muted draw is the renderer's business). Nothing waits here then:
    // bsNextRuns below never waits while a skip is on.
    if (runner->drawSkip.active || r->drawMuted || self == NULL) return bsGen(ctx);
    if (bsN != 0 && bsFrame != runner->frameCount) {
        // Never: a wait always ends in its own frame's pass.
        bsLate++;
        bsFlush(r);
    }
    RendererVtable* vt = r->vtable;
    BsDrawText real = vt->drawText;
    bsReal = real;
    vt->drawText = bsCapture;
    bsFrame = runner->frameCount;
    RValue v = bsGen(ctx);
    vt->drawText = real;
    if (!bsNextRuns(runner, self)) bsFlush(r);
    return v;
}

static BS_CODE uint64_t bsDigest(DataWin* dw, CodeEntry* code) {
    const uint8_t* bytes = DataWin_codeBytes(dw, code);
    if (bytes == NULL || code->offset > code->length) return 0;
    uint64_t h = 0xCBF29CE484222325ull;
    for (uint32_t i = code->offset; code->length > i; i++) {
        h ^= bytes[i];
        h *= 0x100000001B3ull;
    }
    return h;
}

// The lookups, once per data.win: 0 when all match, else the step that didn't (for the log).
static BS_CODE int32_t bsCheck(DataWin* dw) {
    int32_t found[2] = {-1, -1};
    for (uint32_t i = 0; dw->code.count > i; i++) {
        CodeEntry* code = &dw->code.entries[i];
        if (code->name == NULL) continue;
        for (int k = 0; 2 > k; k++) {
            if (code->length != bsPin[k][0]) continue;
            uint32_t nh = 2166136261u;
            for (const char* c = code->name; *c != '\0'; c++) nh = (nh ^ (uint8_t) *c) * 16777619u;
            if (nh != bsPin[k][1]) continue;
            if (found[k] != -1) return 1;
            found[k] = (int32_t) i;
        }
    }
    for (int k = 0; 2 > k; k++) {
        if (0 > found[k]) return 2;
        if (bsDigest(dw, &dw->code.entries[found[k]]) != (((uint64_t) bsPin[k][3] << 32) | bsPin[k][2])) return 3;
    }
    // The generated function: aotBind's first entry of this name, which must match as aotMatches checks.
    CodeEntry* code = &dw->code.entries[found[0]];
    for (uint32_t e = 0; aotTable.entryCount > e; e++) {
        const AotEntry* en = &aotTable.entries[e];
        if (en->fn == NULL || strcmp(en->codeName, code->name) != 0) continue;
        if (en->offset != code->offset || en->blobLength != code->length || en->end != code->length
            || en->digest != (((uint64_t) bsPin[0][3] << 32) | bsPin[0][2]))
            return 4;
        for (uint32_t i = 0; en->varCount > i; i++) {
            const AotVarRef* ref = &en->vars[i];
            Variable* v = ref->index < dw->vari.variableCount ? &dw->vari.variables[ref->index] : NULL;
            if (v == NULL || v->varID != ref->varID || v->instanceType != ref->instanceType || v->name == NULL
                || strcmp(v->name, ref->name) != 0)
                return 5;
        }
        for (uint32_t i = 0; en->funcCount > i; i++) {
            const AotFuncRef* ref = &en->funcs[i];
            if (ref->index >= dw->func.functionCount || dw->func.functions[ref->index].name == NULL
                || strcmp(dw->func.functions[ref->index].name, ref->name) != 0)
                return 6;
        }
        bsGen = en->fn;
        break;
    }
    if (bsGen == NULL) return 7;
    bsCode = found[0];
    return 0;
}

// The prefetchRoom chain's link after writerfirst's: finds the event (once per data.win), binds the wrapper, logs the
// count when it changed, then the next link.
BS_CODE void CTR_PREFETCHROOM_BULLETSPLIT(Renderer* renderer) {
    Runner* runner = renderer != NULL ? renderer->runner : NULL;
    VMContext* ctx = runner != NULL ? runner->vmContext : NULL;
    DataWin* dw = ctx != NULL ? ctx->dataWin : NULL;
    if (dw != NULL && bsSwitch[1] != 0) {
        int32_t step = 0;
        if (bsChecked != dw) {
            bsChecked = dw;
            bsCode = -1;
            bsGen = NULL;
            step = bsCheck(dw);
            if (step != 0) bsCode = -1;
            logInfo(bsLog, (long) (step != 0 ? -step : bsCode));
        }
        if (bsCode >= 0) (void) VM_aotSwapFront(ctx, bsCode, bsFront, bsGen);
    }
    if (bsN != 0) {
        // Never (bsFront's end): dropped, counted.
        bsLate++;
        bsN = 0;
        bsAt = 0;
    }
    if (bsRuns != bsLogged) {
        bsLogged = bsRuns;
        logInfo(bsCountLog, (unsigned long) bsRuns, (unsigned long) bsTexts, (unsigned long) bsLongest, (unsigned long) bsLate);
    }
    CTR_PREFETCHROOM_AFTER_BULLETSPLIT(renderer);
}

#endif
