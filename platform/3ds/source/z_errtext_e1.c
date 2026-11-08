// E1: long physical button names without growing the game's three-byte STRG slots.
// Existing A/B/X/Y/L/R prompts and sprites keep their original path. Only the
// guarded replacement slots may expand; arbitrary game strings never match by text.
#if defined(ENABLE_WAD16) && defined(__3DS__)
#include <3ds.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_display.h"
#include "ctr_input_map.h"
#include "ctr_textures.h"
#include "renderer.h"
#include "runner.h"
#include "stb_ds.h"
#include "vm.h"

#define E1_CODE __attribute__((noinline, optimize("Os"), section(".text.errtext_e1")))
#define E1_RO __attribute__((section(".rodata.errtext_e1_in_text")))
#define E1_STATE __attribute__((section(".data_errtext_e1")))

// Zero-storage aliases of the original private symbols. Neither old slot grows.
extern char* Errtext_slots[5];
bool Errtext_title(const CtrInputMap* map, char out[19]);
extern const uint32_t Errtext_textureCacheAt;
extern bool (*const Errtext_fontTexel)(CtrPage* page, int32_t x, int32_t y, uint32_t* out);
void __real_Colline14_registerAll(VMContext* ctx);
bool __real_CtrBtnprompt_begin(void);
int32_t __real_CtrBtnprompt_buttonSprite(Renderer* renderer, char control);
void __real_Btnprompt_setLabels(const char letters[3], const char* title);
void __real_CtrRenderer_chainDisplayInputlate(Renderer* renderer, const CtrDisplaySettings* settings);
void __real_CtrArgui_chainSaveEditsSmalltext(const CtrDisplaySettings* before, const CtrDisplaySettings* after,
                                          const char* path, CtrDisplayCaps caps);

static const char e1ReplaceName[] E1_RO = "string_replace_all";
static const char e1FontName[] E1_RO = "fnt_small";
static const char e1Names[3][8] E1_RO = {"[ZL]", "[ZR]", "[START]"};
static const uint8_t e1Keys[3][2] E1_RO = {
    {GAME_KEY_Z, GAME_KEY_ENTER}, {GAME_KEY_X, GAME_KEY_SHIFT}, {GAME_KEY_C, GAME_KEY_CTRL}
};
// Explicit zeroes in the paid data reserve preserve the Old BSS page boundary.
// These values are mutable; code/constant pages must never hold writable state.
static uint8_t e1Rows[3] E1_STATE = {0};
static int32_t e1Sprites[3] E1_STATE = {0}; // index + 1, cleared at every VM load
static BuiltinFunc e1PreviousReplace E1_STATE = nullptr;
static CtrInputMap e1Map E1_STATE = {{0}};
static bool e1FilterTitle E1_STATE = false;

// Keep the existing short-button preference (including its alternate key),
// then use a long name if no short button can perform the action.
static E1_CODE uint8_t e1Row(const CtrInputMap* map, unsigned action) {
    for (unsigned group = 0; group != 2; ++group)
        for (unsigned pass = 0; pass != 2; ++pass)
            for (unsigned row = group ? MAP_ROW_ZL : MAP_ROW_A;
                 row <= (unsigned) (group ? MAP_ROW_START : MAP_ROW_R); ++row)
                if (map->keys[row] == e1Keys[action][pass]) return (uint8_t) row;
    return MAP_ROW_COUNT;
}

// Observe existing display/save links before btnLabels runs. Only the
// prompt view is filtered; gameplay settings and all old prompt bodies stay put.
static E1_CODE void e1Capture(const CtrInputMap* map) {
    e1Map = *map;
    bool isNew = false;
    if (R_FAILED(APT_CheckNew3DS(&isNew))) isNew = false;
    e1FilterTitle = !isNew &&
        (map->keys[MAP_ROW_ZL] != GAME_KEY_NONE || map->keys[MAP_ROW_ZR] != GAME_KEY_NONE);
    if (!isNew) {
        e1Map.keys[MAP_ROW_ZL] = GAME_KEY_NONE;
        e1Map.keys[MAP_ROW_ZR] = GAME_KEY_NONE;
    }
    for (unsigned action = 0; action != 3; ++action) e1Rows[action] = e1Row(&e1Map, action);
}

E1_CODE void __wrap_CtrRenderer_chainDisplayInputlate(Renderer* renderer, const CtrDisplaySettings* settings) {
    __real_CtrRenderer_chainDisplayInputlate(renderer, settings);
    e1Capture(&settings->controls);
}

