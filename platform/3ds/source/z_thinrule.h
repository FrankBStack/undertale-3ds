// change thinrule (first update, UNDERTALE): the whole-rows table z_thinrule.c reads and ctr_renderer.c's Smart fallback
// draws from (tools/aot/thinrule.py).
#pragma once

#include <stdint.h>

// One fine item drawn sharp: its page (bits 24-31), source y (12-23) and x (0-11), its size, and where its rescues
// start in bytes (THINRULE_NONE: none there).
typedef struct {
    uint32_t key;
    uint16_t off;
    uint8_t w, h;
} ThinruleEntry;

#define THINRULE_NONE 0xFFFFu

// entries sorted by key, count of them (0: no table), then bytes: per item with rescues, u8 rows, u8 columns, then
// the rows and the columns (bits 0-6 the row, bit 7 set when the donor is the next row); bits, a bit per
// thinruleHash of an entry's source corner (nullptr: no table), so most draws of items not listed stop at one load.
typedef struct {
    const ThinruleEntry* entries;
    const uint8_t* bytes;
    uint32_t count, size;
    const uint32_t* bits;
} ThinruleTable;

#define THINRULE_HASH_BITS 15
#define THINRULE_BIT_BYTES ((1u << THINRULE_HASH_BITS) / 8u)

// The bit of the source corner (x, y), the page left out.
static inline uint32_t thinruleHash(uint32_t x, uint32_t y) {
    return (x * 0x9E3779B1u + y * 0x85EBCA6Bu) >> (32 - THINRULE_HASH_BITS);
}

extern ThinruleTable Thinrule_table;
