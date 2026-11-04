// KM rev 5 (change pacer): the bounded chain of sealed command ranges inside one
// physical recording. Pure bookkeeping, no 3DS calls, so the host fixture
// (tools/analysis/test_kick_chain.c) runs this same code. Every function here
// runs with the caller holding gateLock (ctr_gpu_queue.c); the callback side
// (GSP thread) and the recording thread both take it.
//
// Ownership and frontiers (R123):
// - A recording's entries [base, sealedEnd) are sealed: copied into immutable
//   range descriptors (kick.entries, same index, so ranges never overlap) and
//   owned by the chain. [sealedEnd, numEntries) still belong to the recording
//   thread, and are the suffix if nothing seals them.
// - completedEnd <= submittedEnd <= sealedEnd, each only ever grows within a
//   recording. A range is submitted only when the one before it has completed
//   (one range on the GPU at a time, in FIFO order), so completedEnd is the
//   from of the oldest live range, or sealedEnd when the chain is empty.
// - Slots go FREE -> SEALED -> SUBMITTED -> FREE. Each seal takes a new
//   generation; a completion is accepted only for the submitted head slot with
//   its generation, so a stale or doubled callback changes nothing.
// - The FIFO is bounded (KICK_CHAIN_SLOTS). A full FIFO seals nothing: the
//   entries stay with the recording (the next split or the suffix takes them),
//   which is the original path. Nothing here blocks or allocates.
// - Retirement of the frame is not the chain's: a range completion only moves
//   completedEnd. The whole frame retires once, after its suffix (ctr_gpu_kick.inc).
#ifndef CTRPORT_CTR_GPU_KICK_CHAIN_H
#define CTRPORT_CTR_GPU_KICK_CHAIN_H

#include <stdbool.h>
#include <stdint.h>

#ifndef KICK_CHAIN_SLOTS
#define KICK_CHAIN_SLOTS 4u
#endif
_Static_assert((KICK_CHAIN_SLOTS & (KICK_CHAIN_SLOTS - 1u)) == 0u && KICK_CHAIN_SLOTS != 0u,
               "head/tail wrap needs a power-of-two slot count");

enum { KICK_SLOT_FREE, KICK_SLOT_SEALED, KICK_SLOT_SUBMITTED };

typedef struct {
    uint32_t from, to, gen;
    uint8_t state;
} KickRange;

typedef struct {
    KickRange slot[KICK_CHAIN_SLOTS];
    uint32_t head, tail; // live slots are head..tail-1 (mod KICK_CHAIN_SLOTS), oldest first
    uint32_t base, sealedEnd, submittedEnd, completedEnd;
    uint32_t gen;
    bool active; // the head slot is on the GPU
} KickChain;

static inline uint32_t kickChainCount(const KickChain* c) {
    return c->tail - c->head;
}

static inline bool kickChainBusy(const KickChain* c) {
    return c->active || c->head != c->tail;
}

static inline bool kickChainFull(const KickChain* c) {
    return kickChainCount(c) >= KICK_CHAIN_SLOTS;
}

// A new recording's chain, from entry base. Only when nothing is live (the
// caller checks kickChainBusy first and declines the kick otherwise).
static inline bool kickChainReset(KickChain* c, uint32_t base) {
    if (kickChainBusy(c)) return false;
    c->base = c->sealedEnd = c->submittedEnd = c->completedEnd = base;
    return true;
}

// Seals [sealedEnd, to) into the tail slot. Returns the slot, or -1 when the
// range is empty or the FIFO is full (nothing changes then).
static inline int kickChainSeal(KickChain* c, uint32_t to) {
    if (to <= c->sealedEnd || kickChainFull(c)) return -1;
    uint32_t i = c->tail % KICK_CHAIN_SLOTS;
    KickRange* r = &c->slot[i];
    if (r->state != KICK_SLOT_FREE) return -1; // cannot happen with count < slots
    r->from = c->sealedEnd;
    r->to = to;
    r->gen = ++c->gen;
    r->state = KICK_SLOT_SEALED;
    c->sealedEnd = to;
    c->tail++;
    return (int) i;
}

// The slot to submit now, or -1: the head, if it is sealed and nothing of this
// chain is on the GPU. The caller also requires the GPU free of other frames.
static inline int kickChainNext(KickChain* c) {
    if (c->active || c->head == c->tail) return -1;
    uint32_t i = c->head % KICK_CHAIN_SLOTS;
    KickRange* r = &c->slot[i];
    if (r->state != KICK_SLOT_SEALED || r->from != c->completedEnd) return -1;
    r->state = KICK_SLOT_SUBMITTED;
    c->submittedEnd = r->to;
    c->active = true;
    return (int) i;
}

// A range's completion (the GSP thread). Accepted only for the submitted head
// with its generation; returns false and changes nothing otherwise.
static inline bool kickChainFinished(KickChain* c, uint32_t i, uint32_t gen) {
    if (!c->active || c->head == c->tail || i != c->head % KICK_CHAIN_SLOTS) return false;
    KickRange* r = &c->slot[i];
    if (r->state != KICK_SLOT_SUBMITTED || r->gen != gen) return false;
    c->completedEnd = r->to;
    r->state = KICK_SLOT_FREE;
    c->head++;
    c->active = false;
    return true;
}

#endif
