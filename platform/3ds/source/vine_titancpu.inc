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
 * its quad holds, with the table's drawSurface ctrDrawSurface itself (TC_INNER: O9's check stub for it where O9 is on),
 * or natsurf6's passing the draw straight on to it (Titan_ns6PassesDraw), and nothing held by O9 (tcLazyHeld). A quad
 * onto the open batch (tcEmitQuad) changes none of what those tests read, so the session's next call of the same
 * surface and alpha does what the fast way does after its tests: the stamps, the corners, the texture coordinates (the
 * same divisions, of the texture size taken when armed), and tcEmitQuad. It goes the whole way again (and disarms)
 * when tcEmitQuad can't, since emitQuad may flush, split or move surfaces, and when anything it can see differs from
 * when it last drew: the renderer, the frame, a split, the vertices or the batch. A profile build
 * (CTRPORT_RENDER_TIMING) always goes the whole way. */
bool Titan_ns6PassesDraw(const Renderer* renderer, int32_t id, const void* inner);
/* The renderer's own drawSurface as its table names it (TC_INNER), and whether knightgpu O9 holds blend or fog calls
 * (tcLazyHeld). With O9 (CTRPORT_KNIGHTGPU_LAZY_ON, DELTARUNE New) the table's entry is kglC_ctrDrawSurface, the check
 * stub that settles held calls (kglSettle) and then runs ctrDrawSurface; compared with ctrDrawSurface itself, the
 * sessions below never armed there (knightgpu dspe's counters, 11-02). A session's quad skips the stub, which does
 * nothing when nothing is held: kglState.r, read by its assembler name (no C reference, so ctr_renderer.c's statics
 * keep their order), is 0 then. Nothing is held when a session arms (its call has just gone through the stub, which
 * settles, and ctrDrawSurface holds nothing), and between two of its calls the region reaches no renderer entry; the
 * test makes a repeat go the whole way anyway if something was. Elsewhere both are as before. */
#ifdef CTRPORT_KNIGHTGPU_LAZY_ON
#define TC_INNER() ({ const void* tcInner = (const void*) KGL_CHK(ctrDrawSurface); __asm__("" : "+r"(tcInner)); tcInner; })
static inline __attribute__((always_inline)) bool tcLazyHeld(void) {
    uint32_t held;
    __asm__ volatile("ldr %0, 1f\n\tldr %0, [%0]\n\tb 2f\n\t.balign 4\n1:\t.word kglState\n2:" : "=r"(held) : : "memory");
    return held != 0;
}
#else
#define TC_INNER() ((const void*) VR_CALL(ctrDrawSurface))
#define tcLazyHeld() false
#endif
#define TC_TAIL __attribute__((noinline, used, optimize("Os", "inline-functions", "no-tree-switch-conversion"), section(".text.titancpu_tail")))
/* A repeat whose colour has alpha 0 under blending that keeps the target (transparentDrawIsNoop) is what the whole way
 * does with it: Titan_wrap_drawSurfaceImpl's fast way stamps, tcEmitQuad declines (alpha 0), and emitQuad returns at
 * that same test with nothing changed. The session then stays armed (tcTransparentNoop) instead of going the whole way
 * every other call, as the Roaring Knight's ball strips at darkness 0 did (knightgpu dspe's counters, 11-02). The
 * static is reached by its assembler name, so no call-graph edge moves ctr_renderer.c's functions. */
static inline __attribute__((always_inline)) bool tcTransparentNoop(const CtrRenderer* r, CtrColor c) {
    extern __typeof__(transparentDrawIsNoop) tcTransparentDrawIsNoop __asm__("transparentDrawIsNoop");
    return c.a == 0 && tcTransparentDrawIsNoop(r);
}
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

/* 75zq's Titan_stripDraw, kept as it was, in its place: in knightgpu dspe session builds Titan_scalarSurfacePart
 * calls Titan_stripDrawDspe (at the dspe tail), which hands over to it outside the Knight and Titan rooms; it stays so
 * that no later late function moves (review decision, 11-03). */
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

#ifdef CTRPORT_KNIGHTGPU_DSPE_SESSION
/* knightgpu dspe (DELTARUNE New): Titan_stripDraw for draw_surface_part_ext (Knight_scalarSurfacePartExt,
 * engine/src/vm_builtins.c's end, with a session: tools/aot/typed.py gives one to a region whose builtin calls are
 * such draws and pure queries, as the Roaring Knight's 480 one-row strips of its ball surface). The same tests and the
 * same work as Titan_stripDraw, with the call's scale and colour: the whole way is renderer->vtable->drawSurface(renderer,
 * id, left, top, w, h, x, y, xscale, yscale, 0, color, alpha), and a repeat (same surface, colour and alpha) does what
 * Titan_wrap_drawSurfaceImpl's fast way does after its tests, with the corners it computes from the scale. Named outside
 * .text.* and last in late_reserve.ld, so no earlier late function moves. */
typedef struct __attribute__((may_alias)) {
    CtrRenderer* r; // nullptr: not armed
    uint32_t frame, splits, vertexEnd, batchStart, alpha, color;
    int32_t id;
    float tw, th;
    CtrColor c;
} KnSession;
_Static_assert(sizeof(KnSession) <= TC_SESSION_WORDS * sizeof(uint32_t) && _Alignof(KnSession) <= _Alignof(uint32_t), "typed.py's tss_");

// makeColor, inlined here: a second out-of-line caller would make GCC emit makeColor outside the late sections that
// vine_extract.py keeps from this pass.
static inline __attribute__((always_inline)) CtrColor knMakeColor(uint32_t bgr, float alpha) {
    CtrColor c;
    c.r = (uint8_t) BGR_R(bgr);
    c.g = (uint8_t) BGR_G(bgr);
    c.b = (uint8_t) BGR_B(bgr);
    if (0.0f >= alpha) c.a = 0;
    else if (alpha >= 1.0f) c.a = 255;
    else c.a = (uint8_t) (alpha * 255.0f + 0.5f);
    return c;
}

