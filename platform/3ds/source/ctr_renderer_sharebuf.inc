// ===[ sharebuf: surfaces that share one buffer (change titancpu, DELTARUNE New only) ]===
//
// DELTARUNE Chapter 4's Titan fires its big rays in barrages: every ray object makes its own 640x480 surface
// and, each frame, clears the whole surface, draws two triangles on it, draws the surface once (additive) and leaves
// it until next frame; CleanUp frees it. On the console each ray's surface is a 512x256 native-scale texture of 496 KB
// (248 rows), in VRAM while it fits, then spilled into linear memory: a barrage holds megabytes for pixels that live
// one draw.
//
// For the objects the builder lists (tools/roomplan/build_sharebuf.py: romfs:/roomplan/sharebuf.dtp, written only for
// the data.win the PC code was read on, and checked here against its key and object names), a surface made in their
// code is a transient: a spilled surface with no texture of its own, whose pixels live only in its scratch, the VRAM
// render target every spilled surface of its size takes turns with (bindTarget). Its ID is a full surface on every
// other count (surface_exists, its size, surface_free; resizing or freeing it ends the transient), and the scratch
// itself is the surface's own VRAM taken over when it had some (the first ray of a barrage) or one already there of
// its size; VRAM taken over goes back once no surface uses it any more, as the surface's own would have at its free.
//
// What makes a transient exact: the store that would copy its pixels out of the scratch, when the next surface binds
// the scratch (flushPendingStore), is skipped only when the scratch was sampled since it last drew (the ray's draw of
// its surface): by the PC code, nothing reads those pixels again before the ray clears them next frame. Everything
// else that could reach them first gives the surface a texture of its own, with its pixels if they are still in the
// scratch (exact): any read but the sampled draw, a store without a sample since the draw, a frame skip setting, a
// scratch released for VRAM (releaseIdleScratches stores through flushPendingStore too; a sampled ray's store is
// skipped there and the scratch's target is deleted only after the frame is suspended, so the queued draw that
// samples it runs first). Only one case can't be exact: a read after the skip, once another surface has drawn over
// the scratch (or a load into the scratch for a draw that doesn't start with a whole clear). The PC code says it
// never happens; if it does, that frame shows the surface blank, the log says SHAREBUF VIOLATION, and sharing stops
// for the session. build.sh sharebuf=test forces one, to show it fires.
//
// Hooks: no table entry, so knightgpu's and natsurf6's wrappers stay as they are, and no change to ctr_renderer.c's
// code. This file is compiled only in the vine helper pass (tools/analysis/vine_old_parent.py adds its sections to
// the original pass's assembly, which never sees it), and vine_old_observer_compile.py routes these calls, each
// counted, in the original assembly: loadSpill in clearBoundTarget, reserveBatch and ctrSurfaceCopy (all its
// calls), flushPendingStore in surfaceTexture, releaseIdleScratches and bindTarget (all), touchSurface in bindTarget
// and surfaceTexture (so a touch knows it is a bind or a sample), touchSurface's tail call of unparkSurface (a
// transient looks parked: touchSurface hands it on, never to makeTextureNow), and createSurface in ctrCreateSurface.
// Each original makes a call GCC can't see into (GX_TextureCopy, C3D_SyncTextureCopy, GSPGPU_FlushDataCache,
// CtrLz_decompress, logInfo), so its callers keep nothing in call-clobbered registers, or in memory, across it
// (IPA-RA, modref) that a wrapper could break. This file reaches the file's functions only through SB_CALL (an
// opaque pointer: the original body runs, never a copy or a clone) and copies of its inline helpers.
// A transient has tex.data nullptr and parked != nullptr, which every fast path that reads a texture directly
// (knsurf, copyIntoLinear, knightgpu's moves and swaps, parking) already leaves alone.
#ifdef CTRPORT_SHAREBUF

