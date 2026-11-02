/* Lazy surface hand-off splits on DELTARUNE New 3DS (titancpu L1, late code only).
 *
 * bindTarget split the frame (splitFrame: flush, submit the command list so far, re-emit all GPU state) every time
 * it left a surface that had been drawn on, so that whatever sampled the surface later saw its pixels. Sampling
 * already does that itself: surfaceTexture splits when the surface it hands out was drawn on since the last split
 * and isn't the one bound. The Titan's dark shapes each redraw a surface and then sample it 46 times a frame, so
 * every shape paid for two splits where one is enough (CHAPTER 4's Titan fights: about 20 hand-offs a frame).
 *
 * tools/analysis/vine_old_parent.py routes, without changing any original body:
 *   - bindTarget's hand-off splitFrame call (its first; the second, in the inlined flushPendingStoresSharing, stays)
 *     to Titan_leaveSplit, which skips the split when leaving a plain surface. A surface that is spilled (shares a
 *     scratch target), windowed, recorded, has draws put off (lazy) or sampled by draws put off (lazyRefs), or has
 *     frame skip's recordings, still splits, as does every hand-off while frame skip's wrappers are in.
 *   - every surfaceTexture call to Titan_wrap_surfaceTexture, which notes that the surface was sampled since the
 *     last split (a stamp of the frame and its split count, taken after any split surfaceTexture makes; a split
 *     always counts up, so a stale stamp can only match by chance, which costs a split and is never wrong). The
 *     bound surface itself (present samples the application surface before binding the screen) splits first when
 *     drawn on since the last split, where the hand-off split used to fall.
 *   - every clearBoundTarget call to Titan_wrap_clearBoundTarget. A whole clear is a GX memory fill, which the GX
 *     queue runs ahead of every command not yet split off. Without the hand-off split, draws onto the surface from
 *     an earlier binding, or draws sampling it, can still be unsubmitted, so the frame is split first when either
 *     is the case (spilled, windowed or skip-recorded surfaces split whenever anything is unsubmitted).
 * Everything else that reads a surface's memory outside the command list already submits first: GX copies split
 * (or check CtrRenderer.drawnSinceSplit, which still says anything at all is unsubmitted), CPU reads and synchronous
 * copies suspend or end the frame, and present samples the application surface through surfaceTexture. */
#define TC_CODE __attribute__((noinline, used, optimize("Os", "inline-functions", "no-tree-switch-conversion"), section(".text.titancpu_late")))
#define TC_BSS  __attribute__((section(".bss.titancpu_late")))
#define TC_STAMPS 256 // surfaces with a sample stamp; any other surface counts as sampled

static uint32_t tcStamp[TC_STAMPS] TC_BSS;

// Nonzero, and the same until the frame is next split or ended.
#define TC_NOW(r) ((((uint32_t) (r)->frame) << 12) ^ (uint32_t) (r)->frameStats.splits ^ 0x80000000u)

static inline __attribute__((always_inline)) bool tcPlain(const CtrRenderer* r, const CtrSurface* s) {
    return !r->skip.wrapped && !s->spilled && !s->windowed && !s->recorded && s->skipRec == nullptr && s->skipRealRefs == 0 &&
           s->lazy == nullptr && s->lazyRefs == 0;
}

TC_CODE void Titan_leaveSplit(CtrRenderer* r) {
    // bindTarget calls this leaving a drawn-on surface (0 <= boundSurface): split unless the surface is plain.
    const CtrSurface* left = (uint32_t) r->boundSurface < r->surfaceCount ? &r->surfaces[r->boundSurface] : nullptr;
    if (left == nullptr || !left->used || !tcPlain(r, left)) VR_CALL(splitFrame)(r);
}

TC_CODE C3D_Tex* Titan_wrap_surfaceTexture(CtrRenderer* r, int32_t id) {
    // The bound surface, sampled (present, a copy out of it) and then left: the hand-off split used to come before
    // the draws that sample it, so it comes here instead. surfaceTexture splits for any other surface itself.
    if (id == r->boundSurface && (uint32_t) id < r->surfaceCount && r->inFrame && r->surfaces[id].drawnSinceSplit &&
        tcPlain(r, &r->surfaces[id]))
        VR_CALL(splitFrame)(r);
#ifdef CTRPORT_FLOWERGPU_VRAMPROBE
    C3D_Tex* tex = Vine_wrap_surfaceTexture(r, id);
#else
    C3D_Tex* tex = VR_CALL(surfaceTexture)(r, id);
#endif
    // Stamped after any split surfaceTexture made: the draws that sample it come after that split.
    if ((uint32_t) id < TC_STAMPS) tcStamp[id] = TC_NOW(r);
    return tex;
}

