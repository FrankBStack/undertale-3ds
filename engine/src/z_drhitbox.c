// GM 2022.9 legacy collision corrections. Linked only by the DR target.
// Keep the original bodies and their callers' layout; drhitbox_compile.py
// redirects the two rectangle calls and adds a 4-byte retained-bbox bridge.
// GCC may outline this header helper here. Keep its new late copy distinct
// from the two existing retained definitions, which must keep their identity.
#define Collision_instanceOBB DrHitbox_instanceOBB
#include "collision.h"

#if defined(ENABLE_WAD17) && !defined(ENABLE_WAD16)
#define DRHB_LATE __attribute__((noinline, section(".text.drhitbox_late")))

static bool __attribute__((section(".bss.drhitbox_late"))) drhbLegacy;

static inline bool drhbData(const DataWin* dw) {
    return dw->gen8.wadVersion == 17 && dw->detectedFormat.major == 2022 &&
        dw->detectedFormat.minor == 9 && dw->detectedFormat.release == 0 &&
        dw->detectedFormat.build == 0 && ((dw->optn.info >> 27) & 1) != 0;
}

#if defined(__3DS__) && !defined(USE_FLOAT_REALS)
// Assembly bridge to runner.c's retained Collision_computeBBox. Its input,
// rounding and outputs remain exactly those used by the original query.
InstanceBBox DrHitbox_sharedBBox(Runner* runner, Instance* inst);
#else
static inline InstanceBBox DrHitbox_sharedBBox(Runner* runner, Instance* inst) {
    return Collision_computeBBox(runner, inst);
}
#endif

DRHB_LATE bool DrHitbox_rectHits(Runner* runner, Instance* inst,
                               GMLReal x1, GMLReal y1, GMLReal x2, GMLReal y2, bool prec) {
    Sprite* spr = Collision_getSprite(runner->dataWin, inst);
    if (!runner->collisionCompatibilityMode || !drhbData(runner->dataWin) ||
        !Collision_obbNeedsSAT(spr, inst)) {
        return Collision_compatRectHitsInstance(runner, inst, x1, y1, x2, y2, prec);
    }
    InstanceBBox bbox = DrHitbox_sharedBBox(runner, inst);
    if (!bbox.valid || x1 > bbox.right - 1.0 || bbox.left > x2 ||
        y1 > bbox.bottom - 1.0 || bbox.top > y2) return false;

    // Native rectangle-query corners use x-0.5/y-0.5. Do not translate the
    // rounded broad phase or the query rectangle along with them.
    InstanceOBB obb = Collision_instanceOBB(spr, inst);
    obb.x -= 0.5;
    obb.y -= 0.5;
    GMLReal corners[4][2] = {{x1, y1}, {x2, y1}, {x1, y2}, {x2, y2}};
    GMLReal uMin = 0, uMax = 0, vMin = 0, vMax = 0;
    for (int c = 0; c < 4; c++) {
        GMLReal u, v;
        Collision_obbWorldToLocal(&obb, corners[c][0], corners[c][1], &u, &v);
        if (c == 0) { uMin = uMax = u; vMin = vMax = v; }
        else {
            if (u < uMin) uMin = u; else if (u > uMax) uMax = u;
            if (v < vMin) vMin = v; else if (v > vMax) vMax = v;
        }
    }
    return uMin < obb.lx1 && obb.lx0 < uMax && vMin < obb.ly1 && obb.ly0 < vMax;
}

void __real_Colflip_registerAll(VMContext* ctx);
DRHB_LATE void __wrap_Colflip_registerAll(VMContext* ctx) {
    __real_Colflip_registerAll(ctx);
    drhbLegacy = drhbData(ctx->dataWin);
}

// Mixed bitmap pairs already passed the rounded AABB test. A common -0.5 px
// translation of both boxes cancels, so their relative SAT uses the existing
// corner coordinates. The bitmap walk itself is unchanged.
static DRHB_LATE bool drhbPairSAT(const ColflipScan* scan) {
    InstanceOBB a = Collision_instanceOBB(scan->sprA, scan->a);
    InstanceOBB b = Collision_instanceOBB(scan->sprB, scan->b);
    GMLReal ax[4], ay[4], bx[4], by[4];
    GMLReal alx[2] = {a.lx0, a.lx1}, aly[2] = {a.ly0, a.ly1};
    GMLReal blx[2] = {b.lx0, b.lx1}, bly[2] = {b.ly0, b.ly1};
    for (int j = 0; j < 2; j++) {
        for (int i = 0; i < 2; i++) {
            int k = j * 2 + i;
            ax[k] = a.x + a.cs * alx[i] + a.sn * aly[j];
            ay[k] = a.y - a.sn * alx[i] + a.cs * aly[j];
            bx[k] = b.x + b.cs * blx[i] + b.sn * bly[j];
            by[k] = b.y - b.sn * blx[i] + b.cs * bly[j];
        }
    }
    GMLReal axes[4][2] = {{a.cs, -a.sn}, {a.sn, a.cs}, {b.cs, -b.sn}, {b.sn, b.cs}};
    for (int k = 0; k < 4; k++) {
        GMLReal nx = axes[k][0], ny = axes[k][1];
        GMLReal amin = ax[0] * nx + ay[0] * ny, amax = amin;
        GMLReal bmin = bx[0] * nx + by[0] * ny, bmax = bmin;
        for (int j = 1; j < 4; j++) {
            GMLReal pa = ax[j] * nx + ay[j] * ny;
            GMLReal pb = bx[j] * nx + by[j] * ny;
            if (pa < amin) amin = pa; else if (pa > amax) amax = pa;
            if (pb < bmin) bmin = pb; else if (pb > bmax) bmax = pb;
        }
        if (amax <= bmin || bmax <= amin) return false;
    }
    return true;
}

bool __real_Colflip14_scanPixels(const ColflipScan* scan);
DRHB_LATE bool __wrap_Colflip14_scanPixels(const ColflipScan* scan) {
    if (drhbLegacy && (Collision_obbNeedsSAT(scan->sprA, scan->a) ||
                      Collision_obbNeedsSAT(scan->sprB, scan->b)) && !drhbPairSAT(scan)) return false;
    return __real_Colflip14_scanPixels(scan);
}
#endif