// Os: late text is short (vine_titancpu.inc does the same); no switch tables (they would go in plain .rodata).
#define SB_TEXT __attribute__((noipa, used, optimize("Os", "no-tree-switch-conversion"), section(".text.sharebuf_late")))
#define SB_RO __attribute__((section(".rodata.sharebuf_late")))
#define SB_BSS __attribute__((section(".bss.sharebuf_late")))
// The original pass's function, by name, through a pointer GCC can't see through (as vine_new_retain.inc's VR_CALL).
#define SB_CALL(name) ({ __typeof__(&(name)) sbFn = &(name); __asm__("" : "+r"(sbFn)); sbFn; })

// Copies of the file's inline helpers (the original pass has no body of them to call).
static inline __attribute__((always_inline)) int32_t sbRows(const C3D_Tex* tex) {
    return (int32_t) (tex->size / ((uint32_t) tex->width * 4u)); // textureRows
}

static inline __attribute__((always_inline)) int32_t sbRoot(const CtrRenderer* r, int32_t k) {
    return 0 <= r->scratches[k].base ? r->scratches[k].base : k; // scratchRoot
}

#define SB_MAX 32          // transients at once (a barrage is about ten)
#define SB_ADOPT_MAX 4     // scratches made of a surface's own VRAM at once
#define SB_OBJECTS_MAX 8   // build_sharebuf.py ENTRIES_MAX
#define SB_FILE_MAX 4096
#define SB_MAGIC 0x42535444u // "DTSB"
#define SB_VERSION 1u
#define SB_NAME_BYTES 32u
#define SB_CONVERT_LOGS 8u

enum { SB_CTX_NONE, SB_CTX_BIND, SB_CTX_SAMPLE };

typedef struct {
    int32_t id;
    void* token; // its CtrSurface.parked, a heap block freeParked frees with the surface
} SbEntry;

typedef struct {
    int32_t k;
    C3D_RenderTarget* target; // the slot is still ours while it holds this target
} SbAdopted;

static struct {
    CtrRenderer* r;
    uint32_t frame; // r->frame at the last check (sbFrame)
    SbEntry e[SB_MAX];
    uint32_t n;
    SbAdopted adopted[SB_ADOPT_MAX];
    uint32_t adoptedN;
    uint8_t ctx;
    bool disabled; // after a violation, for the session
    bool fileTried;
    uint8_t* file;
    uint32_t fileSize;
    const DataWin* listFor;
    size_t listSize;
    uint64_t listStamp;
    uint32_t objectCount;
    int32_t objects[SB_OBJECTS_MAX];
    // Since the last time no transient was left (logged then).
    uint32_t unmade, took, joined, skipped, converted, refused;
    uint32_t violations, convertLogs; // the session's
#ifdef CTRPORT_SHAREBUF_TEST
    uint32_t testMade;
#endif
} sb SB_BSS;

static const char sbPath[] SB_RO = "romfs:/roomplan/sharebuf.dtp";
static const char sbMode[] SB_RO = "rb";
static const char sbLogFile[] SB_RO = "Sharebuf: %lu bytes, %lu sections\n";
static const char sbLogList[] SB_RO = "Sharebuf: %lu object(s) of this data.win share their surfaces' buffers (first: %s)\n";
static const char sbLogBadName[] SB_RO = "Sharebuf: list entry %lu names %s, not object %lu's %s: left out\n";
static const char sbLogStart[] SB_RO = "Sharebuf: surface %d (%dx%d) of %s shares scratch %d (%s)\n";
static const char sbHowUnmade[] SB_RO = "spilled when made";
static const char sbHowTook[] SB_RO = "its own VRAM became the scratch";
static const char sbHowJoined[] SB_RO = "its own VRAM freed";
static const char sbLogDone[] SB_RO =
    "Sharebuf: no shared surface left: %lu shared (%lu spilled when made, %lu took their VRAM as the scratch, %lu "
    "joined one), %lu stores skipped, %lu given a texture of their own, %lu refused\n";
