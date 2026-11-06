// Preloading can remove the later draw misses that requested a packed copy.
// After the room's tiles and code have finished, restore that intent for
// pages read by this load. The existing per-frame repeat gate, worker,
// admission, heap reserve and promotion picker still decide what is read.
// No file is opened here: the validated tile table already gives its size.
#if defined(ENABLE_WAD16) && defined(CTRPORT_TARGET_O3DS)

#include "ctr_textures.h"
#include "runner.h"

#define UTCREDEPI_PAGES 64u
#define UTCREDEPI_TEXT __attribute__((noinline, optimize("Os"), section(".text_utcredepi")))

void __real_CtrTextures_roomLoadedOld(CtrTextureCache* cache, Runner* runner);
void __wrap_CtrTextures_roomLoadedOld(CtrTextureCache* cache, Runner* runner);

UTCREDEPI_TEXT void __wrap_CtrTextures_roomLoadedOld(CtrTextureCache* cache, Runner* runner) {
    uint32_t before[UTCREDEPI_PAGES];
    uint32_t count = cache != nullptr ? cache->pageCount : 0;
    bool track = count > 0 && count <= UTCREDEPI_PAGES && cache->reader != nullptr && cache->packedBudgetBytes > 0;
    if (track) {
        for (uint32_t i = 0; count > i; i++) before[i] = cache->pages[i].fileLoads;
    }
    __real_CtrTextures_roomLoadedOld(cache, runner);
    if (!track) return;

    uint32_t done = 0, total = 0;
    if (cache->worker != nullptr && cache->workerKeepsPacked) {
        CtrPackWorker_progress(cache->worker, &done, &total);
        if (total > done) return;
    }
    for (uint32_t i = 0; count > i; i++) {
        CtrPage* page = &cache->pages[i];
        if (page->fileLoads == before[i] || page->packed != nullptr || page->failed || !page->packInfo ||
            page->tiles == nullptr || page->cacheFile != CTR_CACHE_FILE_VALID || page->promotionPending ||
            page->promotionRetryFrame > cache->frame || (cache->wholeRead != nullptr && cache->wholePage == i)) continue;
        int32_t tiles = page->tilesX * page->tilesY;
        if (tiles <= 0 || tiles > CTR_PAGE_MAX_TILES) continue;
        // CtrPack_readView lays every tile consecutively, including empty
        // tiles. The last offset plus size is the validated total file size.
        const CtrTile* last = &page->tiles[tiles - 1];
        uint32_t bytes = last->offset + last->size;
        if (bytes == 0 || bytes > cache->packedBudgetBytes) continue;
        page->promotionBytes = bytes;
        page->promotionPending = true;
    }
}

#endif
