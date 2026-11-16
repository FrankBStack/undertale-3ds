// storyentry (change storyentry, 11-15; UNDERTALE Old): a New Home story battle reads its own monsters ahead.
//
// One room (the story battle room) holds 18 story battles. The corridor's trigger sets global.flag[450] and starts the
// encounter animation; the object placed in the battle room then makes the monsters `if flag[450] == K`. The room's plan
// scene has one encounter's monsters, so btlentry's read-ahead (z_btlentry.c's btTarget) read the rest of the room's set
// during the soul's flight and left the others' art to the room change frame, read from the SD card while the last
// flight picture stayed on screen: the hitch maintainer saw on the New Home walk (11-08, 11-15; ethanlog4.md section 2). The
// room plan now has a scene per encounter (build_plan.py story_encounters: sub STORY_SUB + K, the room scene's tiles and
// code and that encounter's art), and btTarget asks CtrStoryEntry_scene which one to read: flag[450]'s, as the game
// will pick it two frames later, else the room's own as before.
// CtrStoryEntry_makeRoom: at the battle room's load (z_btlentry.c's CtrStoryEntry_roomLoad, before bthand), room in the
// texture budget and linear memory for the tiles btlentry read, evicting as the room load's whole set does a moment later
// (usWholeMakeRoom): the scene's resident tiles count as used in the old room's last frame, then the least recently used
// tiles not drawn in it go. bthand left a tile without room to the room load, which read it again from the SD card.
// Reads the VM's state only (never writes it); textures only: which tiles are resident, never their texels, the game's
// state, its timing or its RNG. Its own AAC inputs (aacout.cmake, the last ones): no late text, data or bss.
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#if defined(ENABLE_WAD16) && defined(CTRPORT_STORYENTRY)
#include <3ds.h>

#include "ctr_textures.h"
#include "gml_array.h"
#include "instance.h"
#include "int_rvalue_hashmap.h"
#include "roomplan_format.h"
#include "runner.h"
#include "stb_ds.h"
#include "vm.h"

#ifdef ENABLE_WAD16 // AAC inputs: an explicit guard (test_aacslot_shared.py)
#define ST_TEXT __attribute__((noinline, section(".aacout.text.storyentry")))
// Constants in the text input (its own name with the assembler flags and a comment mark after it, so the compiler sees
// another section and takes no type conflict with the code): the AAC rodata slot ends in N8a release-only inputs.
#define ST_CONST __attribute__((aligned(4), section(".aacout.text.storyentry,\"ax\",%progbits @")))
#endif
#line 36
#define ST_FLAG 450      // build_plan.py STORY_FLAG: the element the story battle generator's Create tests
#define ST_SUB 0x8100u   // build_plan.py STORY_SUB: an encounter's scene is sub ST_SUB + K
#define ST_KEYS 256u     // build_plan.py STORY_KEYS
#define ST_KEY_MASK 0x07FFFFFFu

const uint8_t* CtrStoryEntry_scene(Runner* runner, const uint8_t* plan, int32_t room, int32_t* group);
bool CtrStoryEntry_makeRoom(CtrTextureCache* cache, const uint8_t* scene, uint64_t bytes, uint32_t floor);

static const char stFlag[] ST_CONST = "flag";

