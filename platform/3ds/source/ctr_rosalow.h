// The Rosalina limit lowering's decisions (z_rosalow.c), apart so tools/analysis/test_rosalow.py can run them on the host.
// One step per watcher poll. No time limit call or button read here.
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    ROSALOW_NONE,
    ROSALOW_LOWER,
    ROSALOW_RAISE_QUIET,  // the combo stopped forming
    ROSALOW_RAISE_CAP,    // held too long since its last new press
    ROSALOW_RAISE_RESUME, // the app was paused and runs again
    ROSALOW_RAISE_BUDGET, // game buttons alone have used up their time at the low limit
} CtrRosalowAct;

typedef struct {
    uint64_t quietAt; // the last poll that saw the combo forming, while low
    uint64_t pressAt; // the last new press of a combo button, while low
    uint64_t lastAt;  // the last poll
    uint64_t spent;   // low time charged to game buttons, less what time since has paid back
    uint32_t prev;    // the combo's buttons held at the last poll
    bool low;
    bool capped;      // no lowering until a new press of a combo button
} CtrRosalowState;

// Rosalina opens only when the whole combo is down, so anything less than two of its buttons says nothing. One button
// alone never counts here: SELECT opens UNDERTALE's options menu, and Down is a game button.
static inline bool CtrRosalow_forming(uint32_t part, uint32_t combo) {
    return part != 0 && (part == combo || (part & (part - 1)) != 0);
}

#define CTR_ROSALOW_SELECT 4u // KEY_SELECT: z_rosalow.c checks that

// Without SELECT, the buttons could be someone playing, so the time they keep the limit low is on a budget. Low time with
// SELECT up adds to `spent`, and any other time takes a tenth of itself off. At budgetTicks it comes back up; it goes down
// again only on a new press with rearmTicks to spend. In any window of W, low time L obeys L <= budget + (W - L) / 10, so
// a budget of 600 ms holds it to 1 s in any 5 s, whatever the pattern. SELECT is never a game button, and with it down a
// menu is likely, so its low time isn't charged and it can lower with the budget gone.
//
// part: the combo's buttons held now. paused: this poll came so late that the app was stopped (Rosalina, HOME, sleep).
// The action is assumed to work; z_rosalow.c puts `low` right when it doesn't.
static inline CtrRosalowAct CtrRosalow_step(CtrRosalowState* st, uint64_t now, uint32_t part, uint32_t combo, bool paused,
                                            uint64_t quietTicks, uint64_t capTicks, uint64_t budgetTicks,
                                            uint64_t rearmTicks) {
    uint32_t fresh = part & ~st->prev;
    st->prev = part;
    uint64_t gap = now - st->lastAt;
    st->lastAt = now;
    bool select = (part & CTR_ROSALOW_SELECT) != 0;
    if (st->low && !paused) {
        if (!select) st->spent += gap;
    } else {
        st->spent -= gap / 10 < st->spent ? gap / 10 : st->spent;
    }
    if (paused) {
        // Whatever is still held went down during the pause or before it, so it isn't a new try at the combo.
        st->capped = part != 0;
        if (!st->low) return ROSALOW_NONE;
        st->low = false;
        return ROSALOW_RAISE_RESUME;
    }
    if (fresh != 0) st->capped = false;
    bool forming = CtrRosalow_forming(part, combo);
    if (!st->low) {
        if (!forming || st->capped) return ROSALOW_NONE;
        if (!select && st->spent + rearmTicks > budgetTicks) {
            st->capped = true; // this press got nothing; the next one asks again
            return ROSALOW_NONE;
        }
        st->low = true;
        st->quietAt = st->pressAt = now;
        return ROSALOW_LOWER;
    }
    if (fresh != 0) st->pressAt = now;
    if (forming) st->quietAt = now;
    if (!select && st->spent >= budgetTicks) {
        st->low = false; // and the rearm test above stops the same press lowering again
        return ROSALOW_RAISE_BUDGET;
    }
    if (now - st->pressAt >= capTicks) {
        st->low = false;
        st->capped = true;
        return ROSALOW_RAISE_CAP;
    }
    if (now - st->quietAt >= quietTicks) {
        st->low = false;
        return ROSALOW_RAISE_QUIET;
    }
    return ROSALOW_NONE;
}
