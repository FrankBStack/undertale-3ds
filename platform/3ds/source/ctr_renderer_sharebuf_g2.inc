// G2 (change titancpu): a whole clear of a shared scratch to zero fills only the rows that can hold anything else.
//
// Included at the end of ctr_renderer_sharebuf.inc (G1), with CTRPORT_SHAREBUF_G2 only, and append-only against G1:
// G1's code, constants and state are compiled exactly as without it; G2's code, constants and state have sections of
// their own, linked after G1's (late_reserve.ld). vine_old_observer_compile.py routes, in the original assembly,
// clearBoundTarget's C3D_FrameBufClear (linked as knightgpu's __wrap_C3D_FrameBufClear) to shareClear,
// processDeferredFrees' and releaseIdleScratches' C3D_RenderTargetDelete to shareTargetDelete, and the calls that
// went to G1's shareTouchBind (bindTarget, 1) and shareLoad (loadSpill's three) to shareBindG2 and shareLoadG2, which
// run G2's part and then G1's (by address: sbG1Calls). check_sharebuf_layout.py --g2 proves it against the G1 build.
//
// Each frame every ray binds the one scratch, clears all 248 rows of it, draws two triangles over about a third of
// them and leaves it; the next ray's clear fills the whole buffer again for those few rows. A slot (SbDirty) keeps,
// for a scratch's colour buffer, which rows may be nonzero: none (EMPTY), rows row0 to row1 (BOX), or anything (no
// slot, or NONE). shareClear fills only the 8-row tile bands over BOX's rows, or nothing for EMPTY; any other clear
// (another value, another target, no slot) is the whole fill.
//
// A slot is opened (OPEN) by a whole clear to zero of a transient's binding: everything drawn on it from then on is a
// vertex at r->vertices[vStart] on, put through the uploaded projection and the viewport. When anything binds a
// surface (shareBindG2, before the switch), or clears, the OPEN slot is closed: its rows are those vertices' rows,
// two rows more each side, and BOX; or EMPTY with nothing drawn. It is closed to NONE instead when the vertices can't
// be trusted to be all that was drawn, through the projection seen at the clear: another frame, the vertex ring gone
// round or vertices taken back (vertexCount and vertexUsed not moved by the same), an own matrix uploaded since
// (r->uploadedOwn, unused while gameProjection holds, is marked at the clear; any own upload writes it), the game's
// projection rows or viewport changed, frame skip, or more than SB_BOX_VERTICES. What listing an object promises
// besides (build_sharebuf.py): its draws on its surface are the game's plain draws under the surface's own projection
// and viewport, which no draw changes and puts back.
//
// A slot describes memory, so only what writes the memory touches it. A binding of anything over a slot's memory
// (pending) keeps the slot only while nothing at all is drawn (vertexCount and vertexUsed as at the bind); a load into
// the bound target (shareLoadG2: every loadSpill call) or a target deleted (shareTargetDelete: every delete of a
// scratch's target) forgets it, and so does a clear to another value. A transient given a texture of its own (G1's
// sbConvert) writes only its new linear texture (the scratch is read, by the store), so it leaves the slots as they
// are: from then on the surface is an ordinary spilled one, whose loads, binds and clears are the ones above.
// build.sh sharebuf=fulltest fills whole every time and checks, at each clear a slot would have cut, that the memory
// outside its rows is all zero (the GPU run first), logging SHAREBUF BOX MISS if not.

#define SB2_TEXT __attribute__((noipa, used, optimize("Os", "no-tree-switch-conversion"), section(".text.sharebuf_g2_late")))
#define SB2_RO __attribute__((section(".rodata.sharebuf_g2_late")))
#define SB2_BSS __attribute__((section(".bss.sharebuf_g2_late")))

#define SB_SLOTS 4
#define SB_BOX_VERTICES 4096u // more drawn in one binding: the whole clear
#define SB_OWN_MARK 0x7FC5B0F1u // a NaN no matrix holds
enum { SB_D_NONE, SB_D_EMPTY, SB_D_BOX, SB_D_OPEN };

