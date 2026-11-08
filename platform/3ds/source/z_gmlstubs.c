// Legacy room background colour and foreground variables. The release's
// original dispatch and drawing bodies retain their addresses and sizes.
#if defined(ENABLE_WAD16)
// Reuse the engine's exported legacy conversion helpers.
#define RValue_toRealOther Colflip14_toRealOther
#define RValue_toInt32Other Colflip14_toInt32Other
#define RVALUE_OTHER_EXTERN
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include "z_gmlstubs.h"
#include "vm_builtins.h"

// IDs outside both the ordinary table and the physics range. No original
// lookup-table entry or dispatch jump table changes.
enum { GMLSTUBS_BLEND = 30000, GMLSTUBS_FOREGROUND = 30001 };
enum { GMLSTUBS_BACKGROUNDS = sizeof(((Runner*)0)->backgrounds) / sizeof(RuntimeBackground) };

static const char blendName[] = "background_blend";
static const char foregroundName[] = "background_foreground";

RValue __real_VMBuiltins_getVariable(VMContext*, Instance*, int16_t, const char*, int32_t);
void __real_VMBuiltins_setVariable(VMContext*, Instance*, int16_t, const char*, RValue, int32_t);
void Gmlstubs_initRoomOriginal(Runner*, int32_t);
void Gmlstubs_drawBackgroundOriginal(Runner*, int32_t, bool, float, float,
    bool, bool, float, float, float, float, float, float, uint32_t, float);

static uint32_t backgroundBlend(const RuntimeBackground* bg) {
    const unsigned char* bytes = Gmlstubs_colourBytesConst(bg);
    return 0xffffffu ^ ((uint32_t)bytes[0]
        | ((uint32_t)bytes[1] << 8)
        | ((uint32_t)bytes[2] << 16));
}

typedef struct { const char* name; int16_t id; } BackgroundVarEntry;
static const BackgroundVarEntry blendEntry = { blendName, GMLSTUBS_BLEND };
static const BackgroundVarEntry foregroundEntry = { foregroundName, GMLSTUBS_FOREGROUND };

void* Gmlstubs_varSearch(const void* key, const void* base, size_t count,
    size_t size, int (*compare)(const void*, const void*)) {
    void* hit = bsearch(key, base, count, size, compare);
    if (hit != nullptr) return hit;
    if (strcmp(key, blendName) == 0) return (void*)&blendEntry;
    if (strcmp(key, foregroundName) == 0) return (void*)&foregroundEntry;
    return nullptr;
}

RValue __wrap_VMBuiltins_getVariable(VMContext* ctx, Instance* inst,
    int16_t id, const char* name, int32_t index) {
    if (id != GMLSTUBS_BLEND && id != GMLSTUBS_FOREGROUND)
        return __real_VMBuiltins_getVariable(ctx, inst, id, name, index);
    if (index < 0 || index >= GMLSTUBS_BACKGROUNDS) return RValue_makeReal(0);
    RuntimeBackground* bg = &ctx->runner->backgrounds[index];
    return id == GMLSTUBS_BLEND ? RValue_makeReal(backgroundBlend(bg))
        : RValue_makeBool(bg->foreground);
}

void __wrap_VMBuiltins_setVariable(VMContext* ctx, Instance* inst,
    int16_t id, const char* name, RValue val, int32_t index) {
    if (id != GMLSTUBS_BLEND && id != GMLSTUBS_FOREGROUND) {
        __real_VMBuiltins_setVariable(ctx, inst, id, name, val, index);
        return;
    }
    if (index < 0 || index >= GMLSTUBS_BACKGROUNDS) return;
    RuntimeBackground* bg = &ctx->runner->backgrounds[index];
    if (id == GMLSTUBS_FOREGROUND) {
        bg->foreground = RValue_toBool(val);
    } else {
        uint32_t inverse = RValue_toColour(val) ^ 0xffffffu;
        unsigned char* bytes = Gmlstubs_colourBytes(bg);
        bytes[0] = inverse;
        bytes[1] = inverse >> 8;
        bytes[2] = inverse >> 16;
    }
}

void Gmlstubs_initRoom(Runner* runner, int32_t roomIndex) {
    // Fresh rooms start white. The original persistent-room restore copies
    // the complete saved background array, including these three bytes.
    for (int i = 0; i < GMLSTUBS_BACKGROUNDS; ++i)
        memset(Gmlstubs_colourBytes(&runner->backgrounds[i]), 0, 3);
    Gmlstubs_initRoomOriginal(runner, roomIndex);
}

void Gmlstubs_drawLegacy(Runner* runner, bool foreground) {
    if (runner->renderer == nullptr) return;
    float width = runner->currentRoom->width;
    float height = runner->currentRoom->height;
    for (int i = 0; i < GMLSTUBS_BACKGROUNDS; ++i) {
        RuntimeBackground* bg = &runner->backgrounds[i];
        if (!bg->visible || bg->foreground != foreground || bg->backgroundIndex < 0) continue;
        int32_t tpag = Renderer_resolveBackgroundTPAGIndex(runner->dataWin, bg->backgroundIndex);
        Gmlstubs_drawBackgroundOriginal(runner, tpag, bg->stretch, width, height,
            bg->tileX, bg->tileY, bg->x, bg->y, 0, 0, bg->xScale, bg->yScale,
            backgroundBlend(bg), bg->alpha);
    }
}
#endif
