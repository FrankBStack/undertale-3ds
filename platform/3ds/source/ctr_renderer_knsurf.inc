// An already-open surface strip run. The first strip takes the ordinary path;
// subsequent strips reuse only state that is still true in the live renderer.
// No snapshot survives a call, so setters, copies and target/surface changes
// need no invalidation hooks. The O9 checked draw entry must still settle first.
#ifdef CTRPORT_KNSURF
// Named outside .text.late.* because ctr_renderer.o has an earlier catch-all.
// The explicit final linker input puts this code after every existing hot body.
static __attribute__((noinline, noclone, section(".text.knsurf_late")))
void knsurfSurfaceImpl(CtrRenderer* r, int32_t surfaceId, int32_t srcLeft, int32_t srcTop, int32_t srcWidth, int32_t srcHeight,
                       float x, float y, float xscale, float yscale, float angleDeg, const CtrColor* cs) {
    if (angleDeg != 0.0f || srcHeight != 1 || srcWidth <= 0 || surfaceId < 0 || (uint32_t) surfaceId >= r->surfaceCount ||
        surfaceId == r->boundSurface || !r->inFrame || r->boundTarget == nullptr || r->dlg.armed || r->depth.active ||
        r->shaderFx != SHADER_FX_NONE || r->palKind != PAL_NONE || cs[0].a == 0 || r->addHold.mode == ADD_HOLD_HELD ||
        r->spillLoadPending || r->vertexCount + 6 > r->vertexLimit || !r->batchQuads || r->vertexCount == r->batchStart ||
        r->batchTexCount != 1 || r->palNextB != nullptr || r->batchTexB != nullptr) goto full;

    CtrSurface* s = &r->surfaces[surfaceId];
    // drawSurfaceImpl's seen-surface branch, then surfaceTexture with no work
    // remaining: touchSurface's frame write is already done and cancelPark is
    // a no-op. Leave unusual source regions to the original arithmetic too.
    if (!s->used || s->seenFrame != r->frame || s->touchedFrame != r->frame || s->lazy != nullptr || s->recorded || s->windowed ||
        s->skipRec != nullptr || s->parked != nullptr || s->needsClear || s->drawnSinceSplit || r->park.id == surfaceId ||
        srcLeft < 0 || srcLeft > s->width || srcWidth > s->width - srcLeft || srcTop < 0 || srcTop >= s->height) goto full;

    CtrSurface* bound = r->boundSurface >= 0 ? &r->surfaces[r->boundSurface] : nullptr;
    if (bound != nullptr && (bound->skipRec != nullptr || bound->lazy != nullptr)) goto full;
    C3D_Tex* tex = &s->tex;
    CtrScratch* sampled = nullptr;
    if (s->spilled) {
        CtrScratch* sc = &r->scratches[s->scratch];
        if (sc->pendingStore && sc->owner == surfaceId) {
            // Equal dimensions and byte size imply equal textureRows. Anything
            // needing a store/copy must take surfaceTexture's ordinary path.
            if (sc->target == nullptr || sc->tex.width != s->tex.width || sc->tex.height != s->tex.height ||
                sc->tex.size != s->tex.size) goto full;
            tex = &sc->tex;
            sampled = sc;
        }
    }
    if (tex != r->batchTex) goto full;

    // Identical operations and division (no reciprocal multiplication): native
    // surfaces express their source coordinates in logical, unshifted pixels.
    float x1 = xscale * (float) srcWidth + x, y1 = yscale * (float) srcHeight + y;
    float tw = (float) (tex->width << s->shift), th = (float) (tex->height << s->shift);
    float u0 = (float) srcLeft / tw, v0 = (float) srcTop / th;
    float u1 = (float) (srcLeft + srcWidth) / tw, v1 = (float) (srcTop + srcHeight) / th;
    bool multiSafe = v0 >= MULTI_MIN_V && v1 >= MULTI_MIN_V && 1.0f >= v0 && 1.0f >= v1;

    // surfaceTexture's remaining bookkeeping, then reserveBatch's successful
    // same-texture/unit-zero quad append. Keep every per-strip version update.
    if (sampled != nullptr) sampled->sampled = true;
    else if (s->spilled) s->storeQueued = false;
    if (!multiSafe) r->batchMultiOk = false;
    CtrVertex* v = &r->vertices[r->vertexCount];
    r->vertexCount += 4;
    r->vertexUsed += 4;
    r->boundTargetDrawn = true;
    r->clearedTarget = nullptr;
    r->drawnSinceSplit = true;
    if (bound != nullptr) {
        bound->drawnSinceSplit = true;
        bound->version = ++r->contentSerial;
    }
    if (r->spillBound >= 0) r->spillDirty = true;
    r->vertexZ = 0.0f; // no stereo disparity, single texture at unit zero
    setVertex(&v[0], x, y, 0.0f, u0, v0, cs[0]);
    setVertex(&v[1], x1, y, 0.0f, u1, v0, cs[1]);
    setVertex(&v[2], x1, y1, 0.0f, u1, v1, cs[2]);
    setVertex(&v[3], x, y1, 0.0f, u0, v1, cs[3]);
    return;
full:
    drawSurfaceImpl(r, surfaceId, srcLeft, srcTop, srcWidth, srcHeight, x, y, xscale, yscale, angleDeg, cs);
}
#endif
