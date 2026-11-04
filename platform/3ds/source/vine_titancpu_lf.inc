/* titancpu L-F on DELTARUNE New 3DS (late code only; c26rev R165, review decision: a no-move port).
 *
 * Titan_lfMeshRegion is ctr_pillar_exact.inc's fountainMeshRegion (F1 included) with two exact changes:
 *   (a) tile reuse: a tile that is valid, already drawn this frame (lastUsedFrame == textures.frame) and, while the
 *       cache records, seen this visit makes fountainTile's CtrTextures_ensureTiles a pure no-op (no recordTile, not
 *       hot since lastUsedFrame + 1 != frame, lastUsedFrame rewritten to itself, not missing, no load), so the cell
 *       takes CtrTextures_drawTex(tile) itself. Every other lookup (first use this frame, evicted, recording, a
 *       surface's one-tile page) makes fountainTile's call. Nothing is kept across cells, so an eviction inside the
 *       frame can't leave a stale pointer. Off under CTRPORT_ROOMPLAN_RECORDER (R165 F2).
 *   (b) clip skip: when both of the cell's columns sit inside both wavy edges with a 1e-5 margin, both fountainClip
 *       calls keep all four corners and return the rect in order (n = 4), so the cell uses the rect.
 *
 * Compiled in the vine helper pass only (ctr_renderer.c's end), so ctr_renderer.c's own code is compiled exactly as
 * without it. tools/analysis/vine_old_observer_compile.py then routes the two existing calls of fountainMeshRegion
 * (pillarSurfaceQuad.isra.0's bl, pillarEmitPageRegion's tail b) here, same size; fountainMeshRegion keeps its body,
 * address and size in .text.late.pillar (shared with the other pillar functions, so the link keeps it). This copy's
 * own calls are routed as the renderer's are (route_lf: reserveBatch -> Vine_wrap_reserveBatch), and its section is
 * linked last in late text (late_reserve.ld), so no existing late address moves. fountainMeshRegion calls external
 * functions (sinf, floorf, memcmp), so its two callers were already compiled with every call-clobbered register
 * clobbered across the call; this standard-ABI body (noipa) clobbers no more. */
#define TLF_CODE __attribute__((noinline, noipa, used, section(".text_titancpu_lf")))