TC_CODE void Titan_wrap_clearBoundTarget(CtrRenderer* r, CtrColor color, int32_t targetW, int32_t targetH) {
    // Only the memory fill (clearBoundTarget's whole clear) runs outside the command list.
    int32_t id = r->boundSurface;
    if (r->inFrame && r->boundTarget != nullptr && !r->quadClears && r->drawnSinceSplit && (uint32_t) id < r->surfaceCount &&
        r->colorWrite[0] && r->colorWrite[1] && r->colorWrite[2] && r->colorWrite[3]) {
        const CtrSurface* s = &r->surfaces[id];
        bool sampled = (uint32_t) id >= TC_STAMPS || tcStamp[id] == TC_NOW(r);
        if (s->drawnSinceSplit || sampled || !tcPlain(r, s)) VR_CALL(splitFrame)(r);
    }
    Vine_wrap_clearBoundTarget(r, color, targetW, targetH);
}

/* titancpu L2: a surface drawn as it is, again in a frame (draw_surface_part strips: the Titan's dark shapes cut a
 * 46-row surface into 46 one-row strips, the Roaring Knight a surface into 480), skips the way down to emitQuad.
 * Every drawSurfaceImpl call is routed here. The fast way is taken only where each step it skips is known to do
 * nothing but what is done here, and every other draw goes the whole way (Vine_wrap_drawSurfaceImpl):
 *   - Vine_wrap_drawSurfaceImpl: nothing, with no face sampled outside (vrSampleFace 0) and no draws put off on the
 *     surface (lazy, which also covers its 240x720 faces);
 *   - drawSurfaceImpl: its own fast way (seen in view this frame, nothing put off, not recorded or windowed, a
 *     rendered target, no palette or shader effect taking the draw elsewhere), unrotated, with a source rectangle,
 *     not the bound surface; no shader at all (shaderFx none, no palette), so a shader always takes the long way;
 *   - surfaceTexture (through Titan_wrap_surfaceTexture): no frame skip recording, nothing to clear, no split due
 *     (not drawn on since the last split), not spilled; touchSurface only stamps the frame (not parked, not the
 *     surface being parked).
 * A quad onto the open batch of the same texture is then emitted here (tcEmitQuad); any other goes through emitQuad
 * and reserveBatch as they are. A profile build (CTRPORT_RENDER_TIMING) always goes the whole way. */
/* emitQuad's quad onto an open batch of the same texture (the second strip of a surface on): what emitQuad,
 * Vine_wrap_reserveBatch and reserveBatch do then, done here; false (nothing changed) for anything else, which then
 * goes through emitQuad. The callers guarantee shaderFx none (no castle fade) and a surface texture (not white). */
static inline __attribute__((always_inline)) bool tcEmitQuad(CtrRenderer* r, C3D_Tex* tex, const float* px, const float* py, float u0, float v0, float u1,
                                                               float v1, const CtrColor* c) {
    if ((c[0].a | c[1].a | c[2].a | c[3].a) == 0 || r->dlg.armed) return false; // emitQuad's no-op test; recordingSurface
    bool multiSafe = v0 >= MULTI_MIN_V && v1 >= MULTI_MIN_V && 1.0f >= v0 && 1.0f >= v1;
    const VrRing* g = &vrRing;
    if (g->frame != r->frame || g->r != r) return false; // Vine_wrap_reserveBatch's first reserve of a frame
    int32_t b = r->boundSurface;
    if (r->addHold.mode == ADD_HOLD_HELD || !r->inFrame || r->boundTarget == nullptr || r->spillLoadPending) return false;
    if (0 <= b && (r->surfaces[b].skipRec != nullptr || r->surfaces[b].lazy != nullptr)) return false;
    if (r->vertexCount + 6 > r->vertexLimit) return false; // makeVertexRoom's
    if (r->batchTexCount != 1 || tex != r->batchTex || r->palNextB != r->batchTexB) return false; // batchUnitFor: unit 0 only
    if (r->vertexCount == r->batchStart) return false; // a batch's first quad sets its layout
    if (!multiSafe) r->batchMultiOk = false;
    uint32_t count = r->batchQuads ? 4u : 6u;
    CtrVertex* v = &r->vertices[r->vertexCount];
    r->vertexCount += count;
    r->vertexUsed += count;
    r->boundTargetDrawn = true;
    r->clearedTarget = nullptr;
    r->drawnSinceSplit = true;
    if (0 <= b) {
        r->surfaces[b].drawnSinceSplit = true;
        r->surfaces[b].version = ++r->contentSerial;
    }
    if (0 <= r->spillBound) r->spillDirty = true;
    uint32_t unit = 0;
    r->vertexZ = depthDisparity(r) + MULTI_UNIT_Z * (float) unit;
    float z = r->vertexZ;
    setVertex(&v[0], px[0], py[0], z, u0, v0, c[0]);
    setVertex(&v[1], px[1], py[1], z, u1, v0, c[1]);
    setVertex(&v[2], px[2], py[2], z, u1, v1, c[2]);
    if (r->batchQuads) {
        setVertex(&v[3], px[3], py[3], z, u0, v1, c[3]);
        return true;
    }
    setVertex(&v[3], px[0], py[0], z, u0, v0, c[0]);
    setVertex(&v[4], px[2], py[2], z, u1, v1, c[2]);
    setVertex(&v[5], px[3], py[3], z, u0, v1, c[3]);
    return true;
}