typedef struct {
    uintptr_t at;   // the colour buffer (the key)
    uint32_t bytes; // what a whole clear fills: width * height * 4
    uint16_t width, height;
    uint8_t state;  // NONE: anything (a whole clear fills it all); EMPTY: zeros; BOX: zeros but rows [row0, row1]
    bool pending;   // bound since: still EMPTY or BOX only if nothing has drawn since (frame, vStart, uStart)
    int16_t row0, row1;
    uint32_t frame, vStart, uStart; // OPEN: at the clear; pending: at the bind
    CtrRect view;                   // OPEN: the game's viewport at the clear
    int32_t vy, vh;                 // OPEN: the GPU viewport's rows, as applyEyeViewport sets them
    C3D_FVec u1, u3;                // OPEN: the projection's y and w rows, as uploaded
} SbDirty;

static struct {
    CtrRenderer* r;
    uint32_t frame; // r->frame at the last look (sbgSync)
    SbDirty d[SB_SLOTS];
    // Whole clears of a tracked scratch since the last log: left out (nothing drawn), cut to rows (and those rows,
    // of how many), filled whole.
    uint32_t clearSkip, clearCut, cutRows, ofRows, clearWhole;
#ifdef CTRPORT_SHAREBUF_FULLTEST
    uint32_t checks, fails; // the session's
#endif
} sbg SB2_BSS;

static const char sbLogClears[] SB2_RO = "Sharebuf: %lu whole clears of shared scratches left out (nothing drawn), %lu cut to %lu of %lu rows, %lu whole\n";
#ifdef CTRPORT_SHAREBUF_FULLTEST
static const char sbLogCheck[] SB2_RO = "SHAREBUF BOX MISS: frame %lu, scratch %08lx: rows %d to %d drawn on outside rows %d to %d (%lu of %lu checks)\n";
static const char sbLogChecks[] SB2_RO = "Sharebuf full test: %lu clears checked, %lu found pixels outside their rows\n";
#endif

// G1's functions that G2 calls, by address words in G2's constants (an assembler block GCC can't see into). Any C
// reference to them, even SB_CALL's address, makes GCC emit G1's functions in another order: G1 would move.
__asm__("\t.pushsection .rodata.sharebuf_g2_late,\"a\",%progbits\n"
        "\t.align 2\n"
        "\t.type sbG1Calls, %object\n"
        "sbG1Calls:\n"
        "\t.word shareTouchBind\n"
        "\t.word shareLoad\n"
        "\t.word sbFind\n"
        "\t.size sbG1Calls, 12\n"
        "\t.popsection\n");
extern const uintptr_t sbG1Calls[3] __asm__("sbG1Calls");
#define SB_G1_TOUCH_BIND ((bool (*)(CtrRenderer*, CtrSurface*)) sbG1Calls[0])
#define SB_G1_LOAD ((void (*)(CtrRenderer*)) sbG1Calls[1])
#define SB_G1_FIND ((int32_t (*)(CtrRenderer*, int32_t)) sbG1Calls[2])

static inline __attribute__((always_inline)) bool sbOverlaps(const SbDirty* d, uintptr_t at, uint32_t bytes) {
    return d->state != SB_D_NONE && at + bytes > d->at && d->at + d->bytes > at;
}

// Another renderer, or the frame count gone back (as G1's sbFrame starts a session): nothing is known.
static SB2_TEXT void sbgSync(CtrRenderer* r) {
    if (sbg.r != r || sbg.frame > r->frame) {
        sbg.r = r;
        memset(sbg.d, 0, sizeof(sbg.d));
    }
    sbg.frame = r->frame;
}

// Every slot over [at, at + bytes) forgets what it knew: anything may be there now.
static SB2_TEXT void sbForget(uintptr_t at, uint32_t bytes) {
    for (uint32_t i = 0; SB_SLOTS > i; i++) {
        if (sbOverlaps(&sbg.d[i], at, bytes)) sbg.d[i].state = SB_D_NONE;
    }
}

static SB2_TEXT void sbForgetTarget(const C3D_RenderTarget* t) {
    if (t != nullptr) sbForget((uintptr_t) t->frameBuf.colorBuf, (uint32_t) t->frameBuf.width * t->frameBuf.height * 4u);
}

