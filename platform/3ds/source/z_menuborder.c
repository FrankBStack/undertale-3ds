// UNDERTALE's white frame is 6 PC pixels / 3 native pixels (menuborder PC captures). Keep the outer 320 x 240
// rectangle, and add its third pixel inward. All framed pages share this copy, including Controls and Legal;
// Credits uses a bare page. As in credclip, the first pixel identifies a framed page. Paint the spare page too,
// so the live counter restores the thicker frame from the same backdrop. No new state or earlier code growth.
// Separate TU: a local callee changes GCC's order of the original optmenu bodies (docs/3ds-hardware.md).
#include <stdint.h>
#include <string.h>

#if defined(ENABLE_WAD16)
#define MENUBORDER_CODE __attribute__((noinline, noipa, optimize("Os"), section(".text_menuborder")))
void* CtrMenuborder_copy(void* to, const void* from, size_t bytes);
MENUBORDER_CODE void* CtrMenuborder_copy(void* to, const void* from, size_t bytes) {
    uint16_t* fb = (uint16_t*) from; // optCopyShown's writable spare page; its memcpy ABI is retained
    if (bytes == 320u * 240u * sizeof(*fb) && fb[0] == 0xFFFFu) {
        for (uint32_t x = 2; x < 318; x++) {
            fb[x * 240u + 2u] = fb[x * 240u + 237u] = 0xFFFFu;
        }
        for (uint32_t y = 3; y < 237; y++) {
            fb[2u * 240u + y] = fb[317u * 240u + y] = 0xFFFFu;
        }
    }
    return memcpy(to, from, bytes);
}
#endif
