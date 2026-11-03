// btlentry (UNDERTALE Old): a battle's planned tiles are read during the encounter animation, before the room change.
//
// Playtest, 11-02 (Old 3DS XL, 75zm): "some battle screen entrance lag". When a battle starts, the screen goes black and the
// soul blinks and flies to the FIGHT button (about 31 frames); then the game goes to the battle room, and on the 64 MB Old
// models the room change frame loads the battle group's whole tile set (z_utstall.c item 5) and its code: 0.5-1.15 s at
// the first fight of each group in his logs (Asgore 1153 ms, Mettaton 922 ms, Mad Dummy 805 ms), with the soul frozen
// on screen. Nearly all of it is tiles from the SD card, one page at a time on the game thread (10-110 ms a page), and
// the tile reader's read-ahead brought nothing ("read ahead 0 KB"): its reads want 8 MiB of heap free besides their
// bytes, and the Old heap has 6-7 MB free in play.
//
// So, once a frame in the overworld (from RoomLoad_collect's chain, as flowstream: utflPkCollect -> here -> flowstream),
// while an obj_battler or obj_battleblcon exists (the battle's start; neither reads anything here), the plan scene of
// global.battlegroup (the one the battle room's load will take) is walked in order, and its missing tiles are read on
// the reader thread, a page's missing planned tiles in one read (its header once, neighbouring tiles in one run) and
// three reads at a time (on different pages), admitted as flowstream's refill reads are (the promotion reserve, 4 MiB
// on UT Old, plus its bytes; heap relief off). A read whose bytes are in is installed tile by tile in later frames
// (CtrTextures_btlentryInstall: installTile, one tile's check, unpack and flush, 3-4 ms on the Old models), one a frame
// and more only while the frame's installs stay within BT_INSTALL_MS (by the costliest tile so far), each tile only if
// the texture budget and the linear floor leave room for it, else room is made by evicting tiles last drawn before
// the encounter started (round 4, below); a tile that still has no room is dropped. A read is released once its last
// tile is done. A page not loaded from yet this session takes its grid and tile table
// from the read's header, as its first load would (setLayout, applyView). The room change releases whatever is still
// in flight or not installed yet (releaseReads, which frees nothing installed), and the room load then finds the
// installed tiles resident and skips them, and reads the rest itself.
//
// The installs run in CtrTextures_beginFrame, before main.c takes the frame's start time, so a frame with installs
// starts (as the bench counts starts) that much after its slot, and the start interval into it is longer by the same
// (r2 console rows: one ~42 ms interval in the encounter room = 33.3 ms and two 3-4 ms installs of round 2's two reads,
// every frame still shown on time). BT_INSTALL_MS keeps a frame's installs within those two (what r2's rows passed on
// all three Old models), so the interval stays under ~42 ms; the log line gives the most install time one frame took.
//
// Optional all the way (c26rev r101): the game thread never does a read of ours (a wait for one of its own reads that
// takes ours from the queue gets no file, as flowstream's refill: F1); the tile's texture is allocated here without
// evicting anything and counted as a read's reserved tile, so installTile allocates nothing (F2); and the read record
// and a learned tile table are allocated with heap relief off.
//
// Round 4 (Asgore: the cache is full at the encounter, 26.0 of 26.0 MB, and r3 left 12 of his 42 missing tiles for
// the battle room's load, which then evicted 5.8 MB of other tiles itself): a tile without room evicts, oldest first as
// the cache's own eviction does (evictTile, through CtrTextures_btlentryEvict), only tiles last drawn before the
// encounter's first frame and not in the last CTR_THRASH_FRAMES frames, never a tile of the battle's planned set. Those
// are the tiles the battle room's load would evict for the same tiles a few frames later. Each evicted tile is
// remembered (the first BT_GONE), and one drawn again before the room change, so loaded again, is counted in the log
// line ("reloaded"); it must stay 0.
// Rev 2 (c26rev R109 F1: a tile last drawn before the encounter may still be one the encounter room draws again, a
// later animation frame or an object drawn now and then, and evicting it moves its reload into the animation): a
// victim must also be provably outside the room the encounter starts in, so never a tile the room wants (wanted), in
// its plan scene (the record's tiles of all its visits, CtrUtstall_activeScene) or among the tiles it drew on its last
// visits' entries (the cache's roomTiles). The plan scene is the room's whole set (tools/roomplan/build_plan.py
// whole_set: every frame of each sprite the records drew from, the room's backgrounds, tiles and placed objects' sprites,
// and the sprites of objects created in recorded play). A room with no plan scene, a scene without tiles (5 UT rooms
// have code only) or one cut at ROOMPLAN_TILES_MAX has no such proof: nothing is evicted there, and a tile without room
// is deferred, then dropped, as in round 3.
// Rev 2b (the r4 console rows: the cache wasn't full at Asgore, nothing could be evicted, and r4 still read tiles with
// no room and held a read up to 9 frames waiting for room, so it read fewer tiles than r3): at the encounter's first
// armed frame the victims btMakeRoom may take are counted once (their bytes, the pool, up to BT_POOL_ENOUGH). A tile
// without room is read only while the pool covers it and the tiles already taken on it, and only then waits for room or
// evicts. With an empty pool every choice is round 3's.
//
// Round 5 (the battle's code: r3 console rows left about 95-120 ms of the hold in the room load's bytecode reads,
// z_roomload.c rlReadCode, 8.5 ms a read on the Old models): while armed, the plan scene's code entries (the list the
// room load reads, RoomPlan_roomCode) whose group isn't in memory are read on the reader too, in file order, one read
// at a time of up to BT_CODE_SPANS runs (neighbouring groups with at most BT_CODE_GAP bytes between them in one run)
// and BT_CODE_BYTES. The read is a tile read with no cache page (pageId BT_CODE_PAGE): the reader's own file for it is
// the bytecode cache file (DataWin_moveBytecodeToFile's path, kept by its wrap), its "header" is that file's header,
// checked, and its "tiles" are the runs, in a one-column grid set up before it is queued; it is admitted and allocated
// as the tile reads are. Once its bytes are in, each of its groups not in memory meanwhile gets its code memory as the
// lazy path would give it (data_win.c allocCodeArena's 32 KB blocks and sizes; heap relief off, the promotion reserve
// left free, no growth of the block list) and its bytes, and its blobs point there: what DataWin_loadCodeBytes and
// rlReadCode do, on the game thread, with the same bytes from the same file. A group refused memory, a read refused
// or emptied (the game thread's wait gets no file for it, F1), and whatever the room change finds still in flight
// are left to the room load's own reads, as before.
//
// Textures and code loads only: no game state, script, timing the game sees or RNG changes; every tile is the same
// texels and every group the same bytes whenever it loads. Late code and statics only (late_reserve.ld, last).
#include <3ds.h>
#include <errno.h>
#include <malloc.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#if defined(ENABLE_WAD16) && defined(CTRPORT_FLOWSTREAM_READ)
#include "ctr_textures.h"
#include "ctr_tile_reader.h"
#include "log.h"
#include "roomplan_format.h"
#include "runner.h"
#include "stb_ds.h"