/* The sessions' rooms (review decision 11-03, flower ABBA dspzq2: the B'' sessions are kept only where they were measured to
 * pay): the Roaring Knight's chapter 3 arena and Titan's chapter 4 fight. Elsewhere Knight_stripDrawExt draws the whole
 * way, as Knight_scalarSurfacePartExt does without a session, and Titan_stripDrawDspe is 75zq's Titan_stripDraw. The
 * rooms are known by the FNV-1a 32 hash of their names (no game names in the binary or the source; one match each in
 * every chapter's room list of DELTARUNE 0.0.253, none elsewhere; tools/aot/check_dspe_gate.py checks them at build).
 * The verdict is kept in the region's own session (its last word, which neither session layout uses: 0 not yet, 1 off,
 * 2 on), so it is looked up once per region entry and cannot outlive the room or the chapter (c26rev R145 F2: a cache
 * keyed by Room* could outlive a chapter's room table and match a later chapter's room at the same address). */
#define KN_GATE_WORD (TC_SESSION_WORDS - 1)
_Static_assert(sizeof(TcSession) <= KN_GATE_WORD * sizeof(uint32_t) && sizeof(KnSession) <= KN_GATE_WORD * sizeof(uint32_t),
               "knGate's word is past both sessions");

__attribute__((noinline, optimize("Os"), section(".text_knightgpu_dspe")))
static bool knGate(const Renderer* renderer, uint32_t* session) {
    uint32_t verdict = session[KN_GATE_WORD];
    if (verdict == 0) {
        const Room* room = renderer->runner->currentRoom;
        uint32_t hash = 2166136261u; // no "" for a missing room: vine_extract.py keeps no string constants
        if (room != nullptr) {
            for (const char* c = room->name; *c != 0; c++) hash = (hash ^ (uint8_t) *c) * 16777619u;
        }
        bool knGateOn = hash == 0x182A880Bu || hash == 0x12FF5524u;
        verdict = knGateOn ? 2u : 1u;
        session[KN_GATE_WORD] = verdict;
    }
    return verdict == 2u;
}

__attribute__((noinline, used, optimize("Os", "inline-functions", "no-tree-switch-conversion"), section(".text_knightgpu_dspe")))
void Knight_stripDrawExt(Renderer* renderer, uint32_t* session, int32_t surfaceId, int32_t left, int32_t top, int32_t w, int32_t h, float x,
                         float y, float xscale, float yscale, uint32_t color, float alpha) {
    if (!knGate(renderer, session)) {
        renderer->vtable->drawSurface(renderer, surfaceId, left, top, w, h, x, y, xscale, yscale, 0.0f, color, alpha);
        return;
    }
    CtrRenderer* r = (CtrRenderer*) renderer;
    KnSession* q = (KnSession*) session;
#ifndef CTRPORT_RENDER_TIMING
    if (q->r == r && q->id == surfaceId && q->alpha == tcBits(alpha) && q->color == color && 0 <= w && q->frame == r->frame &&
        q->splits == r->frameStats.splits && q->vertexEnd == r->vertexCount && q->batchStart == r->batchStart && !tcLazyHeld()) {
        CtrSurface* s = &r->surfaces[surfaceId];
        float px[4], py[4];
        px[0] = px[3] = x;
        px[1] = px[2] = xscale * (float) w + x;
        py[0] = py[1] = y;
        py[2] = py[3] = yscale * (float) h + y;
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
        if (tcTransparentNoop(r, q->c)) return;
        q->r = nullptr;
        VR_CALL(emitQuad)(r, tex, px, py, u0, v0, u1, v1, cs);
        return;
    }
#endif
    renderer->vtable->drawSurface(renderer, surfaceId, left, top, w, h, x, y, xscale, yscale, 0.0f, color, alpha);
    q->r = nullptr;
#ifndef CTRPORT_RENDER_TIMING
    const void* inner = TC_INNER();
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
    q->color = color;
    q->id = surfaceId;
    q->tw = (float) (s->tex.width << s->shift);
    q->th = (float) (s->tex.height << s->shift);
    q->c = knMakeColor(color, alpha);
#endif
}
/* Titan_stripDraw as knightgpu dspe has it (O9's check stub as the inner draw, nothing held by O9, a transparent
 * repeat staying armed: the notes above TC_TAIL), for Titan_scalarSurfacePart in dspe session builds: in the sessions'
 * rooms, Knight_stripDrawExt at scale 1 and colour white, the call draw_surface_part makes (the same tests and the same
 * work: 1.0f * w is w exactly, and knMakeColor(0xFFFFFFFF, alpha) is Titan_stripDraw's colour); elsewhere 75zq's
 * Titan_stripDraw. At the dspe tail under its own name, so 75zq's Titan_stripDraw keeps its size and no later late
 * function moves (review decision, 11-03). One body for both draws, so B'' costs DELTARUNE New's late text less. */
__attribute__((noinline, used, optimize("Os"), section(".text_knightgpu_dspe")))
void Titan_stripDrawDspe(Renderer* renderer, uint32_t* session, int32_t surfaceId, int32_t left, int32_t top, int32_t w, int32_t h,
                         float x, float y, float alpha) {
    if (!knGate(renderer, session)) {
        Titan_stripDraw(renderer, session, surfaceId, left, top, w, h, x, y, alpha);
        return;
    }
    Knight_stripDrawExt(renderer, session, surfaceId, left, top, w, h, x, y, 1.0f, 1.0f, 0xFFFFFFFFu, alpha);
}
#endif