static const char sbLogConvert[] SB_RO = "Sharebuf: surface %d given a texture of its own (%s; its pixels %s)\n";
static const char sbKept[] SB_RO = "kept from the scratch";
static const char sbBlank[] SB_RO = "never drawn";
static const char sbLost[] SB_RO = "LOST";
static const char sbLogNoMem[] SB_RO = "Sharebuf: no linear memory to give surface %d (%dx%d) a texture of its own (%s): recording its draws\n";
static const char sbLogViolation[] SB_RO =
    "SHAREBUF VIOLATION: surface %d (%dx%d) read after its shared buffer was reused (%s, frame %lu): this frame's "
    "pixels differ from the PC's; sharing is off from now on (%lu violation(s))\n";
static const char sbLogReleased[] SB_RO = "Sharebuf: scratch %d (taken from a surface's VRAM) released: no surface uses it\n";
static const char sbWhyRead[] SB_RO = "a read";
static const char sbWhySample[] SB_RO = "a sample";
static const char sbWhyStore[] SB_RO = "a store without a sample since its draw";
static const char sbWhyLoad[] SB_RO = "a draw without a whole clear first";
#ifdef CTRPORT_SHAREBUF_TEST
static const char sbLogTest[] SB_RO = "Sharebuf test: reading surface %d after its buffer was reused, to force a violation\n";
#endif

static SB_TEXT bool sbSame(const C3D_Tex* a, const C3D_Tex* b) {
    return a->width == b->width && a->height == b->height && sbRows(a) == sbRows(b);
}

static SB_TEXT bool sbValid(CtrRenderer* r, const SbEntry* e) {
    if (0 > e->id || (int32_t) r->surfaceCount <= e->id) return false;
    const CtrSurface* s = &r->surfaces[e->id];
    return s->used && s->spilled && !s->recorded && s->parked == e->token && s->tex.data == nullptr;
}

static SB_TEXT void sbRemove(uint32_t i) {
    sb.e[i] = sb.e[--sb.n];
}

// Entry i for surface id, if it is still a transient; one that isn't any more goes.
static SB_TEXT int32_t sbFind(CtrRenderer* r, int32_t id) {
    for (uint32_t i = 0; sb.n > i; i++) {
        if (sb.e[i].id != id) continue;
        if (sbValid(r, &sb.e[i])) return (int32_t) i;
        sbRemove(i);
        return -1;
    }
    return -1;
}

static SB_TEXT void sbLoadFile(void) {
    sb.fileTried = true;
    FILE* f = fopen(sbPath, sbMode);
    if (f == nullptr) return;
    uint8_t* data = malloc(SB_FILE_MAX);
    size_t size = data != nullptr ? fread(data, 1, SB_FILE_MAX, f) : 0;
    fclose(f);
    uint32_t head[3] = { 0, 0, 0 };
    if (size >= 12 && SB_FILE_MAX > size) memcpy(head, data, 12);
    if (head[0] != SB_MAGIC || head[1] != SB_VERSION) {
        free(data);
        return;
    }
    sb.file = data;
    sb.fileSize = (uint32_t) size;
    logInfo(sbLogFile, (unsigned long) size, (unsigned long) head[2]);
}

// This data.win's objects, from the section made for it.
static SB_TEXT void sbParse(const DataWin* dw) {
    sb.listFor = dw;
    sb.listSize = dw->fileSize;
    sb.listStamp = dw->gen8.timestamp;
    sb.objectCount = 0;
    if (sb.file == nullptr) return;
    uint32_t sections;
    memcpy(&sections, sb.file + 8, 4);
    uint32_t at = 12;
    for (uint32_t sec = 0; sections > sec && sb.fileSize >= at + 28u; sec++) {
        uint32_t h[7];
        memcpy(h, sb.file + at, 28);
        at += 28;
        uint64_t stamp = (uint64_t) h[2] | (uint64_t) h[3] << 32;
        uint32_t n = h[6];
        if (n > (sb.fileSize - at) / (4u + SB_NAME_BYTES)) return;
        bool match = h[0] == (uint32_t) dw->fileSize && h[1] == dw->gen8.gameID && stamp == dw->gen8.timestamp &&
                     h[4] == dw->room.count && h[5] == dw->objt.count;
        for (uint32_t j = 0; match && n > j; j++) {
            uint32_t index;
            char name[SB_NAME_BYTES + 1];
            memcpy(&index, sb.file + at + (4u + SB_NAME_BYTES) * j, 4);
            memcpy(name, sb.file + at + (4u + SB_NAME_BYTES) * j + 4u, SB_NAME_BYTES);
            name[SB_NAME_BYTES] = '\0';
            const char* real = dw->objt.count > index ? dw->objt.objects[index].name : nullptr;
            if (real == nullptr || strcmp(real, name) != 0) {
                logWarn(sbLogBadName, (unsigned long) j, name, (unsigned long) index, real != nullptr ? real : sbBlank);
                continue;
            }
            if (SB_OBJECTS_MAX > sb.objectCount) sb.objects[sb.objectCount++] = (int32_t) index;
        }
        at += (4u + SB_NAME_BYTES) * n;
        if (match) break;
    }
    if (sb.objectCount != 0) logInfo(sbLogList, (unsigned long) sb.objectCount, dw->objt.objects[sb.objects[0]].name);
}