TC_CODE void Titan_wrap_drawSurfaceImpl(CtrRenderer* r, int32_t surfaceId, int32_t srcLeft, int32_t srcTop, int32_t srcWidth, int32_t srcHeight,
                                        float x, float y, float xscale, float yscale, float angleDeg, const CtrColor* cs) {
#ifndef CTRPORT_RENDER_TIMING
    if (angleDeg == 0.0f && 0 <= srcWidth && vrSampleFace == 0 && (uint32_t) surfaceId < r->surfaceCount && surfaceId != r->boundSurface &&
        r->boundTarget != nullptr && r->shaderFx == SHADER_FX_NONE && r->palKind == PAL_NONE && !r->skip.wrapped) {
        CtrSurface* s = &r->surfaces[surfaceId];
        if (s->used && s->seenFrame == r->frame && s->lazy == nullptr && !s->recorded && !s->windowed && s->skipRec == nullptr && !s->needsClear &&
            !s->drawnSinceSplit && !s->spilled && s->parked == nullptr && r->park.id != surfaceId && !surfaceFxDraw(r)) {
            float px[4], py[4];
            px[0] = px[3] = x;
            px[1] = px[2] = xscale * (float) srcWidth + x;
            py[0] = py[1] = y;
            py[2] = py[3] = yscale * (float) srcHeight + y;
            s->touchedFrame = r->frame;
            C3D_Tex* tex = &s->tex;
            if ((uint32_t) surfaceId < TC_STAMPS) tcStamp[surfaceId] = TC_NOW(r);
            float tw = (float) (tex->width << s->shift), th = (float) (tex->height << s->shift);
            float u0 = (float) srcLeft / tw, v0 = (float) srcTop / th, u1 = (float) (srcLeft + srcWidth) / tw, v1 = (float) (srcTop + srcHeight) / th;
            if (!tcEmitQuad(r, tex, px, py, u0, v0, u1, v1, cs)) VR_CALL(emitQuad)(r, tex, px, py, u0, v0, u1, v1, cs);
            return;
        }
    }
#endif
    Vine_wrap_drawSurfaceImpl(r, surfaceId, srcLeft, srcTop, srcWidth, srcHeight, x, y, xscale, yscale, angleDeg, cs);
}

/* titancpu lever 1: the repeats of a typed region's draw_surface_part (Titan_scalarSurfacePart, engine/src/vm_builtins.c,
 * with a session: tools/aot/typed.py gives one to a region whose only builtin calls are such draws, as the Titan's dark
 * shapes' 46 one-row strips of one surface; it is the region's own TC_SESSION_WORDS words, zero at the region's start).
 * Between two of the session's calls the region runs nothing but numeric code and its own draws, so nothing else
 * reaches the renderer. A call goes the whole way (renderer->vtable->drawSurface with xscale 1, yscale 1, angle 0 and
 * colour 0xFFFFFFFF) and then arms the session when every test that Titan_wrap_drawSurfaceImpl's fast way makes before
 * its quad holds, with the table's drawSurface ctrDrawSurface itself, or natsurf6's passing the draw straight on to it
 * (Titan_ns6PassesDraw). A quad onto the open batch (tcEmitQuad) changes none of what those tests read, so the
 * session's next call of the same surface and alpha does what the fast way does after its tests: the stamps, the
 * corners, the texture coordinates (the same divisions, of the texture size taken when armed), and tcEmitQuad. It goes
 * the whole way again (and disarms) when tcEmitQuad can't, since emitQuad may flush, split or move surfaces, and when
 * anything it can see differs from when it last drew: the renderer, the frame, a split, the vertices or the batch. A
 * profile build (CTRPORT_RENDER_TIMING) always goes the whole way. */