// Late code, every function here (no noinline: GCC may inline a static into its callers, all of them in this section;
// that keeps btlentry inside its fixed 7,428 B slot, late_reserve.ld).
#ifdef CTRPORT_BTLENTRY_DIAG
#define BT_TEXT __attribute__((section(".text.btlentry_diag"))) // LAB ONLY: the diag's hooks outgrow the slot; .text takes it
#else
#define BT_TEXT __attribute__((section(".text.btlentry_late")))
#endif
#define BT_CONST __attribute__((aligned(4), section(".rodata.btlentry_in_text")))
#define BT_BSS __attribute__((section(".bss.btlentry_late")))
#define BT_READS 3u // in flight, on different pages
#define BT_READ_TILES 16u             // a read's tiles at most
#define BT_READ_BYTES (160u * 1024u)  // and their compressed bytes, where the page's tile table is known
#ifdef CTRPORT_BTLENTRY_FAULT
#define BT_INSTALL_MS 0u // LAB ONLY: one tile a frame, so every read's installs cross frames
#else
#define BT_INSTALL_MS 8u // game-thread install time a frame: one tile, then another only if it fits within this
#endif
#define BT_FLOOR (3u * 1024u * 1024u + 256u * 1024u) // flowstream's linear floor and spare
#define BT_LIFT (8u * 1024u * 1024u)                 // ctr_tile_reader.c's READER_HEAP_RESERVE
#define BT_KEY_MASK 0x07FFFFFFu
#define BT_POOL_ENOUGH (4u * 1024u * 1024u) // the most the victim pool is counted to (Asgore evicts at most 2.7 MB)
#define BT_GONE 64u // evicted tiles remembered, to count their reloads
#define BT_CODE_PAGE 0xFFFFu        // a code read's pageId: no cache page has it
#define BT_CODE_SPANS 16u           // a code read's runs at most
#define BT_CODE_BYTES (64u * 1024u) // and its bytes (z_roomload.c's ROOMLOAD_SPAN_BYTES)
#define BT_CODE_GAP 256u            // bytes between groups one run reads over (ROOMLOAD_GAP_BYTES)
#define BT_CODE_HEADER 20u          // data_win.c's CodeCacheHeader: magic, version, base, size, checksum
#define BT_CODE_MAGIC 0x31434244u   // its CODE_CACHE_MAGIC
#define BT_ARENA_BLOCK (32u * 1024u) // its CODE_ARENA_BLOCK
#ifdef CTRPORT_BTLENTRY_DIAG
#define BTD(...) __VA_ARGS__ // LAB ONLY (btlentry heap proof): see the end of this file
// Out of line, in .text: never inlined into the late code, so the diag twins fit btlentry's slot too.
#define BTD_TEXT __attribute__((noinline))
static BTD_TEXT void btdMark(const char* what);
static BTD_TEXT void btdQueued(uint32_t k);
static BTD_TEXT uint32_t btdFault(uint32_t k, uint32_t kind);
static BTD_TEXT bool btdFile(uint32_t pageId);
static BTD_TEXT void btdMain(const CtrTileRead* read);
static BTD_TEXT bool btdHold(void);
#else
#define BTD(...)
#endif

void __real_CtrFlowstream_collect(CtrTextureCache* cache, bool drop);
void __wrap_CtrFlowstream_collect(CtrTextureCache* cache, bool drop);
bool __real_CtrFlowstream_readHeader(const uint8_t* data, size_t size, const CtrPackKey* key, uint32_t blobOffset, uint32_t blobSize,
                                     CtrPackView* out);
bool __wrap_CtrFlowstream_readHeader(const uint8_t* data, size_t size, const CtrPackKey* key, uint32_t blobOffset, uint32_t blobSize,
                                     CtrPackView* out);
struct mallinfo __real_CtrFlowstream_readMallinfo(void);
struct mallinfo __wrap_CtrFlowstream_readMallinfo(void);
void* __real_CtrFlowstream_readMalloc(size_t size);
void* __wrap_CtrFlowstream_readMalloc(size_t size);
FILE* __real_CtrFlowstream_gameFile(uint32_t pageId);
FILE* __wrap_CtrFlowstream_gameFile(uint32_t pageId);
FILE* __real_CtrFlowstream_openFile(uint32_t pageId, bool* busy);
FILE* __wrap_CtrFlowstream_openFile(uint32_t pageId, bool* busy);
const uint8_t* RoomPlan_utstallPlan(const CtrTextureCache* cache);
const uint8_t* CtrUtstall_activeScene(const CtrTextureCache* cache); // z_utstall.c: the plan scene this room visit loaded
int32_t RoomPlan_utstallGroup(Runner* runner);
bool CtrTextures_btlentryInstall(CtrTextureCache* cache, CtrPage* page, int32_t t); // ctr_textures.c's end
void CtrTextures_btlentryEvict(CtrTextureCache* cache, CtrPage* page, CtrTile* tile);
bool CtrMemory_allowRelief(bool allow);
bool __real_DataWin_moveBytecodeToFile(DataWin* dw, const char* cachePath);
bool __wrap_DataWin_moveBytecodeToFile(DataWin* dw, const char* cachePath);
void CtrOpenFiles_beginCacheOpen(void);
void CtrOpenFiles_endCacheOpen(void);
bool CtrOpenFiles_missing(int err);
extern u32 __ctru_heap_size;

static BT_BSS struct {
    const DataWin* objectsOf;     // the data.win the object indices are for
    int32_t objects[2];           // obj_battler, obj_battleblcon (or -1)
    CtrTileRead* volatile performing; // a read of ours, on the reader between its header and its allocation
    const DataWin* codeOf;        // the data.win whose bytecode moved to the file at codePath
    char codePath[96];            // the path is 43 characters; a longer one turns code reads off
    // From here on, a room visit's (cleared at a room change):
    const CtrTextureCache* cache; // the cache and its room visit
    uint32_t roomStart;
    const uint8_t* scene;         // the battle group's plan scene, once a battle starts
    int32_t group;
    uint32_t frames, installed, missing, untabled; // frames armed, tiles installed; at the first look: missing, on pages with no tile table
    uint32_t reads, installTicks, maxTicks, tileTicks; // reads queued; install time in all, in the costliest frame, of the costliest tile
    CtrTileRead* volatile read[BT_READS]; // the reads in flight, each set before it is queued; their pages
    uint32_t page[BT_READS];
    uint16_t next[BT_READS];              // the next tile of the read to install
    bool dropped[BT_READS];               // a tile of the read was not installed
    bool full;                            // a tile found no room even after evicting all it may: read only tiles with room
    uint32_t encounter;                   // the encounter's first frame
    uint32_t pool, poolTaken;             // the victims' bytes at the encounter (rev 2b); the bytes of no-room tiles read on it
    uint32_t evicted, evictedBytes, reloads, gone; // tiles evicted and their bytes; of the first BT_GONE: reloaded, remembered
    uint32_t goneKey[BT_GONE];            // page << 8 | tile
    CtrTileRead* volatile codeRead;       // the code read in flight: its groups in dstSize[], each one's run in dstFormat[]
    uint32_t codeGroups, codeAt;          // its groups; where in the bytecode the next one starts looking (UINT32_MAX: done)
    uint32_t codeReads, codePlaced, codeBytes, codeLeft; // code reads queued; groups placed and their bytes; not placed
} bt;

