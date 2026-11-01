/* A native surface's opaque overlaps must be resolved before additive
 * composition. Compact physical surfaces must not sample unallocated rows.
 * Included only by the independent Old DELTARUNE helper assembly pass. */
#define DRPIX_CODE __attribute__((noinline, used, optimize("Os", "no-tree-switch-conversion"), section(".text.drpix_late")))
#define DRPIX_CALL(name) ({ __typeof__(&(name)) drpixFn = &(name); __asm__("" : "+r"(drpixFn)); drpixFn; })

static DRPIX_CODE bool drpixNativeColours(CtrRenderer* r, int32_t id) {
    CtrSurface* s = &r->surfaces[id];
    ptrdiff_t count = arrlen(s->ops);
    if (!s->recorded || !s->noVram || !s->wantNative || s->windowed || !r->inFrame ||
        r->shaderFx != SHADER_FX_NONE || r->opAlphaCut != 0 || count == 0 || count > 16 ||
        !r->colorWrite[0] || !r->colorWrite[1] || !r->colorWrite[2] || !r->colorWrite[3] ||
        0 > r->boundSurface || r->boundSurface == id || r->surfaces[r->boundSurface].recorded) return false;
    for (ptrdiff_t i = 0; count > i; i++) {
        if (s->ops[i].pageId != REC_COLOR_PAGE || s->ops[i].alphaCut != 0 ||
            s->ops[i].castleFade || s->ops[i].zeroFromZero) return false;
    }

    // promoteRecorded already preserves native resolution and can obtain the
    // shared scratch by demoting an idle surface. Keep the recipe here: this
    // is a live read, rather than a clear that would discard its operations.
    CtrRecOp* ops = s->ops;
    bool failed = s->windowFailed, live = r->liveSnapshot;
    uint32_t attempt = s->promoteFrame;
    s->ops = nullptr;
    s->windowFailed = true;
    r->liveSnapshot = true;
    bool promoted = DRPIX_CALL(promoteRecorded)(r, id);
    r->liveSnapshot = live;
    s = &r->surfaces[id];
    s->windowFailed = failed;
    if (!promoted) {
        s->ops = ops;
        s->promoteFrame = attempt;
        return false;
    }

    int32_t previous = r->boundSurface;
    DRPIX_CALL(flushBatch)(r);
    s->needsClear = true;
    DRPIX_CALL(bindSurface)(r, id);
    // Restrict the viewport to the logical image. The native offset then has
    // exactly the same scale as an ordinary game draw onto this surface,
    // including the top alignment in a larger shared scratch.
    DRPIX_CALL(materializeState)(r, s->width >> s->shift, s->height >> s->shift);
    C3D_Mtx pixels;
    memset(&pixels, 0, sizeof(pixels));
    pixels.r[0].x = 2.0f / (float) s->width;
    pixels.r[0].w = -1.0f;
    pixels.r[1].y = -2.0f / (float) s->height;
    pixels.r[1].w = 1.0f;
    pixels.r[2].w = -0.5f;
    pixels.r[3].w = 1.0f;
    DRPIX_CALL(uploadProjection)(r, &pixels);
    r->gridHold++;
    for (ptrdiff_t i = 0; count > i; i++) {
        DRPIX_CALL(emitQuad)(r, &r->white, ops[i].x, ops[i].y, 0.5f, 0.5f, 0.5f, 0.5f, ops[i].c);
    }
    DRPIX_CALL(flushBatch)(r);
    r->gridHold--;
    arrfree(ops);
    DRPIX_CALL(bindSurface)(r, previous);
    DRPIX_CALL(applyEyeViewport)(r, false);
    DRPIX_CALL(uploadProjection)(r, &r->projection);
    DRPIX_CALL(applyBlend)(r);
    DRPIX_CALL(applyAlphaTest)(r);
    return true;
}

static DRPIX_CODE void Drpix_replay(CtrRenderer* r, CtrSurface* s, float sx0, float sy0, float sx1, float sy1,
                                    const float* px, const float* py, const CtrColor* cs) {
    int32_t id = (int32_t) (s - r->surfaces);
    if (r->blendEnable && r->blendMode == bm_add && drpixNativeColours(r, id)) {
        DRPIX_CALL(drawSurfaceQuad)(r, id, &r->surfaces[id], sx0, sy0, sx1, sy1, px, py, cs);
        return;
    }
    DRPIX_CALL(replayRecorded)(r, s, sx0, sy0, sx1, sy1, px, py, cs);
}

/* The preserved pass drops pillarSurfaceQuad's unused surface argument.
 * Its one drawSurfaceQuad tail branch qualifies this frozen entry/ABI:
 * r0=r, r1=tex, r2=px, r3=py, stack=cs; s0..s5=tw,th,sx0,sy0,sx1,sy1.
 * An assembler alias calls that existing specialization without taking the
 * C function's address (which would emit a different full entry). */
extern void drpixPillarSurface(CtrRenderer*, C3D_Tex*, float, float, float, float, float, float,
                              const float*, const float*, const CtrColor*) __asm__("pillarSurfaceQuad.isra.0");

static DRPIX_CODE void Drpix_surfaceQuad(CtrRenderer* r, C3D_Tex* tex, float tw, float th,
                                        float sx0, float sy0, float sx1, float sy1,
                                        const float* px, const float* py, const CtrColor* cs) {
    if (r->shaderFx == SHADER_FX_NONE && tex->fmt == GPU_RGBA8) {
        uint32_t rows = tex->size / ((uint32_t) tex->width * 4u);
        if (rows < tex->height) {
            float scale = th / (float) tex->height;
            float end = (float) rows * scale;
            if (sy0 >= end && sy1 >= end) {
                // Both endpoints lie beyond compact storage. Clamp to its
                // cleared guard, rather than the advertised texture's last
                // row, which has no allocation. Do not distort a quad that
                // crosses the boundary or change a shader's coordinates.
                sy0 = sy1 = ((float) rows - 0.5f) * scale;
            }
        }
    }
    drpixPillarSurface(r, tex, tw, th, sx0, sy0, sx1, sy1, px, py, cs);
}

#undef DRPIX_CALL
#undef DRPIX_CODE
