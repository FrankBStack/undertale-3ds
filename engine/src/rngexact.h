#ifndef BS_RNGEXACT_H
#define BS_RNGEXACT_H

#include "random.h"
#include "real_type.h"

/* The native integer boundary conversion, including its indefinite value. */
int64_t RNGExact_bound(GMLReal value);
GMLReal RNGExact_real(Random* random, GMLReal bound);
GMLReal RNGExact_realRange(Random* random, GMLReal lo, GMLReal hi);
GMLReal RNGExact_integer(Random* random, int64_t bound);
GMLReal RNGExact_integerRange(Random* random, int64_t lo, int64_t hi);

#endif