static const char btObject0[] BT_CONST = "obj_battler";
static const char btObject1[] BT_CONST = "obj_battleblcon";
static const char btLog[] BT_CONST =
    "Battle entry (btlentry): group %ld: %u of %u missing planned tiles read ahead in %u frames (%u untabled), "
    "%u reads; installs %.1f ms, %.1f ms most a frame; evicted %u tiles (%u KB), %u reloaded; "
    "code %u groups (%u KB) placed from %u reads, %u not placed\n";

static BT_TEXT bool btStarting(Runner* runner) {
    const DataWin* dw = runner->dataWin;
    if (bt.objectsOf != dw) {
        bt.objectsOf = dw;
        bt.objects[0] = bt.objects[1] = -1;
        for (uint32_t i = 0; dw->objt.count > i; i++) {
            const char* name = dw->objt.objects[i].name;
            if (name == nullptr) continue;
            if (strcmp(name, btObject0) == 0) bt.objects[0] = (int32_t) i;
            if (strcmp(name, btObject1) == 0) bt.objects[1] = (int32_t) i;
        }
    }
    for (uint32_t k = 0; 2 > k; k++) {
        int32_t o = bt.objects[k];
        if (0 <= o && runner->instancesByExactObject != nullptr && arrlen(runner->instancesByExactObject[o]) > 0) return true;
    }
    return false;
}

static BT_TEXT const uint8_t* btScene(const uint8_t* plan, int32_t group) {
    RoomPlanHeader h;
    memcpy(&h, plan, sizeof(h));
    size_t at = sizeof(h);
    for (uint32_t s = 0; h.sceneCount > s; s++) {
        RoomPlanScene scene;
        memcpy(&scene, plan + at, sizeof(scene));
        if (scene.sub != ROOMPLAN_NO_SUB && (int32_t) scene.sub == group) return plan + at;
        at += RoomPlan_sceneSize(&scene);
    }
    return nullptr;
}

// Texture memory for the tile, and linear memory above flowstream's floor and spare after it, with nothing evicted.
// A tile's texture bytes (what btRoomFor makes room for and btReserve checks the texture against).
static __attribute__((noinline)) BT_TEXT uint32_t btTileBytes(const CtrPage* page, const CtrTile* tile) {
    return (uint32_t) page->tileW * (uint32_t) page->tileH * CtrPack_texelBytes((CtrTileFormat) tile->format);
}

static BT_TEXT bool btRoomFor(const CtrTextureCache* cache, const CtrPage* page, const CtrTile* tile) {
    uint32_t bytes = btTileBytes(page, tile);
    uint32_t linear = linearSpaceFree();
    return cache->residentBytes + bytes <= cache->budgetBytes && linear >= BT_FLOOR && linear - BT_FLOOR >= bytes;
}

// Whether the tile (page << 8 | tile) is in the plan scene's tiles.
static BT_TEXT bool btPlanned(const uint8_t* scene, uint32_t key) {
    RoomPlanScene s;
    memcpy(&s, scene, sizeof(s));
    for (uint32_t i = 0; s.tileCount > i; i++) {
        uint32_t entry;
        memcpy(&entry, scene + sizeof(s) + (size_t) i * 4u, 4);
        if ((entry & BT_KEY_MASK) == key) return true;
    }
    return false;
}

// Whether the tile may be needed by the room the encounter starts in (rev 2): wanted by it, in its plan scene, or among
// the tiles its last visits drew on entry.
static BT_TEXT bool btRoomUses(const CtrTextureCache* cache, const uint8_t* room, const CtrTile* tile, uint32_t key) {
    if (tile->wanted || btPlanned(room, key)) return true;
    int32_t r = cache->runner->currentRoomIndex;
    if (0 > r || (uint32_t) r >= cache->roomCount) return true;
    const uint32_t* drew = cache->roomTiles[r];
    for (ptrdiff_t i = 0; arrlen(drew) > i; i++) {
        if ((drew[i] & BT_KEY_MASK) == key) return true;
    }
    return false;
}

// Room for the tile (btRoomFor), evicting for it, oldest first (the first in page order of the oldest frame, as
// evictUsedBefore), tiles last drawn before the encounter's first frame and not in the last CTR_THRASH_FRAMES frames
// (so evictTile never marks the room thrashing, and no queued GPU command still uses one), never one of the battle's
// planned set, and (rev 2) never one the room the encounter starts in may use (btRoomUses). False if there is still no
// room.
static BT_TEXT const uint8_t* btRoomProof(const CtrTextureCache* cache) {
    const uint8_t* room = CtrUtstall_activeScene(cache);
    if (room == nullptr) return nullptr;
    RoomPlanScene s;
    memcpy(&s, room, sizeof(s));
    return s.tileCount == 0 || s.tileCount >= ROOMPLAN_TILES_MAX ? nullptr : room;
}

// The tiles btMakeRoom may evict: last drawn before the encounter, outside the battle's planned set and the room's
// (btRoomUses). With pick, also idle longer than CTR_THRASH_FRAMES: the oldest (the first in page order of the oldest
// frame), its key in *out. Without, their bytes in *out, counted up to BT_POOL_ENOUGH (rev 2b's pool).
static BT_TEXT CtrTile* btVictims(CtrTextureCache* cache, const uint8_t* room, bool pick, uint32_t* out) {
    CtrTile* best = nullptr;
    uint32_t sum = 0;
    for (uint32_t p = 0; cache->pageCount > p; p++) {
        CtrPage* each = &cache->pages[p];
        if (each->residentTiles == 0) continue;
        for (int32_t i = 0; each->tilesX * each->tilesY > i; i++) {
            CtrTile* other = &each->tiles[i];
            uint32_t key = p << 8 | (uint32_t) i;
            if (!other->valid || other->lastUsedFrame >= bt.encounter ||
                (pick && (other->lastUsedFrame + CTR_THRASH_FRAMES >= cache->frame ||
                          (best != nullptr && other->lastUsedFrame >= best->lastUsedFrame))) ||
                btPlanned(bt.scene, key) || btRoomUses(cache, room, other, key))
                continue;
            if (pick) {
                best = other;
                *out = key;
            } else if ((sum += other->tex.size) >= BT_POOL_ENOUGH) {
                break;
            }
        }
        if (!pick && sum >= BT_POOL_ENOUGH) break;
    }
    if (!pick) *out = sum;
    return best;
}