// An OPEN slot's rows, from the vertices drawn since its clear.
static SB2_TEXT void sbClose(CtrRenderer* r, SbDirty* d) {
    d->state = SB_D_NONE;
    if (r->frame != d->frame || d->vStart > r->vertexCount || d->uStart > r->vertexUsed) return;
    uint32_t n = r->vertexCount - d->vStart;
    if (n != r->vertexUsed - d->uStart) return;
    if (n == 0) {
        d->state = SB_D_EMPTY;
        return;
    }
    const C3D_FVec* u = &C3D_FVUnif[GPU_VERTEX_SHADER][r->projectionLoc];
    uint32_t mark;
    memcpy(&mark, &r->uploadedOwn.m[0], 4);
    if (n > SB_BOX_VERTICES || !r->gameProjection || mark != SB_OWN_MARK || r->skip.max != 0 || r->skip.active || r->skip.wrapped ||
        memcmp(&r->viewport, &d->view, sizeof(d->view)) != 0 || memcmp(&u[1], &d->u1, sizeof(d->u1)) != 0 ||
        memcmp(&u[3], &d->u3, sizeof(d->u3)) != 0)
        return;
    float h = (float) d->height, half = 0.5f * (float) d->vh, mid = (float) d->vy + half, lo = 1.0e30f, hi = -1.0e30f;
    for (uint32_t i = 0; n > i; i++) {
        const CtrVertex* v = &r->vertices[d->vStart + i];
        float cy = d->u1.x * v->x + d->u1.y * v->y + d->u1.z * v->z + d->u1.w;
        float cw = d->u3.x * v->x + d->u3.y * v->y + d->u3.z * v->z + d->u3.w;
        if (!(cw > 0.0f)) return;
        // Window row y is memory row height - 1 - y (the PICA counts rows from the buffer's far end).
        float c = h - (mid + half * (cy / cw));
        if (!(c > -1.0e6f && 1.0e6f > c)) return;
        if (lo > c) lo = c;
        if (c > hi) hi = c;
    }
    // Truncated, two rows out: at least floor(lo) - 1 and ceil(hi) + 1, a row more each side than the pixels reach.
    int32_t row0 = (int32_t) lo - 2, row1 = (int32_t) hi + 2, last = (int32_t) d->height - 1;
    if (0 > row1 || row0 > last) {
        d->state = SB_D_EMPTY;
        return;
    }
    d->row0 = (int16_t) (0 > row0 ? 0 : row0);
    d->row1 = (int16_t) (row1 > last ? last : row1);
    d->state = SB_D_BOX;
}

// A binding ends, or a clear comes: OPEN slots close, and pending ones stay only if nothing has drawn since.
static SB2_TEXT void sbSettle(CtrRenderer* r) {
    for (uint32_t i = 0; SB_SLOTS > i; i++) {
        SbDirty* d = &sbg.d[i];
        if (d->state == SB_D_OPEN) sbClose(r, d);
        if (d->pending && (r->frame != d->frame || r->vertexCount != d->vStart || r->vertexUsed != d->uStart)) d->state = SB_D_NONE;
        d->pending = false;
    }
}

#ifdef CTRPORT_SHAREBUF_FULLTEST
// The memory of [at, at + bytes) outside [from, to), once the GPU has run everything so far, is all zero.
static SB2_TEXT void sbCheck(CtrRenderer* r, uintptr_t at, uint32_t bytes, uint32_t width, uint32_t from, uint32_t to) {
    SB_CALL(flushBatch)(r);
    CtrSuspendedFrame f;
    SB_CALL(endFrameEarly)(r, &f);
    SB_CALL(resumeFrame)(r, &f);
    CtrGpu_waitIdle();
    GSPGPU_InvalidateDataCache((const void*) at, bytes);
    const uint32_t* w = (const uint32_t*) at;
    uint32_t bad = bytes;
    for (uint32_t o = 0; bytes > o; o += 4) {
        if (o == from && to > from) {
            o = to - 4;
            continue;
        }
        if (w[o / 4] != 0) {
            bad = o;
            break;
        }
    }
    sbg.checks++;
    if (bad == bytes) return;
    sbg.fails++;
    uint32_t band = width * 32u;
    if (8 >= sbg.fails) {
        logError(sbLogCheck, (unsigned long) r->frame, (unsigned long) at, (int) (bad / band * 8u), (int) (bad / band * 8u + 7u),
                 (int) (from / band * 8u), (int) (to / band * 8u) - 1, (unsigned long) sbg.fails, (unsigned long) sbg.checks);
    }
}
#endif