bool Titan_ns6PassesDraw(const Renderer* renderer, int32_t id, const void* inner);
#define TC_TAIL __attribute__((noinline, used, optimize("Os", "inline-functions", "no-tree-switch-conversion"), section(".text.titancpu_tail")))
#define TC_SESSION_WORDS 16 // typed.py's tss_
typedef struct __attribute__((may_alias)) {
    CtrRenderer* r; // nullptr: not armed
    uint32_t frame, splits, vertexEnd, batchStart, alpha;
    int32_t id;
    float tw, th;
    CtrColor c;
} TcSession;
_Static_assert(sizeof(TcSession) <= TC_SESSION_WORDS * sizeof(uint32_t) && _Alignof(TcSession) <= _Alignof(uint32_t), "typed.py's tss_");

static inline __attribute__((always_inline)) uint32_t tcBits(float f) {
    uint32_t u;
    memcpy(&u, &f, sizeof(u));
    return u;
}

TC_TAIL void Titan_stripDraw(Renderer* renderer, uint32_t* session, int32_t surfaceId, int32_t left, int32_t top, int32_t w, int32_t h, float x,
                             float y, float alpha) {
    CtrRenderer* r = (CtrRenderer*) renderer;
    TcSession* q = (TcSession*) session;
#ifndef CTRPORT_RENDER_TIMING
    if (q->r == r && q->id == surfaceId && q->alpha == tcBits(alpha) && 0 <= w && q->frame == r->frame && q->splits == r->frameStats.splits &&
        q->vertexEnd == r->vertexCount && q->batchStart == r->batchStart) {
        CtrSurface* s = &r->surfaces[surfaceId];
        float px[4], py[4];
        px[0] = px[3] = x;
        px[1] = px[2] = (float) w + x;
        py[0] = py[1] = y;
        py[2] = py[3] = (float) h + y;
        s->touchedFrame = r->frame;
        C3D_Tex* tex = &s->tex;
        if ((uint32_t) surfaceId < TC_STAMPS) tcStamp[surfaceId] = TC_NOW(r);
        float u0 = (float) left / q->tw, u1 = (float) (left + w) / q->tw;
        float v0 = (float) top / q->th, v1 = (float) (top + h) / q->th;
        CtrColor cs[4] = { q->c, q->c, q->c, q->c };
        if (tcEmitQuad(r, tex, px, py, u0, v0, u1, v1, cs)) {
            q->vertexEnd = r->vertexCount;
            return;
        }
        q->r = nullptr;
        VR_CALL(emitQuad)(r, tex, px, py, u0, v0, u1, v1, cs);
        return;
    }
#endif
    renderer->vtable->drawSurface(renderer, surfaceId, left, top, w, h, x, y, 1.0f, 1.0f, 0.0f, 0xFFFFFFFFu, alpha);
    q->r = nullptr;
#ifndef CTRPORT_RENDER_TIMING
    const void* inner = (const void*) VR_CALL(ctrDrawSurface);
    if (0 > w || vrSampleFace != 0 || (uint32_t) surfaceId >= r->surfaceCount || surfaceId == r->boundSurface || r->boundTarget == nullptr ||
        r->shaderFx != SHADER_FX_NONE || r->palKind != PAL_NONE || r->skip.wrapped)
        return;
    const CtrSurface* s = &r->surfaces[surfaceId];
    if (!s->used || s->seenFrame != r->frame || s->lazy != nullptr || s->recorded || s->windowed || s->skipRec != nullptr || s->needsClear ||
        s->drawnSinceSplit || s->spilled || s->parked != nullptr || r->park.id == surfaceId || surfaceFxDraw(r))
        return;
    if ((const void*) renderer->vtable->drawSurface != inner && !Titan_ns6PassesDraw(renderer, surfaceId, inner)) return;
    q->r = r;
    q->frame = r->frame;
    q->splits = r->frameStats.splits;
    q->vertexEnd = r->vertexCount;
    q->batchStart = r->batchStart;
    q->alpha = tcBits(alpha);
    q->id = surfaceId;
    q->tw = (float) (s->tex.width << s->shift);
    q->th = (float) (s->tex.height << s->shift);
    q->c = makeColor(0xFFFFFFFFu, alpha);
#endif
}
