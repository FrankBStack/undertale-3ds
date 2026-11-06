/* Native RNG mappings. Seed initialization is deliberately unchanged.
 * Unsigned arithmetic below spells out the native signed-width wrap without
 * relying on C signed overflow or an out-of-range floating-to-integer cast.
 */
#include "rngexact.h"

#if defined(__3DS__) && defined(__GNUC__)
#define RNG_CODE __attribute__((noinline, section(".text.late.rngexact")))
#else
#define RNG_CODE
#endif

static inline int64_t signedBits(uint64_t bits) {
    return (bits >> 63) ? INT64_MIN + (int64_t)(bits & INT64_MAX) : (int64_t)bits;
}

RNG_CODE int64_t RNGExact_bound(GMLReal value) {
    if (!(value >= (GMLReal)-0x1p63 && value < (GMLReal)0x1p63)) return INT64_MIN;
    return (int64_t)value;
}

RNG_CODE GMLReal RNGExact_real(Random* random, GMLReal bound) {
    return ((GMLReal)Random_nextUInt32(random) / (GMLReal)4294967296.0) * bound;
}

RNG_CODE GMLReal RNGExact_realRange(Random* random, GMLReal lo, GMLReal hi) {
    if (lo > hi) { GMLReal temp = lo; lo = hi; hi = temp; }
    GMLReal unit = (GMLReal)Random_nextUInt32(random) / (GMLReal)4294967296.0;
    return lo + unit * (hi - lo);
}

/* width is a signed 64-bit bit pattern. The native helper takes a signed
 * exclusive width, returns a remainder with that width's sign, and consumes
 * both words even for width 0 or 1. Low word comes first. */
static RNG_CODE uint64_t signedModulo(Random* random, uint64_t width) {
    uint64_t low = Random_nextUInt32(random);
    uint64_t high = Random_nextUInt32(random) & UINT32_C(0x7fffffff);
    uint64_t value = low | (high << 32);
    bool negative = (width >> 63) != 0;
    uint64_t magnitude = negative ? UINT64_C(0) - width : width;
    uint64_t result = magnitude ? value % magnitude : 0;
    return negative ? UINT64_C(0) - result : result;
}

RNG_CODE GMLReal RNGExact_integer(Random* random, int64_t bound) {
    uint64_t magnitude = bound < 0 ? UINT64_C(0) - (uint64_t)bound : (uint64_t)bound;
    uint64_t result = signedModulo(random, magnitude + 1);
    if (bound < 0) result = UINT64_C(0) - result;
    return (GMLReal)signedBits(result);
}

RNG_CODE GMLReal RNGExact_integerRange(Random* random, int64_t lo, int64_t hi) {
    if (lo > hi) { int64_t temp = lo; lo = hi; hi = temp; }
    uint64_t width = (uint64_t)hi - (uint64_t)lo + 1;
    uint64_t result = (uint64_t)lo + signedModulo(random, width);
    return (GMLReal)signedBits(result);
}
