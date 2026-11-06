/* Separate translation unit: the original builtin entries retain their slots. */
#define RValue_toRealOther RNGExact_toRealOther
#include "vm_builtins.h"
#include "runner.h"
#include "rvalue.h"
#include "rngexact.h"

#if defined(__3DS__) && defined(__GNUC__)
#define RNG_CODE __attribute__((noinline, section(".text.late.rngexact")))
#else
#define RNG_CODE
#endif

/* GM 1.4's real getter coerces non-finite arguments to zero. GM 2 keeps
 * them; the integer conversion below then produces its indefinite value. */
#if defined(__GNUC__) || defined(__clang__)
__attribute__((always_inline))
#endif
static inline GMLReal realArg(MAYBE_UNUSED VMContext* ctx, RValue arg) {
    GMLReal value = RValue_toReal(arg);
    return IS_WAD16_OR_BELOW(ctx) && !isfinite(value) ? 0.0 : value;
}

static RNG_CODE int64_t integerArg(VMContext* ctx, RValue arg) {
#ifndef NO_RVALUE_INT64
    if (arg.type == RVALUE_INT64) return arg.int64;
#endif
    return RNGExact_bound(realArg(ctx, arg));
}

RNG_CODE RValue RNGExact_random(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 1) return RValue_makeReal(0.0);
    return RValue_makeReal(RNGExact_real(&ctx->runner->random, realArg(ctx, args[0])));
}

RNG_CODE RValue RNGExact_random_range(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 2) return RValue_makeReal(0.0);
    GMLReal lo = realArg(ctx, args[0]), hi = realArg(ctx, args[1]);
    return RValue_makeReal(RNGExact_realRange(&ctx->runner->random, lo, hi));
}

RNG_CODE RValue RNGExact_irandom(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 1) return RValue_makeReal(0.0);
    return RValue_makeReal(RNGExact_integer(&ctx->runner->random, integerArg(ctx, args[0])));
}

RNG_CODE RValue RNGExact_irandom_range(VMContext* ctx, RValue* args, int32_t count) {
    if (count < 2) return RValue_makeReal(0.0);
    int64_t lo = integerArg(ctx, args[0]), hi = integerArg(ctx, args[1]);
    return RValue_makeReal(RNGExact_integerRange(&ctx->runner->random, lo, hi));
}