static BT_TEXT bool btMakeRoom(CtrTextureCache* cache, const CtrPage* page, const CtrTile* tile) {
    const uint8_t* room = btRoomProof(cache);
    while (!btRoomFor(cache, page, tile)) {
        if (room == nullptr) return false;
        uint32_t from = 0;
        CtrTile* best = btVictims(cache, room, true, &from);
        if (best == nullptr) return false;
        if (BT_GONE > bt.gone) bt.goneKey[bt.gone++] = from;
        bt.evicted++;
        bt.evictedBytes += best->tex.size;
        CtrTextures_btlentryEvict(cache, &cache->pages[from >> 8], best);
    }
    return true;
}

// Rev 2b: the bytes btMakeRoom may evict for the battle (btVictims without the age), counted at its first armed frame.
// Tiles drawn again later only leave it, so it is never short of what btMakeRoom finds.
static BT_TEXT uint32_t btPool(CtrTextureCache* cache) {
    const uint8_t* room = btRoomProof(cache);
    uint32_t pool = 0;
    if (room != nullptr) btVictims(cache, room, false, &pool);
    return pool;
}

// Room for the tile, or (rev 2b) a pool that still covers it after the no-room tiles already read on it.
static BT_TEXT bool btFits(const CtrTextureCache* cache, const CtrPage* page, const CtrTile* tile) {
    if (btRoomFor(cache, page, tile)) return true;
    uint32_t bytes = btTileBytes(page, tile);
    return bt.pool > 0 && !bt.full && bytes > 0 && bt.pool >= bt.poolTaken && bt.pool - bt.poolTaken >= bytes;
}

// Counts the remembered evicted tiles resident again that were last drawn before frame before (loaded again), and
// forgets them.
static BT_TEXT void btReloads(const CtrTextureCache* cache, uint32_t before) {
    for (uint32_t i = 0; bt.gone > i;) {
        uint32_t key = bt.goneKey[i];
        const CtrTile* tile = &cache->pages[key >> 8].tiles[key & 0xFFu];
        if (tile->valid && tile->lastUsedFrame < before) {
            bt.reloads++;
            bt.goneKey[i] = bt.goneKey[--bt.gone];
        } else {
            i++;
        }
    }
}

// The tile's texture, allocated without evicting anything (initTile, as allocateTile does with mayEvict false) and
// counted as reserveTile counts a read's: installTile's allocateTile then takes it as allocated, and releaseRead's
// unreserveTile frees it if the install fails first. False (nothing allocated) if linear memory can't give it.
static BT_TEXT bool btReserve(CtrTextureCache* cache, CtrPage* page, CtrTile* tile) {
    uint32_t bytes = btTileBytes(page, tile);
    if (tile->reserved || !C3D_TexInit(&tile->tex, (u16) page->tileW, (u16) page->tileH, CtrPack_gpuFormat((CtrTileFormat) tile->format)))
        return false;
    if (tile->tex.size != bytes) {
        C3D_TexDelete(&tile->tex);
        return false;
    }
    C3D_TexSetFilter(&tile->tex, GPU_NEAREST, GPU_NEAREST);
    C3D_TexSetWrap(&tile->tex, GPU_CLAMP_TO_EDGE, GPU_CLAMP_TO_EDGE);
    tile->reserved = true;
    page->bytes += bytes;
    cache->residentBytes += bytes;
    return true;
}

// Whether the heap keeps the promotion reserve free after bytes more.
static BT_TEXT bool btHeapFor(uint32_t bytes) {
    struct mallinfo mi = mallinfo();
    return __ctru_heap_size >= (uint32_t) mi.uordblks + CtrTileReader_heapReserve() + bytes;
}

// A read record, allocated with heap relief off.
static BT_TEXT CtrTileRead* btNewRead(void) {
    bool allowed = CtrMemory_allowRelief(false);
    CtrTileRead* read = CtrTileReader_newRead();
    CtrMemory_allowRelief(allowed);
    return read;
}

// ---- Round 5: the battle's code.

// The bytecode file's path, for the reader's own handle on it (the game thread's, dw->bytecodeFile, is its own).
BT_TEXT bool __wrap_DataWin_moveBytecodeToFile(DataWin* dw, const char* cachePath) {
    bool moved = __real_DataWin_moveBytecodeToFile(dw, cachePath);
    bt.codeOf = nullptr;
    if (moved && sizeof(bt.codePath) > strlen(cachePath)) {
        strcpy(bt.codePath, cachePath);
        bt.codeOf = dw;
    }
    return moved;
}

// As ctr_texture_pack.c's CtrPack_openFile, for the bytecode file: on the reader only. The mode is late rodata (a
// literal would go to the merged strings of .rodata and move what follows).
static const char btRead[] BT_CONST = "rb";
static BT_TEXT FILE* btOpenCode(bool* busy) {
    CtrOpenFiles_beginCacheOpen();
    errno = 0;
    FILE* f = fopen(bt.codePath, btRead);
    if (busy != nullptr) *busy = f == nullptr && !CtrOpenFiles_missing(errno);
    CtrOpenFiles_endCacheOpen();
    if (f != nullptr) setvbuf(f, nullptr, _IONBF, 0);
    return f;
}

// The blob starting at offset (z_roomload.c's rlBlobOf), and a group's end (by its first blob, rlGroupEnd).
static BT_TEXT uint32_t btBlobOf(const DataWin* dw, uint32_t offset) {
    uint32_t low = 0, high = dw->codeBlobCount;
    while (high > low) {
        uint32_t mid = low + (high - low) / 2u;
        if (offset > dw->codeBlobs[mid].absoluteOffset) low = mid + 1u;
        else high = mid;
    }
    return low;
}

static BT_TEXT uint32_t btGroupEnd(const DataWin* dw, uint32_t first) {
    uint32_t end = 0;
    for (uint32_t b = first; dw->codeBlobCount > b && dw->codeBlobs[b].group == first; b++) {
        uint32_t blobEnd = dw->codeBlobs[b].absoluteOffset + dw->codeBlobs[b].length;
        if (blobEnd > end) end = blobEnd;
    }
    return end;
}

// The first group in file order, starting at from or later, of the plan scene's code entries not in memory (the
// first blob's index), or UINT32_MAX.
static BT_TEXT uint32_t btNextGroup(const DataWin* dw, uint32_t from) {
    RoomPlanScene s;
    memcpy(&s, bt.scene, sizeof(s));
    const uint8_t* codes = bt.scene + sizeof(s) + (size_t) s.tileCount * 4u + (((size_t) s.tileCount + 3u) & ~(size_t) 3u);
    uint32_t best = UINT32_MAX, bestAt = UINT32_MAX;
    for (uint32_t i = 0; s.codeCount > i; i++) {
        uint16_t index;
        memcpy(&index, codes + (size_t) i * 2u, 2);
        if (index >= dw->code.count) continue;
        const CodeEntry* code = &dw->code.entries[index];
        if (!code->present || code->bytecode != nullptr) continue;
        uint32_t b = btBlobOf(dw, code->bytecodeAbsoluteOffset);
        if (b >= dw->codeBlobCount || dw->codeBlobs[b].absoluteOffset != code->bytecodeAbsoluteOffset || dw->codeBlobs[b].bytes != nullptr)
            continue;
        uint32_t g = dw->codeBlobs[b].group;
        uint32_t at = dw->codeBlobs[g].absoluteOffset;
        if (at >= from && bestAt > at) best = g, bestAt = at;
    }
    return best;
}

