// depthmove (DELTARUNE only, CTRPORT_DEPTHMOVE): the element lists of automatic depth layers as a deque.
//
// Every depth change moves an instance's element to the front of an automatic layer (arrins at 0), and swarms of
// short-lived instances leave those layers oldest first. With a plain stb_ds array each insert shifts the whole list
// up one element (newlib's overlapping backward memmove moves one word per loop, against four forward: 9.3 ms of a
// DELTARUNE Old Titan frame).
// A list in an automatic layer of 16 or more elements gets free slots before its first element: the stb_ds header
// sits right before element 0 as always (length; capacity = slots from element 0 to the block's end) and its
// hash_table word, unused by stb_ds arrays, holds the block's start. Inserting at the front or taking the front
// element moves only the header. Element order, indices and contents are exactly those of the plain array, so every
// reader is unchanged; only the writers that free or grow these lists go through here (z_depthmove.c).
//
// Without CTRPORT_DEPTHMOVE (UNDERTALE) each macro is the original code.
#ifndef Z_DEPTHMOVE_H
#define Z_DEPTHMOVE_H

#if defined(CTRPORT_DEPTHMOVE)
#include <stddef.h>
void Depthmove_free(void* header);
void Depthmove_insertFront(RuntimeLayer* layer, const RuntimeLayerElement* el);
void Depthmove_append(RuntimeLayer* layer, const RuntimeLayerElement* el);
void Depthmove_delete(RuntimeLayer* layer, size_t index);
#define DEPTHMOVE_ARRFREE(a) ((void) ((a) ? Depthmove_free(stbds_header(a)) : (void) 0), (a) = NULL)
#define DEPTHMOVE_INSFRONT(layer, el) Depthmove_insertFront((layer), &(el))
#define DEPTHMOVE_APPEND(layer, el) Depthmove_append((layer), &(el))
// The instance's one element, searched from both ends (0, n-1, 1, n-2, ...): swarms leave oldest first, at the end.
#define DEPTHMOVE_J depthmoveScan
#define DEPTHMOVE_SCAN(j, n) size_t j = (depthmoveScan & 1) ? (n) - 1 - (depthmoveScan >> 1) : depthmoveScan >> 1;
#define DEPTHMOVE_DEL(layer, j) Depthmove_delete((layer), (j))
#if !defined(DEPTHMOVE_SOURCE)
#include <stdlib.h>
#include "stb_ds.h"
// Defined in runner.c's unit (only runner.c includes this header without DEPTHMOVE_SOURCE), not in z_depthmove.c:
// GCC then sees that it reads one stbds_array_header field and calls free, nothing else, so the callers of
// Runner_freeRuntimeLayer keep their base code (FreewinsRoom_free's dead-store elimination; with an unknown
// callee, or a bare void* load that may alias any pointer field, it grew 4 B and moved every later late function).
__attribute__((noinline, section(".text.late.depthmove"))) void Depthmove_free(void* header) {
    stbds_array_header* h = header;
    free(h->hash_table != NULL ? h->hash_table : h);
}
#if defined(__3DS__) && defined(__GNUC__)
// runner.o's .text.late.layerfix keeps the stage's 0x12a0 B (it is 0x11bc B with depthmove: the front insert, the
// own-layer removal and the depth move call z_depthmove.c), so every later late function keeps its address and
// 4 KiB set phase (dec-1031-setphase). The padding is subsection 1, after the section's code and literal pools.
__asm__(".pushsection .text.late.layerfix,\"ax\",%progbits\n.subsection 1\n.space 228\n.popsection\n");
#endif
#endif
#else
#define DEPTHMOVE_ARRFREE(a) arrfree(a)
#define DEPTHMOVE_INSFRONT(layer, el) arrins((layer)->elements, 0, el)
#define DEPTHMOVE_APPEND(layer, el) arrput((layer)->elements, el)
#define DEPTHMOVE_J j
#define DEPTHMOVE_SCAN(j, n)
#define DEPTHMOVE_DEL(layer, j) arrdel((layer)->elements, j)
#endif

#endif