// The object whose code runs is listed: its index, else -1.
static SB_TEXT int32_t sbListedObject(CtrRenderer* r) {
    const DataWin* dw = r->base.dataWin;
    const Runner* runner = r->base.runner;
    if (dw == nullptr || runner == nullptr || runner->vmContext == nullptr) return -1;
    if (sb.listFor != dw || sb.listSize != dw->fileSize || sb.listStamp != dw->gen8.timestamp) sbParse(dw);
    const Instance* inst = runner->vmContext->currentInstance;
    if (inst == nullptr || sb.objectCount == 0) return -1;
    for (uint32_t i = 0; sb.objectCount > i; i++) {
        if (sb.objects[i] == inst->objectIndex) return inst->objectIndex;
    }
    return -1;
}

// VRAM taken over from a surface (shareCreate) goes once no surface uses it, as the surface's own would have at its
// free; false while one does (or something else aliases it).
static SB_TEXT bool sbRelease(CtrRenderer* r, const SbAdopted* a) {
    if (arrlen(r->scratches) <= a->k || r->scratches[a->k].target != a->target) return true; // released already
    for (ptrdiff_t j = 0; arrlen(r->scratches) > j; j++) {
        if (r->scratches[j].base == a->k && r->scratches[j].target != nullptr) return false;
    }
    for (uint32_t i = 0; r->surfaceCount > i; i++) {
        const CtrSurface* s = &r->surfaces[i];
        if (s->used && s->spilled && (s->scratch == a->k || (0 <= s->scratch && arrlen(r->scratches) > s->scratch &&
                                                              r->scratches[s->scratch].base == a->k))) {
            return false;
        }
    }
    CtrScratch* sc = &r->scratches[a->k];
    // Draws recorded so far may sample it: they go first, and the memory after the GPU (deferred, as a surface's).
    SB_CALL(flushBatch)(r);
    SB_CALL(queueDeferredFree)(r, (CtrDeferredFree) { sc->tex, sc->target });
    sc->target = nullptr;
    sc->owner = -1;
    sc->releasing = false;
    sc->pendingStore = false;
    sc->sampled = false;
    sc->base = -1;
    logInfo(sbLogReleased, (int) a->k);
    return true;
}

// Entries whose surface stopped being a transient (freed, resized, recorded, given its texture) go, and so do
// scratches taken over that nothing uses now.
static SB_TEXT void sbPurge(CtrRenderer* r) {
    bool had = sb.n != 0;
    uint32_t kept = 0;
    for (uint32_t i = 0; sb.n > i; i++) {
        if (sbValid(r, &sb.e[i])) sb.e[kept++] = sb.e[i];
    }
    sb.n = kept;
    kept = 0;
    for (uint32_t i = 0; sb.adoptedN > i; i++) {
        if (!sbRelease(r, &sb.adopted[i])) sb.adopted[kept++] = sb.adopted[i];
    }
    sb.adoptedN = kept;
    if (had && sb.n == 0) {
        logInfo(sbLogDone, (unsigned long) (sb.unmade + sb.took + sb.joined), (unsigned long) sb.unmade, (unsigned long) sb.took,
                (unsigned long) sb.joined, (unsigned long) sb.skipped, (unsigned long) sb.converted, (unsigned long) sb.refused);
        sb.unmade = sb.took = sb.joined = sb.skipped = sb.converted = sb.refused = 0;
    }
}