// Queues the next code read, if none is in flight and the heap leaves the promotion reserve after its most bytes.
static BT_TEXT void btQueueCode(CtrTextureCache* cache) {
    DataWin* dw = cache->dataWin;
    if (bt.codeRead != nullptr || bt.codeAt == UINT32_MAX || bt.codeOf != dw || dw->bytecodeFile == nullptr || dw->codeBlobs == nullptr)
        return;
    uint32_t g = btNextGroup(dw, bt.codeAt);
    if (g == UINT32_MAX) {
        bt.codeAt = UINT32_MAX;
        return;
    }
    CtrTileRead* read = btHeapFor(BT_CODE_BYTES) ? btNewRead() : nullptr;
    if (read == nullptr) return;
    // The runs, as a page of one column: run r is tile r, at its offset in the file.
    uint32_t base = (uint32_t) dw->bytecodeBufferBase;
    uint32_t groups = 0, total = 0, row = 0, runStart = 0, runEnd = 0;
    while (g != UINT32_MAX && CTR_PAGE_MAX_TILES > groups) {
        uint32_t start = dw->codeBlobs[g].absoluteOffset, end = btGroupEnd(dw, g);
        bool join = groups > 0 && runEnd + BT_CODE_GAP >= start;
        uint32_t add = end - (join ? runEnd : start);
        if (total + add > BT_CODE_BYTES || (!join && groups > 0 && row + 1u == BT_CODE_SPANS)) break;
        total += add;
        if (!join && groups > 0) row++;
        if (!join) runStart = start;
        runEnd = end;
        read->want[row] = true;
        read->view.tileOffset[row] = BT_CODE_HEADER + runStart - base;
        read->view.tileSize[row] = runEnd - runStart;
        read->dstSize[groups] = g; // dst stays nullptr: nothing is decoded
        read->dstFormat[groups++] = (uint8_t) row;
        g = btNextGroup(dw, end);
    }
    bt.codeAt = groups > 0 ? runEnd : dw->codeBlobs[g].absoluteOffset + 1u; // a group alone over BT_CODE_BYTES is left
    if (groups == 0) {
        CtrTileReader_release(cache->reader, read);
        return;
    }
    read->view.layout.tilesX = 1;
    read->view.layout.tilesY = (int32_t) row + 1;
    read->view.totalSize = BT_CODE_HEADER + dw->codeStats.totalBytes;
    read->pageId = BT_CODE_PAGE;
    bt.codeGroups = groups;
    bt.codeRead = read;
    bt.codeReads++;
    BTD(btdQueued(BT_READS));
    CtrTileReader_queue(cache->reader, read);
}

// Code memory for a group of size bytes, as data_win.c's allocCodeArena gives it, but only with the promotion reserve
// still free after it and room in the block list (no growth), and with heap relief off; nullptr otherwise.
static BT_TEXT uint8_t* btArena(DataWin* dw, uint32_t size) {
    size = (size + 3u) & ~3u;
    bool own = size > BT_ARENA_BLOCK / 4u;
    uint32_t take = own ? size : size > dw->codeArenaLeft ? BT_ARENA_BLOCK : 0;
    if (take > 0) {
        stbds_array_header* list = dw->codeArenaBlocks != nullptr ? stbds_header(dw->codeArenaBlocks) : nullptr;
        uint8_t* block = list != nullptr && list->capacity > list->length && btHeapFor(take) ? malloc(take) : nullptr;
        if (block == nullptr) return nullptr;
        dw->codeArenaBlocks[list->length++] = block; // arrput, with room for it
        dw->codeStats.residentBytes += take;
        if (own) return block;
        dw->codeArena = block;
        dw->codeArenaLeft = BT_ARENA_BLOCK;
    }
    uint8_t* at = dw->codeArena;
    dw->codeArena += size;
    dw->codeArenaLeft -= size;
    return at;
}

// The code read, once finished: each of its groups still not in memory gets its memory and bytes (rlPlace and
// rlReadCode's copy, a group at a time), then the read is released.
static BT_TEXT void btPlaceCode(CtrTextureCache* cache) {
    CtrTileRead* read = bt.codeRead;
    if (read == nullptr || !CtrTileReader_finished(cache->reader, read) BTD(|| btdHold())) return;
    DataWin* dw = cache->dataWin;
    DataWinCodeBlob* blobs = dw->codeBlobs;
    uint32_t base = (uint32_t) dw->bytecodeBufferBase;
    uint32_t left = bt.codeLeft;
    bool allowed = CtrMemory_allowRelief(false);
    for (uint32_t i = 0; bt.codeGroups > i; i++) {
        uint32_t g = read->dstSize[i], row = read->dstFormat[i];
        if (blobs[g].bytes != nullptr) continue; // run meanwhile, so read by the lazy path
        uint32_t start = blobs[g].absoluteOffset, end = btGroupEnd(dw, g);
        uint8_t* at = read->headerOk && read->data != nullptr && read->tileAt[row] != CTR_READ_NOT_READ BTD(&& !btdFault(BT_READS, 3))
                          ? btArena(dw, end - start)
                          : nullptr;
        if (at == nullptr) {
            bt.codeLeft++;
            continue;
        }
        memcpy(at, read->data + read->tileAt[row] + (BT_CODE_HEADER + start - base - read->view.tileOffset[row]), end - start);
        for (uint32_t b = g; dw->codeBlobCount > b && blobs[b].group == g; b++) blobs[b].bytes = at + (blobs[b].absoluteOffset - start);
        bt.codePlaced++;
        bt.codeBytes += end - start;
    }
    CtrMemory_allowRelief(allowed);
    BTD(if (read->data == nullptr || bt.codeLeft != left) btdFault(BT_READS, read->data == nullptr ? 4 : 5);)
    (void) left;
    CtrTileReader_release(cache->reader, read);
    bt.codeRead = nullptr;
}

// The game thread's file for a read of ours that its wait took from the queue (performNextOnGameFile's gameFile, the
// original wait's openFile): none, so it reads nothing and is dropped, as flowstream's refill (fsStolen). One read a
// page, so the page's read is ours.
static BT_TEXT bool btStolen(uint32_t pageId) {
    if (threadGetCurrent() != nullptr || bt.cache == nullptr || pageId >= bt.cache->pageCount) return false;
    for (uint32_t k = 0; BT_READS > k; k++) {
        if (bt.read[k] != nullptr && bt.page[k] == pageId && bt.cache->pages[pageId].read == bt.read[k]) return BTD(btdFault(k, 6),) true;
    }
    return false;
}

BT_TEXT FILE* __wrap_CtrFlowstream_gameFile(uint32_t pageId) {
    if (pageId == BT_CODE_PAGE) return BTD(btdFault(BT_READS, 6),) nullptr;
    return btStolen(pageId) BTD(|| btdFile(pageId)) ? nullptr : __real_CtrFlowstream_gameFile(pageId);
}