// g2log (change titancpu, 11-03): shareBindG2 called logInfo at every G1 session's end with any clear counted, so a
// scene with spilled surfaces and no session open (Titan, Knight, Flowery) logged a line for every bound whole clear,
// about two a frame (1-3 ms each on the New 3DS game thread). shareBindG2 now calls this instead of logInfo, with the
// same arguments, so its code keeps its size and every G2, flowerhw stfix and knightgpu dspe address stays: the line
// is logged only when a clear was left out or cut (something saved), and once a room visit. Its code and state have
// sections of their own, after knightgpu dspe's text and flowerhw stfix's statics (late_reserve.ld).
static __attribute__((section(".bss_titancpu_g2log,\"aw\",%nobits @"))) struct { // nobits, as flowerhw stfix's
    bool logged;  // a line logged since the renderer's first frame
    int32_t room; // the room it was logged in
} sbgLog;

static __attribute__((noipa, used, noinline, section(".text_titancpu_g2log"))) void sbLogClearsRoom(const char* fmt, ...) {
    // sbLogClears' five numbers, passed on to logInfo itself (vLogInfo would be linked in only for this, moving .text).
    unsigned long a[5];
    va_list va;
    va_start(va, fmt);
    for (uint32_t i = 0; 5 > i; i++) a[i] = va_arg(va, unsigned long);
    va_end(va);
    int32_t room = sbg.r != nullptr && sbg.r->base.runner != nullptr ? sbg.r->base.runner->currentRoomIndex : -1;
    if (a[0] + a[1] == 0 || (sbgLog.logged && sbgLog.room == room)) return;
    sbgLog.logged = true;
    sbgLog.room = room;
    logInfo(fmt, a[0], a[1], a[2], a[3], a[4]);
}

// bindTarget's touch (G1's shareTouchBind after G2's part). It touches before it switches, so the binding before
// ends here; after it, any slot over the new target's memory is pending. G1's session over (its done line logged:
// no transient left), G2's counters are logged and start again.
static SB2_TEXT bool shareBindG2(CtrRenderer* r, CtrSurface* s) {
    sbgSync(r);
    sbSettle(r);
    bool ok = SB_G1_TOUCH_BIND(r, s);
    const C3D_RenderTarget* t = ok ? s->target : nullptr;
    if (t != nullptr) {
        uintptr_t at = (uintptr_t) t->frameBuf.colorBuf;
        uint32_t bytes = (uint32_t) t->frameBuf.width * t->frameBuf.height * 4u;
        for (uint32_t i = 0; SB_SLOTS > i; i++) {
            SbDirty* d = &sbg.d[i];
            if (!sbOverlaps(d, at, bytes)) continue;
            d->pending = true;
            d->frame = r->frame;
            d->vStart = r->vertexCount;
            d->uStart = r->vertexUsed;
        }
    }
    if (sb.n == 0 && sbg.clearSkip + sbg.clearCut + sbg.clearWhole != 0) {
        sbLogClearsRoom(sbLogClears, (unsigned long) sbg.clearSkip, (unsigned long) sbg.clearCut, (unsigned long) sbg.cutRows,
                (unsigned long) sbg.ofRows, (unsigned long) sbg.clearWhole);
#ifdef CTRPORT_SHAREBUF_FULLTEST
        logInfo(sbLogChecks, (unsigned long) sbg.checks, (unsigned long) sbg.fails);
#endif
        sbg.clearSkip = sbg.clearCut = sbg.cutRows = sbg.ofRows = sbg.clearWhole = 0;
    }
    return ok;
}

// loadSpill (G1's shareLoad after G2's part): the load writes the bound target.
static SB2_TEXT void shareLoadG2(CtrRenderer* r) {
    sbForgetTarget(r->boundTarget);
    SB_G1_LOAD(r);
}

// A scratch's target goes (processDeferredFrees, releaseIdleScratches): its memory may be anything's next.
static SB2_TEXT void shareTargetDelete(C3D_RenderTarget* t) {
    sbForgetTarget(t);
    C3D_RenderTargetDelete(t);
}