// Once a frame (the first bind), and at every create: a new renderer starts empty; the list file is read once, at
// the first frame's first bind (the boot, not a fight).
static SB_TEXT void sbFrame(CtrRenderer* r) {
    if (sb.r != r || sb.frame > r->frame) {
        sb.r = r;
        sb.n = 0;
        sb.adoptedN = 0;
    }
    sb.frame = r->frame;
    if (!sb.fileTried) sbLoadFile();
    if (sb.n != 0 || sb.adoptedN != 0) sbPurge(r);
}

static SB_TEXT void sbViolation(CtrRenderer* r, const CtrSurface* s, int32_t id, const char* why) {
    sb.violations++;
    sb.disabled = true;
    logError(sbLogViolation, (int) id, (int) s->width, (int) s->height, why, (unsigned long) r->frame, (unsigned long) sb.violations);
}

// Transient i gets a texture of its own: a spilled surface like any other from now on. Its pixels, if the scratch
// still holds them, go there by the ordinary store; if they are gone, it is a violation. False if linear memory had
// no room: recorded from now on, as makeTextureNow leaves a surface.
static SB_TEXT bool sbConvert(CtrRenderer* r, uint32_t i, const char* why) {
    int32_t id = sb.e[i].id;
    CtrSurface* s = &r->surfaces[id];
    sbRemove(i);
    int32_t k = s->scratch;
    CtrScratch* sc = 0 <= k && arrlen(r->scratches) > k ? &r->scratches[k] : nullptr;
    bool here = sc != nullptr && sc->target != nullptr && sc->owner == id;
    bool lost = !here && !s->needsClear;
    C3D_Tex tex;
    if (!SB_CALL(initLinearTextureForCpu)(r, &tex, s->tex.width, s->tex.height, sbRows(&s->tex))) {
        logWarn(sbLogNoMem, (int) id, (int) s->width, (int) s->height, why);
        SB_CALL(recordParked)(r, s);
        return false;
    }
    memset(tex.data, 0, tex.size);
    GSPGPU_FlushDataCache(tex.data, tex.size);
    s->tex = tex;
    // freeParked (inline in the original pass): the token is a heap block of ours, never PARKED_BLANK or _UNMADE.
    free(s->parked);
    free(s->parkedSizes);
    s->parked = nullptr;
    s->parkedSizes = nullptr;
    sb.converted++;
    if (lost) {
        sbViolation(r, s, id, why);
    } else if (here) {
        if (r->spillBound == id) {
            r->spillDirty = true;
        } else {
            sc->pendingStore = true;
            // A surface bound through the same VRAM, its pixels not loaded yet, has flushed the scratch already
            // (bindTarget): the store goes now, before its load or clear.
            int32_t b = r->spillBound;
            if (0 <= b && sbRoot(r, r->surfaces[b].scratch) == sbRoot(r, k)) SB_CALL(flushPendingStore)(r, k);
        }
    }
    if (SB_CONVERT_LOGS > sb.convertLogs || lost) {
        sb.convertLogs++;
        logInfo(sbLogConvert, (int) id, why, lost ? sbLost : here ? sbKept : sbBlank);
    }
    return true;
}

static SB_TEXT bool shareUnpark(CtrRenderer* r, CtrSurface* s, uint32_t idleFrames) {
    uint8_t ctx = sb.ctx;
    sb.ctx = SB_CTX_NONE;
    int32_t id = (int32_t) (s - r->surfaces);
    int32_t i = sb.n != 0 ? sbFind(r, id) : -1;
    if (0 > i) return SB_CALL(unparkSurface)(r, s, idleFrames);
    // Bound to be drawn on: a whole clear claims the scratch, anything else loads (shareLoad).
    if (ctx == SB_CTX_BIND) return true;
    if (ctx == SB_CTX_SAMPLE) {
        const CtrScratch* sc = &r->scratches[s->scratch];
        // Its pixels are in the scratch, sampled there (surfaceTexture).
        if (sc->target != nullptr && sc->owner == id && sc->pendingStore && sbSame(&sc->tex, &s->tex)) return true;
    }
    return sbConvert(r, (uint32_t) i, ctx == SB_CTX_SAMPLE ? sbWhySample : sbWhyRead);
}