// A code read's file is the bytecode file, opened by the reader only (none on the game thread, as btStolen).
BT_TEXT FILE* __wrap_CtrFlowstream_openFile(uint32_t pageId, bool* busy) {
    if (pageId == BT_CODE_PAGE) return threadGetCurrent() == nullptr ? (BTD(btdFault(BT_READS, 6),) nullptr) : BTD(btdFile(pageId) ? nullptr :) btOpenCode(busy);
    return btStolen(pageId) BTD(|| btdFile(pageId)) ? nullptr : __real_CtrFlowstream_openFile(pageId, busy);
}

// A planned tile the reader may read now (*outPage set if it is missing, or its page's grid isn't known yet): on a
// cache page with a cache file not known to be missing, that no read or copy holds, and, if the page's tile table is
// known, with room for it (else the read learns the table first, from its header). 1: yes; 0: not now (or not missing).
static BT_TEXT bool btReadable(CtrTextureCache* cache, uint32_t entry, CtrPage** outPage, uint32_t* outTile) {
    uint32_t p = (entry & BT_KEY_MASK) >> 8;
    uint32_t t = entry & 0xFFu;
    if (p >= cache->pageCount) return 0;
    CtrPage* page = &cache->pages[p];
    if (page->failed || page->cacheFile == CTR_CACHE_FILE_MISSING || cache->dataWin->txtr.textures[p].externalPath != nullptr) return 0;
    CtrTile* tile = nullptr;
    if (page->layoutKnown) {
        if (t >= (uint32_t) (page->tilesX * page->tilesY)) return 0;
        tile = &page->tiles[t];
        if (tile->valid || (page->formatsKnown && tile->format == CTR_TILE_EMPTY)) return 0;
    }
    *outPage = page;
    *outTile = t;
    return cache->frame >= page->retryFrame && page->packed == nullptr && page->read == nullptr &&
           (!page->packInfo || btFits(cache, page, tile));
}

BT_TEXT void __wrap_CtrFlowstream_collect(CtrTextureCache* cache, bool drop) {
    __real_CtrFlowstream_collect(cache, drop);
    Runner* runner = cache != nullptr ? cache->runner : nullptr;
    if (runner == nullptr || cache->reader == nullptr) return;
    if (bt.cache != cache || bt.roomStart != cache->roomStartFrame) {
        // A room change: the cache released our reads with the room's. Evicted tiles resident again and last drawn
        // before the battle room's first frame were loaded again in the encounter room.
        if (bt.scene != nullptr && bt.cache == cache) btReloads(cache, cache->roomStartFrame);
        if (bt.codeRead != nullptr && bt.cache == cache) {
            BTD(btdFault(BT_READS, 9);)
            CtrTileReader_release(cache->reader, bt.codeRead); // the room load reads the rest
        }
        if (bt.scene != nullptr)
            logInfo(btLog, (long) bt.group, (unsigned) bt.installed, (unsigned) bt.missing, (unsigned) bt.frames, (unsigned) bt.untabled,
                    (unsigned) bt.reads, (double) bt.installTicks / (double) (SYSCLOCK_ARM11 / 1000u),
                    (double) bt.maxTicks / (double) (SYSCLOCK_ARM11 / 1000u), (unsigned) bt.evicted, (unsigned) (bt.evictedBytes / 1024u),
                    (unsigned) bt.reloads, (unsigned) bt.codePlaced, (unsigned) ((bt.codeBytes + 1023u) / 1024u), (unsigned) bt.codeReads,
                    (unsigned) bt.codeLeft);
        BTD(btdMark(bt.scene != nullptr ? "the encounter animation and the battle room load" : nullptr));
        memset((void*) &bt.cache, 0, sizeof(bt) - offsetof(__typeof__(bt), cache));
        bt.cache = cache;
        bt.roomStart = cache->roomStartFrame;
    }
    BTD(btdMark(cache->frame - bt.roomStart == 300u ? "the room's first 300 frames" : nullptr));
    btReloads(cache, UINT32_MAX);
    // The reads in: their tiles installed while there is room and time, else dropped; a read is released once all its
    // tiles are, and one cut short by the time keeps the page until the next frame.
    uint64_t start = svcGetSystemTick();
    uint64_t budget = (uint64_t) BT_INSTALL_MS * (SYSCLOCK_ARM11 / 1000u);
    uint32_t done = 0;
    btPlaceCode(cache);
    for (uint32_t k = 0; BT_READS > k; k++) {
        CtrTileRead* read = bt.read[k];
        if (read == nullptr) continue;
        CtrPage* page = &cache->pages[bt.page[k]];
        if (page->read != read) { // the cache took it (drawn, or released)
            bt.read[k] = nullptr;
            continue;
        }
        if (!CtrTileReader_finished(cache->reader, read)) continue;
        const CtrPageLayout* layout = &read->view.layout;
        bool allowed = CtrMemory_allowRelief(false);
        if (read->headerOk && !page->layoutKnown && (page->tiles = calloc((size_t) (layout->tilesX * layout->tilesY), sizeof(CtrTile))) != nullptr) {
            // A page not used yet this session: its grid from the read's header (ctr_textures.c's setLayout).
            page->width = layout->width;
            page->height = layout->height;
            page->tileW = layout->tileW;
            page->tileH = layout->tileH;
            page->tilesX = layout->tilesX;
            page->tilesY = layout->tilesY;
            page->layoutKnown = true;
        }
        CtrMemory_allowRelief(allowed);
        if (read->headerOk && page->layoutKnown && !page->packInfo && page->width == layout->width && page->height == layout->height &&
            page->tileW == layout->tileW && page->tileH == layout->tileH && page->tilesX == layout->tilesX && page->tilesY == layout->tilesY) {
            // Its tile table, from the same header (ctr_textures.c's applyView, as takeView does on a page's first load).
            for (int32_t i = 0; page->tilesX * page->tilesY > i; i++) {
                CtrTile* each = &page->tiles[i];
                each->format = layout->formats[i];
                each->offset = read->view.tileOffset[i];
                each->size = read->view.tileSize[i];
                each->checksum = read->view.tileChecksum[i];
            }
            page->formatsKnown = true;
            page->packInfo = true;
            page->cacheFile = CTR_CACHE_FILE_VALID;
        }
        bool more = false;
        for (uint32_t t = bt.next[k]; CTR_PAGE_MAX_TILES > t; t++) {
            if (!read->want[t]) continue;
            if (done > 0 && svcGetSystemTick() - start + bt.tileTicks > budget) {
                bt.next[k] = (uint16_t) t;
                more = true;
                break;
            }
            CtrTile* tile = page->packInfo && t < (uint32_t) (page->tilesX * page->tilesY) ? &page->tiles[t] : nullptr;
            if (tile != nullptr && tile->valid) continue;
            bool usable = read->headerOk && tile != nullptr && read->data != nullptr && read->tileAt[t] != CTR_READ_NOT_READ &&
                          tile->offset == read->view.tileOffset[t] && tile->size == read->view.tileSize[t];
            if (usable && !btRoomFor(cache, page, tile) && (bt.pool == 0 || !btMakeRoom(cache, page, tile))) {
                if (bt.pool > 0 && cache->frame <= bt.encounter + CTR_THRASH_FRAMES + 1u) { // the tiles drawn just before may be evicted soon
                    bt.next[k] = (uint16_t) t;
                    more = true;
                    break;
                }
                bt.full = true;
            } else if (usable && BTD(!btdFault(k, 3) &&) btReserve(cache, page, tile)) {
                done++;
                uint64_t before = svcGetSystemTick();
                bool ok = CtrTextures_btlentryInstall(cache, page, (int32_t) t);
                uint32_t took = (uint32_t) (svcGetSystemTick() - before);
                if (took > bt.tileTicks) bt.tileTicks = took;
                if (ok) {
                    bt.installed++;
                    continue;
                }
            }
            bt.dropped[k] = true;
        }
        if (more) break;
        BTD(if (read->data == nullptr || bt.dropped[k]) btdFault(k, read->data == nullptr ? 4 : 5);)
        CtrTextures_btlentryInstall(cache, page, -1); // released: frees a reserved texture whose install failed
        bt.read[k] = nullptr;
    }
    if (done > 0) {
        uint32_t ticks = (uint32_t) (svcGetSystemTick() - start);
        bt.installTicks += ticks;
        if (ticks > bt.maxTicks) bt.maxTicks = ticks;
    }
    const uint8_t* plan = RoomPlan_utstallPlan(cache);
    if (plan == nullptr || !btStarting(runner)) return;
    int32_t group = RoomPlan_utstallGroup(runner);
    const uint8_t* scene = 0 <= group ? btScene(plan, group) : nullptr;
    if (scene == nullptr) return;
    RoomPlanScene s;
    memcpy(&s, scene, sizeof(s));
    if (s.room == (uint32_t) runner->currentRoomIndex) return;
    bool first = bt.scene != scene;
    BTD(btdMark(first ? "the overworld visit before the encounter" : nullptr));
    if (first) bt.encounter = cache->frame - 1u; // obj_battler came in the last frame's step, before its draw
    bt.scene = scene;
    bt.group = group;
    if (first) bt.pool = btPool(cache);
    bt.frames++;
    btQueueCode(cache);
    uint32_t k = 0;
    for (uint32_t i = 0; s.tileCount > i; i++) {
        while (BT_READS > k && bt.read[k] != nullptr) k++;
        if (BT_READS == k && !first) break;
        uint32_t entry;
        memcpy(&entry, scene + sizeof(s) + (size_t) i * 4u, 4);
        CtrPage* page = nullptr;
        uint32_t t = 0;
        bool readable = btReadable(cache, entry, &page, &t);
        if (first && page != nullptr) bt.missing++, bt.untabled += !page->packInfo;
        if (!readable || BT_READS == k || cache->fillPending) continue;
        // The page's planned tiles still missing, in plan order from this one (the page's first), up to a read's limits.
        uint32_t p = (uint32_t) (page - cache->pages);
        uint8_t want[BT_READ_TILES];
        uint32_t tiles = 0, bytes = 0;
        for (uint32_t j = i; s.tileCount > j && BT_READ_TILES > tiles; j++) {
            uint32_t other;
            memcpy(&other, scene + sizeof(s) + (size_t) j * 4u, 4);
            CtrPage* same = nullptr;
            uint32_t u = 0;
            if (((other & BT_KEY_MASK) >> 8) != p || memchr(want, (int) (other & 0xFFu), tiles) != nullptr || !btReadable(cache, other, &same, &u))
                continue;
            uint32_t size = page->packInfo ? page->tiles[u].size : 0;
            if (tiles > 0 && bytes + size > BT_READ_BYTES) break;
            want[tiles++] = (uint8_t) u;
            bytes += size;
            if (page->packInfo && !btRoomFor(cache, page, &page->tiles[u]))
                bt.poolTaken += btTileBytes(page, &page->tiles[u]);
        }
        CtrTileRead* read = btHeapFor(bytes) ? btNewRead() : nullptr;
        if (read == nullptr) break;
        for (uint32_t j = 0; tiles > j; j++) read->want[want[j]] = true;
        const Texture* txtr = &cache->dataWin->txtr.textures[p];
        read->pageId = p;
        read->blobOffset = txtr->blobOffset;
        read->blobSize = txtr->blobSize;
        page->read = read;
        bt.page[k] = p;
        bt.next[k] = 0;
        bt.dropped[k] = false;
        bt.read[k] = read; // before the queue's lock hands it to the reader
        bt.reads++;
        BTD(btdQueued(k));
        CtrTileReader_queue(cache->reader, read);
    }
}