E1_CODE void __wrap_CtrArgui_chainSaveEditsSmalltext(const CtrDisplaySettings* before, const CtrDisplaySettings* after,
                                                 const char* path, CtrDisplayCaps caps) {
    __real_CtrArgui_chainSaveEditsSmalltext(before, after, path, caps);
    e1Capture(&after->controls);
}

E1_CODE void __wrap_Btnprompt_setLabels(const char letters[3], const char* title) {
    char filtered[19];
    if (e1FilterTitle) title = Errtext_title(&e1Map, filtered) ? filtered : nullptr;
    __real_Btnprompt_setLabels(letters, title);
}

static E1_CODE RValue e1Replace(VMContext* ctx, RValue* args, int32_t count) {
    if (count >= 3 && args[2].type == RVALUE_STRING) {
        for (unsigned action = 0; action != 3; ++action) {
            unsigned row = e1Rows[action];
            if (row >= MAP_ROW_ZL && row <= MAP_ROW_START &&
                args[2].string != nullptr && args[2].string == Errtext_slots[action]) {
                // The original implementation reads only its first three args.
                // Temporarily replace this borrowed argument; restore even when
                // the result is the unchanged input (empty/missing needle).
                RValue saved = args[2];
                args[2] = RValue_makeString(e1Names[row - MAP_ROW_ZL]);
                // A lone icon belongs to the game's icon parser: keep its escape
                // for the game's sprite parser. Prose still uses the full name.
                if (args[0].type == RVALUE_STRING && args[1].type == RVALUE_STRING &&
                    args[0].string != nullptr && args[1].string != nullptr) {
                    const char* needle = args[1].string;
                    if (needle[0] == '\\' && needle[1] == '*' &&
                        needle[2] == (action == 0 ? 'Z' : action == 1 ? 'X' : 'C') &&
                        needle[3] == '\0' && strcmp(args[0].string, needle) == 0)
                        args[2] = args[1];
                }
                RValue result = e1PreviousReplace(ctx, args, count);
                args[2] = saved;
                return result;
            }
        }
    }
    return e1PreviousReplace(ctx, args, count);
}

E1_CODE void __wrap_Colline14_registerAll(VMContext* ctx) {
    __real_Colline14_registerAll(ctx);
    ptrdiff_t i = shgeti(ctx->builtinMap, (char*) e1ReplaceName);
    if (i >= 0 && ctx->builtinMap[i].value != nullptr && ctx->builtinMap[i].value != e1Replace) {
        e1PreviousReplace = ctx->builtinMap[i].value;
        ctx->builtinMap[i].value = e1Replace;
    }
}

E1_CODE bool __wrap_CtrBtnprompt_begin(void) {
    memset(e1Sprites, 0, sizeof(e1Sprites));
    return __real_CtrBtnprompt_begin();
}

static E1_CODE FontGlyph* e1Glyph(Font* font, unsigned ch) {
    for (uint32_t i = 0; i != font->glyphCount; ++i)
        if (font->glyphs[i].character == ch) return &font->glyphs[i];
    return nullptr;
}

// Appended after the last late section, outside this object's .text.* catch-all.
// Return the cell height and bottom source row in the ARM register pair.
static __attribute__((noinline, optimize("Os"), section(".errtext_center_late")))
uint64_t e1CenteredCell(int32_t height) {
    int32_t top = height < 14 ? (14 - height) / 2 : 0;
    if (height < 14) height = 14;
    return ((uint64_t) (uint32_t) (height - 1 - top) << 32) | (uint32_t) height;
}