static SB_TEXT bool shareTouchBind(CtrRenderer* r, CtrSurface* s) {
    if (sb.frame != r->frame || sb.r != r) sbFrame(r);
    if (s->parked == nullptr) return SB_CALL(touchSurface)(r, s);
    sb.ctx = SB_CTX_BIND;
    bool ok = SB_CALL(touchSurface)(r, s);
    sb.ctx = SB_CTX_NONE;
    return ok;
}

static SB_TEXT bool shareTouchSample(CtrRenderer* r, CtrSurface* s) {
    if (s->parked == nullptr) return SB_CALL(touchSurface)(r, s);
    sb.ctx = SB_CTX_SAMPLE;
    bool ok = SB_CALL(touchSurface)(r, s);
    sb.ctx = SB_CTX_NONE;
    return ok;
}

static SB_TEXT void shareFlush(CtrRenderer* r, int32_t k) {
    CtrScratch* sc = &r->scratches[k];
    int32_t i = sc->pendingStore && sb.n != 0 ? sbFind(r, sc->owner) : -1;
    if (0 > i) {
        SB_CALL(flushPendingStore)(r, k);
        return;
    }
    CtrSurface* s = &r->surfaces[sc->owner];
    // Drawn and then sampled (its one draw a frame): by the PC code nothing reads these pixels again before the
    // next whole clear. The draws that sample the scratch go to the GPU before anything draws over it.
    if (!sb.disabled && sc->sampled && s->scratch == k && sc->target != nullptr && sbSame(&sc->tex, &s->tex) &&
        r->skip.max == 0 && !r->skip.active && s->lazyRefs == 0 && s->skipRealRefs == 0 && s->skipRec == nullptr) {
        sc->pendingStore = false;
        if (r->inFrame && r->drawnSinceSplit) SB_CALL(splitFrame)(r);
        sb.skipped++;
        return;
    }
    if (sbConvert(r, (uint32_t) i, sbWhyStore)) SB_CALL(flushPendingStore)(r, k);
}

static SB_TEXT void shareLoad(CtrRenderer* r) {
    int32_t i = sb.n != 0 && 0 <= r->spillBound ? sbFind(r, r->spillBound) : -1;
    // Its pixels aren't in the scratch (another surface's are): they were needed after all.
    if (0 <= i && !sbConvert(r, (uint32_t) i, sbWhyLoad)) return;
    SB_CALL(loadSpill)(r);
}

