#ifndef GMLSTUBS_BACKGROUND_STATE_H
#define GMLSTUBS_BACKGROUND_STATE_H

#include <stddef.h>
#include "runner.h"

// Keep the shared runner header byte-identical to the pinned Windows texture
// preparer. Access only the object representation's three unused padding bytes.
enum { GMLSTUBS_COLOUR_OFFSET = offsetof(RuntimeBackground, stretch) + sizeof(bool) };
_Static_assert(sizeof(RuntimeBackground) == 44, "background ABI");
_Static_assert(GMLSTUBS_COLOUR_OFFSET == 37, "colour padding");
_Static_assert(offsetof(RuntimeBackground, alpha) == GMLSTUBS_COLOUR_OFFSET + 3, "alpha ABI");

static inline unsigned char* Gmlstubs_colourBytes(RuntimeBackground* bg) {
    return (unsigned char*)bg + GMLSTUBS_COLOUR_OFFSET;
}

static inline const unsigned char* Gmlstubs_colourBytesConst(const RuntimeBackground* bg) {
    return (const unsigned char*)bg + GMLSTUBS_COLOUR_OFFSET;
}

#endif
