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
// the texture budget and the linear floor leave room for it without evicting anything; else that tile is dropped. A
// read is released once its last tile is done. A page not loaded from yet this session takes its grid and tile table
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
// Textures only: no game state, script, timing the game sees or RNG changes; every tile is the same texels whenever it
// loads. Late code and statics only (late_reserve.ld, last).
#include <3ds.h>
#include <malloc.h>
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

#define BT_TEXT __attribute__((noinline, section(".text.btlentry_late")))
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
#ifdef CTRPORT_BTLENTRY_DIAG
#define BTD(...) __VA_ARGS__ // LAB ONLY (btlentry heap proof): see the end of this file
static void btdMark(const char* what);
static void btdQueued(uint32_t k);
static uint32_t btdFault(uint32_t k, uint32_t kind);
static bool btdFile(uint32_t pageId);
static void btdMain(const CtrTileRead* read);
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
int32_t RoomPlan_utstallGroup(Runner* runner);
bool CtrTextures_btlentryInstall(CtrTextureCache* cache, CtrPage* page, int32_t t); // ctr_textures.c's end
bool CtrMemory_allowRelief(bool allow);
extern u32 __ctru_heap_size;

static BT_BSS struct {
    const DataWin* objectsOf;     // the data.win the object indices are for
    int32_t objects[2];           // obj_battler, obj_battleblcon (or -1)
    CtrTileRead* volatile performing; // a read of ours, on the reader between its header and its allocation
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
} bt;

static const char btObject0[] BT_CONST = "obj_battler";
static const char btObject1[] BT_CONST = "obj_battleblcon";
static const char btLog[] BT_CONST =
    "Battle entry (btlentry): group %ld: %u of %u missing planned tiles read ahead in %u frames (%u on pages whose tile table was read here), "
    "%u reads; installs %.1f ms, %.1f ms in a frame at most\n";

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
static BT_TEXT bool btRoomFor(const CtrTextureCache* cache, const CtrPage* page, const CtrTile* tile) {
    uint32_t bytes = (uint32_t) page->tileW * (uint32_t) page->tileH * CtrPack_texelBytes((CtrTileFormat) tile->format);
    uint32_t linear = linearSpaceFree();
    return cache->residentBytes + bytes <= cache->budgetBytes && linear >= BT_FLOOR && linear - BT_FLOOR >= bytes;
}

// The tile's texture, allocated without evicting anything (initTile, as allocateTile does with mayEvict false) and
// counted as reserveTile counts a read's: installTile's allocateTile then takes it as allocated, and releaseRead's
// unreserveTile frees it if the install fails first. False (nothing allocated) if linear memory can't give it.
static BT_TEXT bool btReserve(CtrTextureCache* cache, CtrPage* page, CtrTile* tile) {
    uint32_t bytes = (uint32_t) page->tileW * (uint32_t) page->tileH * CtrPack_texelBytes((CtrTileFormat) tile->format);
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
    return btStolen(pageId) BTD(|| btdFile(pageId)) ? nullptr : __real_CtrFlowstream_gameFile(pageId);
}

BT_TEXT FILE* __wrap_CtrFlowstream_openFile(uint32_t pageId, bool* busy) {
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
    return cache->frame >= page->retryFrame && page->packed == nullptr && page->read == nullptr && (!page->packInfo || btRoomFor(cache, page, tile));
}

BT_TEXT void __wrap_CtrFlowstream_collect(CtrTextureCache* cache, bool drop) {
    __real_CtrFlowstream_collect(cache, drop);
    Runner* runner = cache != nullptr ? cache->runner : nullptr;
    if (runner == nullptr || cache->reader == nullptr) return;
    if (bt.cache != cache || bt.roomStart != cache->roomStartFrame) {
        // A room change: the cache released our reads with the room's.
        if (bt.scene != nullptr)
            logInfo(btLog, (long) bt.group, (unsigned) bt.installed, (unsigned) bt.missing, (unsigned) bt.frames, (unsigned) bt.untabled,
                    (unsigned) bt.reads, (double) bt.installTicks / (double) (SYSCLOCK_ARM11 / 1000u),
                    (double) bt.maxTicks / (double) (SYSCLOCK_ARM11 / 1000u));
        BTD(btdMark(bt.scene != nullptr ? "the encounter animation and the battle room load" : nullptr));
        memset((void*) &bt.cache, 0, sizeof(bt) - offsetof(__typeof__(bt), cache));
        bt.cache = cache;
        bt.roomStart = cache->roomStartFrame;
    }
    BTD(btdMark(cache->frame - bt.roomStart == 300u ? "the room's first 300 frames" : nullptr));
    // The reads in: their tiles installed while there is room and time, else dropped; a read is released once all its
    // tiles are, and one cut short by the time keeps the page until the next frame.
    uint64_t start = svcGetSystemTick();
    uint64_t budget = (uint64_t) BT_INSTALL_MS * (SYSCLOCK_ARM11 / 1000u);
    uint32_t done = 0;
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
            if (read->headerOk && tile != nullptr && read->data != nullptr && read->tileAt[t] != CTR_READ_NOT_READ &&
                tile->offset == read->view.tileOffset[t] && tile->size == read->view.tileSize[t] && btRoomFor(cache, page, tile) &&
                BTD(!btdFault(k, 3) &&) btReserve(cache, page, tile)) {
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
    bt.scene = scene;
    bt.group = group;
    bt.frames++;
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
        }
        struct mallinfo mi = mallinfo();
        if (__ctru_heap_size < (uint32_t) mi.uordblks + CtrTileReader_heapReserve() + bytes) break;
        bool allowed = CtrMemory_allowRelief(false);
        CtrTileRead* read = CtrTileReader_newRead();
        CtrMemory_allowRelief(allowed);
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
    uint32_t minFree, queued, outcome[9];
    uint8_t kind[BT_READS];  // each read in flight's fault (0 none, 1 refused, 2 allocation fails, 3 texture fails, 7 no file)
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
            "taken or released %lu, finished empty %lu, not installed %lu, game-thread files refused %lu, read on the game thread %lu; faults: refused %lu, allocation failed %lu, texture failed %lu, no file %lu\n", what,
            (unsigned long) (low / 1024), low >= 4096u * 1024u ? "above" : "BELOW", (unsigned long) btd.queued,
            (unsigned long) (btd.queued - btd.outcome[4] - btd.outcome[5]), (unsigned long) btd.outcome[4],
            (unsigned long) btd.outcome[5], (unsigned long) btd.outcome[6], (unsigned long) btd.outcome[8], (unsigned long) btd.outcome[1], (unsigned long) btd.outcome[2],
            (unsigned long) btd.outcome[3], (unsigned long) btd.outcome[7]);
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
}
#endif
#endif