// global.flag[ST_FLAG] when it is a whole number below ST_KEYS (a value one of the Create's `== K` cases can match),
// else -1. The VM keeps a global under its VARI entry's id in the global scope's map; varNameMap gives a name's first
// entry's id, and the plan has encounter scenes only when that entry is the global (build_plan.py story_encounters,
// codeclose.global_var_id). The map's probe is written out here (no inline helper gets an out-of-line copy), and the
// array read as GMLArray_slot reads it.
static ST_TEXT int32_t stEncounter(Runner* runner) {
    VMContext* ctx = runner->vmContext;
    if (ctx == nullptr || ctx->globalScopeInstance == nullptr) return -1;
    ptrdiff_t slot = shgeti(ctx->varNameMap, (char*) stFlag);
    if (0 > slot) return -1;
    int32_t key = (int32_t) ctx->varNameMap[slot].value;
    const IntRValueHashMap* map = &ctx->globalScopeInstance->selfVars;
    const RValue* value = nullptr;
    uint32_t idx = ((uint32_t) key * 0x9E3779B9u) & map->mask;
    for (uint32_t n = 0; map->capacity > n; n++, idx = (idx + 1u) & map->mask) {
        if (map->entries[idx].key == key) {
            value = &map->entries[idx].value;
            break;
        }
        if (map->entries[idx].key == INT_RVALUE_HASHMAP_EMPTY_KEY) break;
    }
    if (value == nullptr || value->type != RVALUE_ARRAY || value->array == nullptr) return -1;
    const GMLArray* array = value->array;
    const RValue* cell = nullptr;
    if (array->type == GML_LEGACY_ARRAY) {
        if (array->legacy.rowCount > 0 && array->legacy.rows[0].length > ST_FLAG) cell = &array->legacy.rows[0].data[ST_FLAG];
    } else if (array->modern.length > ST_FLAG) {
        cell = &array->modern.data[ST_FLAG];
    }
    if (cell == nullptr) return -1;
    if (cell->type == RVALUE_INT32) return 0 <= cell->int32 && (int32_t) ST_KEYS > cell->int32 ? cell->int32 : -1;
    if (cell->type != RVALUE_REAL || !(cell->real >= 0) || !((GMLReal) ST_KEYS > cell->real)) return -1;
    int32_t k = (int32_t) cell->real;
    return (GMLReal) k == cell->real ? k : -1;
}

// btTarget's story branch: the plan's scene for the room's encounter now (sub ST_SUB + flag[450], *group = that sub)
// if the plan has one, else the room's own scene (*group = -1), as btTarget took it; null if the plan has neither.
ST_TEXT const uint8_t* CtrStoryEntry_scene(Runner* runner, const uint8_t* plan, int32_t room, int32_t* group) {
    *group = -1;
    if (0 > room) return nullptr;
    RoomPlanHeader h;
    memcpy(&h, plan, sizeof(h));
    size_t at = sizeof(h);
    const uint8_t* whole = nullptr;
    int32_t k = -2; // flag[450], read at the first encounter scene
    for (uint32_t i = 0; h.sceneCount > i; i++) {
        RoomPlanScene s;
        memcpy(&s, plan + at, sizeof(s));
        if (s.room == (uint32_t) room) {
            if (s.sub == ROOMPLAN_NO_SUB) {
                if (whole == nullptr) whole = plan + at;
            } else if (ST_KEYS > (uint32_t) s.sub - ST_SUB) {
                if (k == -2) k = stEncounter(runner);
                if ((uint32_t) k == (uint32_t) s.sub - ST_SUB) {
                    *group = (int32_t) s.sub;
                    return plan + at;
                }
            }
        }
        at += RoomPlan_sceneSize(&s);
    }
    return whole;
}

// Room for bytes more of the scene's tiles: below the texture budget, and with floor bytes of linear memory left after
// them. The scene's resident tiles first count as used in the frame before this one (the old room's last drawn frame:
// the room change frame isn't drawn), then the least recently used tiles not drawn since go, one at a time. False if no
// such tile is left and there is still no room.
ST_TEXT bool CtrStoryEntry_makeRoom(CtrTextureCache* cache, const uint8_t* scene, uint64_t bytes, uint32_t floor) {
    if (cache->frame == 0) return false;
    RoomPlanScene s;
    memcpy(&s, scene, sizeof(s));
    for (uint32_t i = 0; s.tileCount > i; i++) {
        uint32_t entry;
        memcpy(&entry, scene + sizeof(s) + (size_t) i * 4u, 4);
        uint32_t p = (entry & ST_KEY_MASK) >> 8, t = entry & 0xFFu;
        if (p >= cache->pageCount) continue;
        CtrPage* page = &cache->pages[p];
        if (!page->layoutKnown || page->tiles == nullptr || t >= (uint32_t) (page->tilesX * page->tilesY)) continue;
        CtrTile* tile = &page->tiles[t];
        if (tile->valid && cache->frame - 1u > tile->lastUsedFrame) tile->lastUsedFrame = cache->frame - 1u;
    }
    while ((uint64_t) cache->residentBytes + bytes > (uint64_t) cache->budgetBytes ||
           (uint64_t) linearSpaceFree() < (uint64_t) floor + bytes) {
        if (!CtrTextures_evictLeastRecentIdle(cache, 1)) return false;
    }
    return true;
}
#endif
