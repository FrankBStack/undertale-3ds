/* UT release prototype, compiled by parity_motion_compile.py into the retained
 * Instance_computeComponentsFromSpeed slot. The ordinary instance translation
 * unit is compiled unchanged; no function or data is moved. Native finite-bit
 * contract and remaining gates: tools/buildcache/parity_motion_verify.py.
 */
#include "instance.h"
#include <math.h>

__attribute__((noipa, optimize("no-fast-math")))
void Instance_computeComponentsFromSpeed(Instance* inst) {
    /* PC's observed stages differ from truncating a double trig factor. Keep
     * the multiply/divide order and each binary32 conversion explicit. */
    float radians = (float)(((double)inst->direction * (double)0x1.921fb6p+1f) / 180.0);
    float cosine = (float)cos((double)radians);
    float sine = (float)sin((double)radians);
    float h = inst->speed * cosine;
    float v = -inst->speed * sine;
    float rh = roundf(h);
    float rv = roundf(v);
    if (fabsf(h - rh) < 0x1.a36e2ep-14f) h = rh == 0.0f ? 0.0f : rh;
    if (fabsf(v - rv) < 0x1.a36e2ep-14f) v = rv == 0.0f ? 0.0f : rv;
    inst->hspeed = h;
    inst->vspeed = v;
}
