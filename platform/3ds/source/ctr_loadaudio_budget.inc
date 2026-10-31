// Source-sample bookkeeping for the frame-budget extension.
// Caller owns publication, source observations and transport.
// No wall-time integration, seek, pitch change, allocation or waiting here.
#ifndef LA_BUDGET_CODE
#define LA_BUDGET_CODE __attribute__((noinline, noipa, optimize("Os"), section(".text.late.loadaudio")))
#endif

typedef struct {
    uint64_t played, last;
    uint32_t serial, epoch;
    bool valid;
} LaBudget;

enum { LA_BUDGET_UNKNOWN = -1, LA_BUDGET_RUN, LA_BUDGET_HOLD };

// anchor is the requested initial/seek source sample, not the current quota.
// epoch changes for an authored seek; serial changes for a new logical voice.
// span bounds physical advance since the prior valid observation (or anchor
// for the first one). If it permits a whole loop, modulo positions cannot prove
// the number of loops. Reject that observation instead of guessing a cycle.
// reserve covers callback/control latency; it does not change played samples.
LA_BUDGET_CODE static int laBudgetStep(LaBudget* state, uint32_t serial, uint32_t epoch,
                                     uint64_t anchor, uint64_t source, uint64_t length,
                                     bool loop, uint64_t span, uint64_t quota, uint64_t reserve) {
    if (length == 0 || source >= length || (loop && span >= length)) return LA_BUDGET_UNKNOWN;
    bool fresh = !state->valid || state->serial != serial || state->epoch != epoch;
    uint64_t previous = fresh ? (loop ? anchor % length : anchor) : state->last;
    if (!loop && source < previous) return LA_BUDGET_UNKNOWN;
    uint64_t delta = source >= previous ? source - previous : length - previous + source;
    if (delta > span) return LA_BUDGET_UNKNOWN;
    uint64_t played = fresh ? anchor : state->played;
    if (UINT64_MAX - played < delta) return LA_BUDGET_UNKNOWN;
    state->played = played + delta;
    state->last = source;
    state->serial = serial;
    state->epoch = epoch;
    state->valid = true;
    uint64_t limit = quota > reserve ? quota - reserve : 0;
    return state->played >= limit ? LA_BUDGET_HOLD : LA_BUDGET_RUN;
}