// Copy the game's own fnt_small coverage, in its existing dimensions, as white
// ink (the game's draw_sprite colour supplies the prompt's tint).
// No font artwork or glyph table is added to RomFS or committed to the repo.
static E1_CODE int32_t e1FontSprite(Renderer* renderer, unsigned row) {
    DataWin* dw = renderer->dataWin;
    Font* font = nullptr;
    for (uint32_t i = 0; i != dw->font.count; ++i)
        if (dw->font.fonts[i].present && dw->font.fonts[i].name != nullptr &&
            strcmp(dw->font.fonts[i].name, e1FontName) == 0) { font = &dw->font.fonts[i]; break; }
    if (font == nullptr || font->tpagIndex < 0 || (uint32_t) font->tpagIndex >= dw->tpag.count) return -4;
    TexturePageItem* item = &dw->tpag.items[font->tpagIndex];
    if (!item->present || item->texturePageId < 0) return -4;
    const char* name = e1Names[row - MAP_ROW_ZL];
    // Omit the brackets for the sprite, just as the existing six button sprites.
    int32_t width = 0, height = 0, extent = 0;
    for (unsigned i = 1; name[i] != ']'; ++i) {
        FontGlyph* glyph = e1Glyph(font, (unsigned char) name[i]);
        if (glyph == nullptr || glyph->offset < 0 || glyph->shift <= 0) return -4;
        int32_t right = width + glyph->offset + glyph->sourceWidth;
        if (right > 96 || glyph->sourceHeight > 32) return -4;
        if (right > extent) extent = right;
        if ((int32_t) glyph->sourceHeight > height) height = glyph->sourceHeight;
        width += glyph->shift;
    }
    if (extent > width) width = extent;
    if (width <= 0 || width > 96 || height <= 0) return -4;
    // Match the existing button sprites' 14 px cell without scaling the font art.
    uint64_t cell = e1CenteredCell(height);
    height = (uint32_t) cell;
    int32_t rowBase = (uint32_t) (cell >> 32);
    CtrTextureCache* cache = (CtrTextureCache*) (void*) ((char*) renderer + Errtext_textureCacheAt);
    CtrPage* page = CtrTextures_acquire(cache, (uint32_t) item->texturePageId);
    if (page == nullptr || !page->layoutKnown || page->tileW <= 0 || page->tileH <= 0) return -4;
    const RendererVtable* vt = renderer->vtable;
    if (vt->createSurface == nullptr || vt->surfaceSetPixels == nullptr ||
        vt->createSpriteFromSurface == nullptr || vt->surfaceFree == nullptr) return -4;
    uint8_t* rgba = calloc((size_t) width * height, 4);
    if (rgba == nullptr) return -4;
    int32_t sprite = -4;
    int32_t pen = 0;
    for (unsigned i = 1; name[i] != ']'; ++i) {
        FontGlyph* glyph = e1Glyph(font, (unsigned char) name[i]);
        int32_t x0 = item->sourceX + glyph->sourceX, y0 = item->sourceY + glyph->sourceY;
        if (x0 + glyph->sourceWidth > page->width || y0 + glyph->sourceHeight > page->height) goto done;
        if (glyph->sourceWidth != 0 && glyph->sourceHeight != 0) {
            CtrTextures_ensureTiles(cache, page, x0 / page->tileW, y0 / page->tileH,
                (x0 + glyph->sourceWidth - 1) / page->tileW, (y0 + glyph->sourceHeight - 1) / page->tileH);
            for (unsigned y = 0; y != glyph->sourceHeight; ++y)
                for (unsigned x = 0; x != glyph->sourceWidth; ++x) {
                    uint32_t colour;
                    int32_t px = x0 + (int32_t) x, py = y0 + (int32_t) y;
                    if (!Errtext_fontTexel(page, px, py, &colour)) goto done;
                    CtrTile* tile = &page->tiles[(py / page->tileH) * page->tilesX + px / page->tileW];
                    uint8_t alpha = tile->format == CTR_TILE_RGBA8 ? (uint8_t) colour : colour != 0 ? 255 : 0;
                    uint8_t* p = rgba + ((rowBase - y) * width + pen + glyph->offset + x) * 4;
                    p[0] = 255; p[1] = 255; p[2] = 255; p[3] = alpha;
                }
        }
        pen += glyph->shift;
    }
    int32_t surface = vt->createSurface(renderer, width, height);
    if (surface >= 0) {
        if (vt->surfaceSetPixels(renderer, surface, rgba))
            sprite = vt->createSpriteFromSurface(renderer, surface, 0, 0, width, height, false, false, 0, 0);
        vt->surfaceFree(renderer, surface);
    }
done:
    free(rgba);
#if defined(__arm__)
    // Retain the pre-centering 1,240 B ARM slot; later functions must not move.
    __asm__ volatile("nop\n\tnop\n\tnop");
#endif
    return sprite < 0 ? -4 : sprite;
}

E1_CODE int32_t __wrap_CtrBtnprompt_buttonSprite(Renderer* renderer, char control) {
    unsigned action = control == 'Z' ? 0 : control == 'X' ? 1 : control == 'C' ? 2 : 3;
    if (action >= 3 || e1Rows[action] < MAP_ROW_ZL || e1Rows[action] > MAP_ROW_START)
        return __real_CtrBtnprompt_buttonSprite(renderer, control);
    if (renderer == nullptr || renderer->dataWin == nullptr) return -4;
    unsigned index = e1Rows[action] - MAP_ROW_ZL;
    int32_t sprite = e1Sprites[index] - 1;
    Sprt* sprt = &renderer->dataWin->sprt;
    if (sprite >= 0 && (uint32_t) sprite < sprt->count && sprt->sprites[sprite].present) return sprite;
    sprite = e1FontSprite(renderer, e1Rows[action]);
    e1Sprites[index] = sprite + 1;
    return sprite;
}
#endif
