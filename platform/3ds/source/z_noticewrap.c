// Setup notices (polish audit, 11-06): the path on a line of its own and no word cut,
// and advice for the case: players use the builder, and missing music has nothing to do with DSP firmware.
//
// main.c's loop prints what CtrNotice_first returns with a line break every 38 characters, and main.c's text is frozen,
// so its calls and the callers of CtrNotice_missing are wrapped (CMakeLists.txt): the text is laid out here in rows of
// exactly 38, spaces padding each row. It lives in the notice itself, in the rest of the key's buffer after its NUL,
// so the key that settings.ini remembers as dismissed is unchanged; a key too long to leave room is shown as it is.
// ctr_notice.c's code is unchanged, both old functions stay linked (noticeKeep) and this file is late code only.
#include <stddef.h>
#include <string.h>

#include "ctr_notice.h"

#if defined(__3DS__) && defined(__GNUC__)
#define NOTICE_LATE __attribute__((noinline, section(".text_menupress")))
#define NOTICE_RO __attribute__((section(".rodata.menupress_in_text")))
#else
#define NOTICE_LATE
#define NOTICE_RO
#endif

enum { NOTICE_COLS = 38, NOTICE_KEY_BYTES = 768 }; // ctr_notice.c's Notice.key (test_notice_layout.py checks it)

const char* __real_CtrNotice_first(void);
void __real_CtrNotice_missing(const char* kind, const char* path);
const char* __wrap_CtrNotice_first(void);
void __wrap_CtrNotice_missing(const char* kind, const char* path);

#if defined(__3DS__) && defined(__GNUC__)
// Nothing calls the old CtrNotice_missing now: this keeps it linked (late_reserve.ld's KEEP), so nothing after it moves.
__attribute__((used, section(".rodata.noticekeep_in_text"))) static const void* const noticeKeep = (const void*) __real_CtrNotice_missing;
#endif

static const char noticeSeparator[] NOTICE_RO = ": ";
static const char noticeBreaks[] NOTICE_RO = " /";
static const char noticeDsp[] NOTICE_RO = "DSP";
static const char noticeRunDsp1[] NOTICE_RO = "Run DSP1 once on this console.";
static const char noticeRunBuilder[] NOTICE_RO = "Run the builder again.";

// The text's pieces, each up to and including its next space or slash, in rows of NOTICE_COLS: a piece that fits on a row
// is never cut, one longer than a whole row (no break in it) has to be. Returns the bytes written, 0 if they don't fit.
NOTICE_LATE static size_t noticeLayout(char* out, size_t room, const char* text, size_t length) {
    size_t used = 0, col = 0;
    for (size_t at = 0; at < length;) {
        size_t piece = strcspn(text + at, noticeBreaks) + 1;
        if (piece > length - at) piece = length - at;
        if (col != 0 && col + piece > NOTICE_COLS) {
            if (used + NOTICE_COLS - col >= room) return 0;
            memset(out + used, ' ', NOTICE_COLS - col);
            used += NOTICE_COLS - col;
            col = 0;
        }
        if (used + piece >= room) return 0;
        memcpy(out + used, text + at, piece);
        used += piece;
        at += piece;
        col = (col + piece) % NOTICE_COLS;
    }
    return used;
}

NOTICE_LATE const char* __wrap_CtrNotice_first(void) {
    const char* key = __real_CtrNotice_first();
    if (key == NULL) return NULL;
    size_t keyLength = strlen(key);
    const char* gap = strstr(key, noticeSeparator);
    if (gap == NULL) return key;
    // The notice's own buffer, not a constant: the key is calloc'd by ctr_notice.c with this many bytes.
    char* out = (char*) key + keyLength + 1;
    size_t room = NOTICE_KEY_BYTES - keyLength - 1;
    size_t kind = (size_t) (gap - key) + 1; // with its colon
    size_t used = noticeLayout(out, room, key, kind);
    if (used == 0) return key;
    size_t pad = (NOTICE_COLS - used % NOTICE_COLS) % NOTICE_COLS; // the path starts a row
    if (used + pad >= room) return key;
    memset(out + used, ' ', pad);
    used += pad;
    size_t path = noticeLayout(out + used, room - used, gap + 2, keyLength - kind - 1);
    if (path == 0) return key;
    out[used + path] = '\0';
    return out;
}

NOTICE_LATE void __wrap_CtrNotice_missing(const char* kind, const char* path) {
    CtrNotice_report(kind, path, strstr(kind, noticeDsp) != NULL ? noticeRunDsp1 : noticeRunBuilder);
}
