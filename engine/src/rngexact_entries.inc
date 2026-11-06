/* Desktop and non-release entries. The 3DS release adapter redirects the
 * original compiled bodies, retaining the graph and canonical string pool. */
#define RNG_ENTRY(name) \
    extern RValue RNGExact_##name(VMContext*, RValue*, int32_t); \
    static RValue builtin_##name(VMContext* ctx, RValue* args, int32_t count) { \
        return RNGExact_##name(ctx, args, count); \
    }
RNG_ENTRY(random)
RNG_ENTRY(random_range)
RNG_ENTRY(irandom)
RNG_ENTRY(irandom_range)
#undef RNG_ENTRY