// clearBoundTarget's memory fill (C3D_RenderTargetClear: C3D_FrameBufClear, through knightgpu's
// __wrap_C3D_FrameBufClear), cut to the rows its slot says may be nonzero. See sbClose.
static SB2_TEXT void shareClear(C3D_FrameBuf* fb, C3D_ClearBits bits, u32 color, u32 depth) {
    CtrRenderer* r = sb.r;
    uintptr_t at = (uintptr_t) fb->colorBuf;
    uint32_t bytes = (uint32_t) fb->width * fb->height * 4u;
    // clearBoundTarget's whole clear of the bound target, colour only: RGBA8, four bytes a pixel, as below.
    bool zero = r != nullptr && r->boundTarget != nullptr && &r->boundTarget->frameBuf == fb && bits == C3D_CLEAR_COLOR &&
                fb->colorFmt == GPU_RB_RGBA8 && color == 0;
    SbDirty* d = nullptr;
    if (zero) {
        sbgSync(r);
        sbSettle(r);
        for (uint32_t i = 0; SB_SLOTS > i && d == nullptr; i++) {
            if (sbg.d[i].state != SB_D_NONE && sbg.d[i].at == at && sbg.d[i].bytes == bytes && sbg.d[i].width == fb->width) d = &sbg.d[i];
        }
    }
    // The bytes [from, to) the fill has to cover: the 8-row tile bands over the slot's rows (a band of a tiled RGBA8
    // buffer is width * 32 bytes, rows counted from the buffer's start).
    uint32_t band = (uint32_t) fb->width * 32u, from = 0, to = bytes;
    if (d != nullptr && d->state == SB_D_EMPTY) {
        to = 0;
    } else if (d != nullptr && d->state == SB_D_BOX) {
        from = (uint32_t) (d->row0 >> 3) * band;
        to = ((uint32_t) (d->row1 >> 3) + 1u) * band;
        if (to > bytes) to = bytes;
    }
    // Every slot over this memory: the one opened below is the clear's.
    sbForget(at, bytes);
    if (d != nullptr || (zero && 0 <= r->spillBound)) {
        if (to == from) {
            sbg.clearSkip++;
        } else if (to - from == bytes) {
            sbg.clearWhole++;
        } else {
            sbg.clearCut++;
            sbg.cutRows += (to - from) / ((uint32_t) fb->width * 4u);
            sbg.ofRows += fb->height;
        }
    }
#ifdef CTRPORT_SHAREBUF_FULLTEST
    if (d != nullptr) sbCheck(r, at, bytes, fb->width, from, to);
    from = 0;
    to = bytes;
#endif
    if (to - from == bytes) {
        C3D_FrameBufClear(fb, bits, color, depth);
    } else if (to > from) {
        GX_MemoryFill((u32*) (at + from), 0, (u32*) (at + to), GX_FILL_TRIGGER | GX_FILL_32BIT_DEPTH, nullptr, 0, nullptr, 0);
    }
    if (!zero) return;
    // A transient's binding (its own surface, the game's projection): what it draws from now on is the slot's.
    int32_t id = r->boundSurface;
    if (sb.disabled || 0 > id || id != r->spillBound || sb.n == 0 || 0 > SB_G1_FIND(r, id) || !r->gameProjection) return;
    const CtrSurface* s = &r->surfaces[id];
    if (s->windowed || (r->base.runner != nullptr && id == r->base.runner->applicationSurfaceId)) return;
#if defined(ENABLE_WAD17) && defined(CTRPORT_KNIGHTGPU_LENDER)
    // VRAM knightgpu lends is its to manage (its whole clears give it back).
    if (kg.base != nullptr && at + bytes > (uintptr_t) kg.base && (uintptr_t) kg.base + (KG_SLOTS + 1u) * kg.slotSize > at) return;
#endif
    for (uint32_t i = 0; SB_SLOTS > i && d == nullptr; i++) {
        if (sbg.d[i].state == SB_D_NONE) d = &sbg.d[i];
    }
    if (d == nullptr) return;
    // The GPU viewport's rows, as applyEyeViewport sets them for this target (no window, not both eyes).
    CtrRect v = r->viewport;
    if (s->shift > 0) {
        int32_t k = s->shift, round = (1 << k) - 1;
        v.y >>= k;
        v.h = (v.h + round) >> k;
    }
    v.y = (int32_t) fb->height - v.y - v.h;
    if (0 > v.y) {
        v.h += v.y;
        v.y = 0;
    }
    if (1 > v.h) v.h = 1;
    const C3D_FVec* u = &C3D_FVUnif[GPU_VERTEX_SHADER][r->projectionLoc];
    *d = (SbDirty) { .at = at, .bytes = bytes, .width = fb->width, .height = fb->height, .state = SB_D_OPEN, .frame = r->frame,
                     .vStart = r->vertexCount, .uStart = r->vertexUsed, .view = r->viewport, .vy = v.y, .vh = v.h, .u1 = u[1], .u3 = u[3] };
    uint32_t mark = SB_OWN_MARK;
    memcpy(&r->uploadedOwn.m[0], &mark, 4);
}