// The reader's hooks (ctr_tile_reader.c's CTR_READ_*, through flowstream's): a read of ours is admitted with the
// promotion reserve plus its bytes, and its buffer allocated with heap relief off, as flowstream's refill read is.
BT_TEXT bool __wrap_CtrFlowstream_readHeader(const uint8_t* data, size_t size, const CtrPackKey* key, uint32_t blobOffset, uint32_t blobSize,
                                             CtrPackView* out) {
    CtrTileRead* read = (CtrTileRead*) (void*) ((uint8_t*) out - offsetof(CtrTileRead, view));
    if (threadGetCurrent() != nullptr) {
        bt.performing = nullptr;
        for (uint32_t k = 0; BT_READS > k; k++) {
            if (read == bt.read[k] && read->pageId == bt.page[k]) bt.performing = read BTD(, btdFault(k, 0));
        }
        if (read == bt.codeRead && read->pageId == BT_CODE_PAGE) {
            // The bytecode file's header: its magic (perform checks the file's size); the view was set up when it was queued.
            bt.performing = read BTD(, btdFault(BT_READS, 0));
            uint32_t magic;
            memcpy(&magic, data, 4);
            return size >= 4u && magic == BT_CODE_MAGIC;
        }
    } BTD(else btdMain(read);)
    return __real_CtrFlowstream_readHeader(data, size, key, blobOffset, blobSize, out);
}

BT_TEXT struct mallinfo __wrap_CtrFlowstream_readMallinfo(void) {
    struct mallinfo mi = __real_CtrFlowstream_readMallinfo();
    if (bt.performing != nullptr && threadGetCurrent() != nullptr BTD(&& !btdFault(0, 1))) {
        uint32_t lift = BT_LIFT - CtrTileReader_heapReserve();
        mi.uordblks = (uint32_t) mi.uordblks > lift ? (int) ((uint32_t) mi.uordblks - lift) : 0;
    }
    return mi;
}