// Made in a listed object's code: a transient, if it can be one (see the top of this file).
static SB_TEXT int32_t shareCreate(CtrRenderer* r, int32_t width, int32_t height, bool record) {
    int32_t id = SB_CALL(createSurface)(r, width, height, record);
    if (0 > id) return id;
    if (sb.frame != r->frame || sb.r != r) sbFrame(r);
    else if (sb.n != 0) sbPurge(r);
    if (sb.disabled || r->skip.max != 0 || r->quadClears) return id;
    int32_t object = sbListedObject(r);
    if (0 > object) return id;
    CtrSurface* s = &r->surfaces[id];
    if (SB_MAX <= sb.n || !s->used || s->recorded || s->windowed || !s->needsClear || s->lazy != nullptr || s->lazyRefs != 0 ||
        s->skipRec != nullptr || s->skipRealRefs != 0 || s->noVram) {
        sb.refused++;
        return id;
    }
    void* token = malloc(4);
    if (token == nullptr) return id;
    const char* how = sbHowUnmade;
    if (s->spilled) {
        const CtrScratch* sc = &r->scratches[s->scratch];
        if (s->parked != PARKED_UNMADE || s->tex.data != nullptr || sc->target == nullptr || !sbSame(&sc->tex, &s->tex)) {
            free(token);
            sb.refused++;
            return id;
        }
        sb.unmade++;
    } else {
        uintptr_t at = (uintptr_t) s->tex.data;
        bool own = s->tex.data != nullptr && s->target != nullptr && s->parked == nullptr && at >= OS_VRAM_VADDR &&
                   OS_VRAM_VADDR + OS_VRAM_SIZE > at;
#if defined(ENABLE_WAD17) && defined(CTRPORT_KNIGHTGPU_LENDER)
        // VRAM knightgpu lends is its to manage.
        if (kg.base != nullptr && at >= (uintptr_t) kg.base && (uintptr_t) kg.base + (KG_SLOTS + 1u) * kg.slotSize > at) own = false;
#endif
        int32_t k = -1, freeSlot = -1;
        for (ptrdiff_t j = 0; own && arrlen(r->scratches) > j; j++) {
            const CtrScratch* sc = &r->scratches[j];
            if (sc->target == nullptr) {
                if (0 > freeSlot) freeSlot = (int32_t) j;
            } else if (sbSame(&sc->tex, &s->tex)) {
                k = (int32_t) j;
                break;
            }
        }
        if (own && 0 > k && SB_ADOPT_MAX > sb.adoptedN) {
            if (0 > freeSlot) {
                // The open batch may sample a scratch's C3D_Tex, which is about to move (as scratchFor).
                SB_CALL(flushBatch)(r);
                CtrScratch empty = { .target = nullptr, .owner = -1, .base = -1 };
                if (CTR_ARRAY_PUT(r->scratches, empty)) freeSlot = (int32_t) arrlen(r->scratches) - 1;
            }
            if (0 <= freeSlot) {
                r->scratches[freeSlot] = (CtrScratch) { .tex = s->tex, .target = s->target, .owner = -1, .lastBound = r->frame - 1u, .base = -1 };
                sb.adopted[sb.adoptedN++] = (SbAdopted) { freeSlot, s->target };
                k = freeSlot;
                how = sbHowTook;
                sb.took++;
            }
        } else if (own && 0 <= k) {
            // Nothing has drawn on it or sampled it yet.
            SB_CALL(queueDeferredFree)(r, (CtrDeferredFree) { s->tex, s->target });
            how = sbHowJoined;
            sb.joined++;
        }
        if (0 > k) {
            free(token);
            sb.refused++;
            return id;
        }
        s->tex.data = nullptr;
        s->spilled = true;
        s->scratch = k;
        s->target = r->scratches[k].target;
        s->storeQueued = false;
        s->parkedSizes = nullptr;
    }
    s->parked = token;
    sb.e[sb.n++] = (SbEntry) { id, token };
    if (sb.n == 1) {
        logInfo(sbLogStart, (int) id, (int) s->width, (int) s->height, r->base.dataWin->objt.objects[object].name, (int) s->scratch, how);
    }
#ifdef CTRPORT_SHAREBUF_TEST
    // From the third transient of the session on, until one fires: an earlier one whose pixels another has drawn
    // over is read back, a violation on purpose, with nothing drawn (that ray clears its surface before it next draws
    // on it). After it, sharing is off and no create gets here.
    if (++sb.testMade >= 3) {
        for (uint32_t i = 0; sb.n > i; i++) {
            CtrSurface* t = &r->surfaces[sb.e[i].id];
            const CtrScratch* sc = &r->scratches[t->scratch];
            if (t->needsClear || (sc->target != nullptr && sc->owner == sb.e[i].id)) continue;
            logInfo(sbLogTest, (int) sb.e[i].id);
            shareTouchSample(r, t);
            break;
        }
    }
#endif
    return id;
}

// G2 (build.sh sharebuf=g1 leaves it out): appended after everything above, in sections of its own.
#ifdef CTRPORT_SHAREBUF_G2
#include "ctr_renderer_sharebuf_g2.inc"
#endif
#endif