static TLF_CODE void Titan_lfMeshRegion(CtrRenderer* r, CtrPage* page, float sx0, float sy0, float sx1, float sy1,
                                        const float* px, const float* py, const CtrColor* colors) {
    const float* uv = fountainUniformValue(r, pillarUvs);
    const float* offset = fountainUniformValue(r, pillarOffset);
    float time = fountainUniformValue(r, pillarTime)[0];
    float origin[2] = { uv[0] * (float) page->width, uv[1] * (float) page->height };
    float span[2] = { uv[2] * (float) page->width, uv[3] * (float) page->height };
    if (!(span[0] > 0.0f && span[1] > 0.0f && sx1 > sx0 && sy1 > sy0)) return;
    float u0 = (sx0 - origin[0]) / span[0], u1 = (sx1 - origin[0]) / span[0];
    float v0 = (sy0 - origin[1]) / span[1], v1 = (sy1 - origin[1]) / span[1];
    float loU = maxF(u0, 0.0f), hiU = minF(u1, 1.0f);
    float loV = v0, hiV = v1;
    if (!(hiU > loU && hiV > loV)) return;
    if (quadOutsideView(r, px, py)) return;
    if (hiV - loV > 1.0f) {
        float middle = loV + 1.0f;
        float t = (middle - v0) / (v1 - v0);
        float x[4], y[4];
        CtrColor c[4];
        // Stored one by one: an initialiser of constants is a plain .rodata copy, outside the extracted sections.
        float ss[4], tt[4];
        ss[0] = 0.0f, ss[1] = 1.0f, ss[2] = 1.0f, ss[3] = 0.0f;
        tt[0] = 0.0f, tt[1] = 0.0f, tt[2] = t, tt[3] = t;
        for (int i = 0; 4 > i; i++) quadPoint(px, py, colors, ss[i], tt[i], &x[i], &y[i], &c[i]);
        Titan_lfMeshRegion(r, page, sx0, sy0, sx1, origin[1] + middle * span[1], x, y, c);
        const float tb[4] = {t, t, 1, 1};
        for (int i = 0; 4 > i; i++) quadPoint(px, py, colors, ss[i], tb[i], &x[i], &y[i], &c[i]);
        Titan_lfMeshRegion(r, page, sx0, origin[1] + middle * span[1], sx1, sy1, x, y, c);
        return;
    }
    float phaseX[2] = { offset[0] + time * 0.008f, offset[0] - time * 0.009f };
    float phaseY[2] = { offset[1] + time * 0.005f, offset[1] + time * 0.007f };
    for (int32_t k = 0; 2 > k; k++) {
        phaseX[k] -= floorf(phaseX[k]);
        phaseY[k] -= floorf(phaseY[k]);
    }
    float xc[FOUNTAIN_CUTS_MAX], yc[FOUNTAIN_CUTS_MAX];
    int32_t nx = fountainCuts(xc, loU, hiU, origin[0], span[0], page->tileW, page->tilesX, phaseX, false);
    int32_t ny = fountainCuts(yc, loV, hiV, origin[1], span[1], page->tileH, page->tilesY, phaseY, true);
    float edges[FOUNTAIN_CUTS_MAX];
    for (int32_t j = 0; ny > j; j++) edges[j] = (1.0f + sinf(time + yc[j] * FOUNTAIN_WAVE_FREQUENCY)) * FOUNTAIN_EDGE;
    flushBatch(r);
    // titancpu F1: equal corner colours lerp to themselves (a + 0 * t), so the corners take colors[0] as quadPoint would.
    bool flat = memcmp(&colors[0], &colors[1], sizeof(CtrColor)) == 0 && memcmp(&colors[0], &colors[2], sizeof(CtrColor)) == 0 &&
                memcmp(&colors[0], &colors[3], sizeof(CtrColor)) == 0;
    // A convex quad's cells have disjoint coverage. Walk down each column so
    // sample-wrap transforms stay together instead of flushing per column per
    // row. Preserve row order for folded/nonconvex draw_sprite_pos quads.
    bool positive = true, negative = true;
    for (int32_t k = 0; 4 > k; k++) {
        int32_t m = (k + 1) % 4, n = (k + 2) % 4;
        float turn = (px[m] - px[k]) * (py[n] - py[m]) - (py[m] - py[k]) * (px[n] - px[m]);
        positive &= turn >= 0.0f;
        negative &= turn <= 0.0f;
    }
    bool columnMajor = positive || negative;
    int32_t outer = columnMajor ? nx : ny, inner = columnMajor ? ny : nx;
    for (int32_t outerIndex = 0; outer - 1 > outerIndex; outerIndex++) {
        for (int32_t innerIndex = 0; inner - 1 > innerIndex; innerIndex++) {
            int32_t i = columnMajor ? outerIndex : innerIndex, j = columnMajor ? innerIndex : outerIndex;
            float a = yc[j], b = yc[j + 1];
            float edgeA = edges[j], edgeB = edges[j + 1];
            CtrFountainPoint rect[4] = { {xc[i], a}, {xc[i + 1], a}, {xc[i + 1], b}, {xc[i], b} };
            CtrFountainPoint mid[8], poly[8];
            // L-F (b): a cell whose columns sit inside both edges (with a margin far above float error) keeps all four
            // corners in both clips, which then return the rect itself in order: skip them.
            const CtrFountainPoint* pts = poly;
            int32_t n = 4;
            float inset = maxF(edgeA, edgeB) + 0.00001f;
            if (xc[i] >= inset && 1.0f - inset >= xc[i + 1]) pts = rect;
            else {
                n = fountainClip(rect, 4, mid, a, b, edgeA, edgeB, false);
                if (3 > n) continue;
                n = fountainClip(mid, n, poly, a, b, edgeA, edgeB, true);
                if (3 > n) continue;
            }
            float centreU = (xc[i] + xc[i + 1]) * 0.5f, centreV = (a + b) * 0.5f;
            float shiftX[2], shiftY[2];
            C3D_Tex* tex[2];
            int32_t tileX[2], tileY[2];
            for (int32_t k = 0; 2 > k; k++) {
                shiftX[k] = phaseX[k] - floorf(centreU + phaseX[k]);
                shiftY[k] = phaseY[k] - floorf(centreV + phaseY[k]);
#if !defined(CTRPORT_ROOMPLAN_RECORDER)
                // L-F (a): a tile already drawn this frame, resident and recorded this visit makes fountainTile's
                // ensureTiles a no-op (not hot, not missing, nothing to record): take it here. Off in the room plan
                // recorder (c26rev R165 F2), whose plan must see every lookup the way fountainTile makes it.
                float x = origin[0] + (centreU + shiftX[k]) * span[0], y = origin[1] + (centreV + shiftY[k]) * span[1];
                int32_t tx = minI(maxI((int32_t) floorf(x / (float) page->tileW), 0), page->tilesX - 1);
                int32_t ty = minI(maxI((int32_t) floorf(y / (float) page->tileH), 0), page->tilesY - 1);
                CtrTile* tile = &page->tiles[ty * page->tilesX + tx];
                if (tile->valid && tile->lastUsedFrame == r->textures.frame &&
                    (0 > r->textures.recordRoom || tile->seenVisit == r->textures.recordVisit)) {
                    tileX[k] = tx, tileY[k] = ty, tex[k] = CtrTextures_drawTex(tile);
                } else {
                    tex[k] = fountainTile(r, page, x, y, &tileX[k], &tileY[k]);
                }
#else
                tex[k] = fountainTile(r, page, origin[0] + (centreU + shiftX[k]) * span[0],
                                      origin[1] + (centreV + shiftY[k]) * span[1], &tileX[k], &tileY[k]);
#endif
            }
            if (tex[0] == nullptr || tex[1] == nullptr) continue;
            r->palNextB = tex[1];
            r->palNextTc1[0] = r->palNextTc1[1] = 1.0f;
            r->palNextTc1[2] = ((shiftX[1] - shiftX[0]) * span[0]) / (float) page->tileW + (float) (tileX[0] - tileX[1]);
            r->palNextTc1[3] = ((shiftY[1] - shiftY[0]) * span[1]) / (float) page->tileH + (float) (tileY[0] - tileY[1]);
            // A new transform with the same texture pair: fountainTc1Flush sets it on the batch (see there).
            // Keep the generic batch lookup unchanged for every other caller.
            if (memcmp(r->palNextTc1, r->batchTc1, sizeof(r->batchTc1)) != 0) fountainTc1Flush(r);
            CtrVertex* verts = reserveVertices(r, tex[0], (uint32_t) (n - 2) * 3u);
            if (verts == nullptr) continue;
            CtrVertex corners[8];
            for (int32_t q = 0; n > q; q++) {
                CtrFountainPoint p = pts[q];
                float x, y;
                CtrColor c;
                float s = (p.u - u0) / (u1 - u0), t = (p.v - v0) / (v1 - v0);
                if (flat) quadPosition(px, py, s, t, &x, &y), c = colors[0];
                else quadPoint(px, py, colors, s, t, &x, &y, &c);
                c.a = unitToByte(1.0f - fabsf(p.u - 0.5f) * 0.75f);
                float u = (origin[0] + (p.u + shiftX[0]) * span[0]) / (float) page->tileW - (float) tileX[0];
                float v = (origin[1] + (p.v + shiftY[0]) * span[1]) / (float) page->tileH - (float) tileY[0];
                setVertex(&corners[q], x, y, r->vertexZ, u, v, c);
            }
            for (int32_t k = 1; n - 1 > k; k++) {
                *verts++ = corners[0];
                *verts++ = corners[k];
                *verts++ = corners[k + 1];
            }
        }
    }
    flushBatch(r);
    r->palNextB = nullptr;
}