BT_TEXT void* __wrap_CtrFlowstream_readMalloc(size_t size) {
    if (bt.performing == nullptr || threadGetCurrent() == nullptr) return __real_CtrFlowstream_readMalloc(size);
    bt.performing = nullptr;
    bool allowed = CtrMemory_allowRelief(false);
    void* data = BTD(btdFault(0, 2) ? nullptr :) malloc(size);
    CtrMemory_allowRelief(allowed);
    return data;
}

#ifdef CTRPORT_BTLENTRY_DIAG
// LAB ONLY, never release (CTRPORT_BTLENTRY_DIAG; review decision 11-02 on the reserve): the smallest heap free
// (__ctru_heap_size less mallinfo's bytes in use, as ctr_tile_reader.c's heapFree) after every heap allocation of any
// thread (newlib's _malloc_r, _calloc_r, _realloc_r and _memalign_r are wrapped, so stdio's buffers count too), logged
// per window: the overworld visit before an encounter, the encounter animation with the battle room's load, and the
// battle room's first 300 frames. With CTRPORT_BTLENTRY_FAULT, our reads cycle through five outcomes (normal, refused
// at the reader's reserve, payload allocation failed, texture allocation failed at install, no file as a read the
// game thread took gets) to prove each falls back to the room load's own read with the same results. Our reads whose
// header the game thread read (a file of ours opened on it: c26rev r101 F1's gate) are counted; they must stay 0.
static struct {
    uint32_t minFree, queued, outcome[10]; // [9]: code reads released by the room change
    uint8_t kind[BT_READS + 1u]; // each read in flight's fault (the code read's last) (0 none, 1 refused, 2 allocation fails, 3 texture fails, 7 no file)
    uint8_t performingK;
} btd = {.minFree = UINT32_MAX};

static void btdSample(void) {
    struct mallinfo mi = mallinfo();
    uint32_t used = (uint32_t) mi.uordblks;
    uint32_t free = __ctru_heap_size > used ? __ctru_heap_size - used : 0;
    uint32_t seen = __atomic_load_n(&btd.minFree, __ATOMIC_RELAXED);
    while (seen > free && !__atomic_compare_exchange_n(&btd.minFree, &seen, free, false, __ATOMIC_RELAXED, __ATOMIC_RELAXED)) {}
}

void* __real__malloc_r(struct _reent* r, size_t n);
void* __real__calloc_r(struct _reent* r, size_t c, size_t n);
void* __real__realloc_r(struct _reent* r, void* p, size_t n);
void* __real__memalign_r(struct _reent* r, size_t a, size_t n);
void* __wrap__malloc_r(struct _reent* r, size_t n);
void* __wrap__calloc_r(struct _reent* r, size_t c, size_t n);
void* __wrap__realloc_r(struct _reent* r, void* p, size_t n);
void* __wrap__memalign_r(struct _reent* r, size_t a, size_t n);
void* __wrap__malloc_r(struct _reent* r, size_t n) {
    void* q = __real__malloc_r(r, n);
    if (q != nullptr) btdSample();
    return q;
}
void* __wrap__calloc_r(struct _reent* r, size_t c, size_t n) {
    void* q = __real__calloc_r(r, c, n);
    if (q != nullptr) btdSample();
    return q;
}
void* __wrap__realloc_r(struct _reent* r, void* p, size_t n) {
    void* q = __real__realloc_r(r, p, n);
    if (q != nullptr) btdSample();
    return q;
}
void* __wrap__memalign_r(struct _reent* r, size_t a, size_t n) {
    void* q = __real__memalign_r(r, a, n);
    if (q != nullptr) btdSample();
    return q;
}

static void btdMark(const char* what) {
    if (what == nullptr) return;
    uint32_t low = __atomic_exchange_n(&btd.minFree, UINT32_MAX, __ATOMIC_RELAXED);
    logInfo("Battle entry diag: %s: smallest heap free %lu KB (floor 4096 KB), %s; reads queued %lu (since boot): installed, "
            "taken or released %lu, finished empty %lu, not installed %lu, game-thread files refused %lu, read on the game thread %lu; faults: refused %lu, allocation failed %lu, texture failed %lu, no file %lu; code reads released by a room change %lu\n", what,
            (unsigned long) (low / 1024), low >= 4096u * 1024u ? "above" : "BELOW", (unsigned long) btd.queued,
            (unsigned long) (btd.queued - btd.outcome[4] - btd.outcome[5]), (unsigned long) btd.outcome[4],
            (unsigned long) btd.outcome[5], (unsigned long) btd.outcome[6], (unsigned long) btd.outcome[8], (unsigned long) btd.outcome[1], (unsigned long) btd.outcome[2],
            (unsigned long) btd.outcome[3], (unsigned long) btd.outcome[7], (unsigned long) btd.outcome[9]);
}

static void btdQueued(uint32_t k) {
#ifdef CTRPORT_BTLENTRY_FAULT
    static const uint8_t cycle[5] = {0, 1, 2, 3, 7};
    btd.kind[k] = cycle[btd.queued % 5u];
#else
    btd.kind[k] = 0;
#endif
    btd.queued++;
}

// kind 0: the reader is performing read k (remember it); 1: may its reserve be lifted? (nonzero: no, refused);
// 2: may its allocation succeed? (nonzero: no); 3: may its texture be allocated? (nonzero: no, dropped);
// 4, 5, 6: a read finished empty / not installed / its file refused to the game thread (counted).
static uint32_t btdFault(uint32_t k, uint32_t kind) {
    if (kind == 0) {
        btd.performingK = (uint8_t) k;
        return 0;
    }
    if (kind >= 4) {
        btd.outcome[kind]++;
        return 0;
    }
    uint32_t at = kind == 3 ? k : btd.performingK;
    if (btd.kind[at] != kind) return 0;
    btd.outcome[kind]++;
    return 1;
}

// A file of ours the reader thread asks for, refused under CTRPORT_BTLENTRY_FAULT for the no-file reads (fault 7).
static bool btdFile(uint32_t pageId) {
    if (pageId == BT_CODE_PAGE && btd.kind[BT_READS] == 7) return btd.outcome[7]++, true;
    if (threadGetCurrent() == nullptr || bt.cache == nullptr || pageId >= bt.cache->pageCount) return false;
    for (uint32_t k = 0; BT_READS > k; k++) {
        if (bt.read[k] != nullptr && bt.page[k] == pageId && bt.cache->pages[pageId].read == bt.read[k] && btd.kind[k] == 7) {
            btd.outcome[7]++;
            return true;
        }
    }
    return false;
}

// A header the game thread read: one of ours must never be among them.
static void btdMain(const CtrTileRead* read) {
    for (uint32_t k = 0; BT_READS > k; k++) {
        if (read == bt.read[k]) btd.outcome[8]++;
    }
    if (read == bt.codeRead) btd.outcome[8]++;
}

// With CTRPORT_BTLENTRY_FAULT, a code read with no fault is never placed: the room change releases it, in whatever
// state it is (queued, being read or finished), and the room load reads its groups.
static bool btdHold(void) {
#ifdef CTRPORT_BTLENTRY_FAULT
    return btd.kind[BT_READS] == 0;
#else
    return false;
#endif
}
#endif
#endif
