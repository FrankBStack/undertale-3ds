// samestart (change audiomain, 11-15, from maintainer's Old 3DS report of the SOUL's battle-entry sound playing twice, "one
// started slightly after the other"; included at ctr_audio_system.c's end, UNDERTALE only): two plays of one sound in
// one game step sound as one.
//
// UNDERTALE plays some sounds twice in one step (the SOUL's entry plays its sound, then plays it again in the same
// Create). On PC both start in the same audio frame and sum. Here each play queues its sound's first piece on the game
// thread (utaChnWaveBufAdd under utaLock, then utaFeed), and libctru's NDSP thread (priority 0x18, the game thread's
// core) sends what is queued at each DSP frame (4.89 ms). When it runs between the two plays (Old 3DS about 6% of
// entries, New about 1.5%: the plays are 0.29 / 0.07 ms apart), the second starts a whole DSP frame after the first:
// the #53 witness logs show the second voice trailing by 215 samples (44.1 kHz) at every update.
//
// The fix moves the second start's window, not its time: libctru's physical add is wrapped (CMakeLists.txt, UNDERTALE),
// and at the first piece of a sound (game thread, segment 0 from its start, nothing played or queued before it) the
// DSP publications so far (sameStart.pass) are noted for its voice. A publication is libctru's ndspiUpdateChn, which
// the NDSP thread runs after the frame callback: it sends each channel's queued buffers to the DSP, channel by
// channel, each under that channel's lock. It is wrapped too (r4, review c26rev7 SS-1): when uta runs, it runs under
// utaLock and counts itself there. The game thread holds utaLock from the count to the add, so no publication is under
// way or can start in between, and a piece added while the count reads N goes to the DSP in publication N + 1, on any
// core and whatever else holds a channel lock. (r1-r3 counted frame callbacks (utaCb): the callback takes utaLock
// before the publication but drops it before libctru sends anything, so an add could land between the two, and a
// publication blocked on a channel lock that a decode thread holds (New: core 2; Old: core 1) let the game thread add
// both plays meanwhile; then the count said one frame apart for two buffers sent together, or the same for two sent
// apart.) Lock order: the NDSP thread already takes channel locks under utaLock (the callback's feed adds), and no
// thread takes utaLock while it holds a channel lock (only libctru's ndspChn* functions hold one, and they call no code
// of this port's), so the wrap adds no new order.
// When another voice already plays the same sound from the same start, at the same rate and pitch, both unpaused and
// not looping, its first piece added in this same step and its sound not done, and L = the count - its count is 1 or
// more, this piece starts L x 160 x rate / 32728.498 samples into the sound (rounded; the DSP's 160-sample frame at
// its output rate, rate = the channel's sample rate x pitch): 107.8 per frame at 22050 Hz, 160.0 at 32728 Hz,
// 215.6 at 44100 Hz, within half a sample for any L. The window keeps the piece's length (shorter only at the
// sound's end, with uta's rule that no piece follows within a DSP frame of the end) and the feed goes on after it;
// the piece's offset in its segment says where it starts, so the position the game reads is the first voice's.
// Any doubt is a plain add (as before): another thread, no record, a different sound, start, rate or pitch, a paused
// or suspended voice, a loop, the first voice's sound done, or fewer than a DSP frame of the sound left after the
// shift. A third play lines up with the first (a shifted voice keeps the first's count).
// Room loads (r5, review c26rev7 SS-2): play-through (ctr_loadaudio_mix.inc ptHeld, ptPhysPaused) pauses on the
// channel, not in the voice or uta flags, every sound started inside an open room-change window, until the window
// closes; then ptDspCallback unpauses them all in one callback, so they start together from sample 0. Publications
// in between are no progress for such a voice. So a first piece on a held channel is a plain add and leaves no
// record (nothing lines up with it). A voice not held at its first piece never becomes held after: a play inside an
// open window is always held (its serial moved after the snapshot), and a window that opens later snapshots its
// serial. (The whole-mix hold, lmCallback's, never comes: play-through credits it away. gomusic's and loadclass's
// holds are for stream contexts' channels.)
// UNDERTALE Old's packed ADPCM sounds are decoded per piece (ctr_adpcm_sfx_pieces.inc): the piece is decoded again
// from the shifted start into its own slot (adRead, then adFlush); a failed decode puts the original piece back.
// Code placed per model through ctr_place.h's UT_COLD_TEXT (lead 11-15: late text is the scarcest region): UNDERTALE
// Old, the AAC text slot's last tenant (.aacout.text.samestart); New, an appended late section (.text_samestart).
// State 292 B late bss (.bss.samestart_late, carved from sdmigrate's placeholder, z_sdmigrate.c SM_CARVE_SAMESTART).
// The uta statics are reached through address words loaded inside the functions, and uta's and adpcm's functions by
// their assembler names (lcstop's and soulahead's pattern): a new C reference would reorder the file's existing code
// and data.
#if defined(ENABLE_WAD16)
#include "ctr_place.h"
#define SAMESTART_CODE __attribute__((noinline, noipa, optimize("Os"))) UT_COLD_TEXT(samestart)
#ifndef SAMESTART_ADDR // (a host test supplies its own)
#define SAMESTART_ADDR(type, name) ({ type* at_; __asm__ volatile("ldr %0, 1f\n\tb 2f\n1:\t.word " #name "\n2:" : "=r"(at_) : : "memory"); at_; })
#endif
#define SAMESTART_MAX_LAG 64u // DSP frames (313 ms): more than a step's worth is never the same step's play
#define SAMESTART_DSP_RATE 32728.498f // UTA_DSP_RATE

typedef struct {
    int32_t instanceId; // the voice's instance when its first piece was added (0: none)
    uint32_t pass; // the publications then (a shifted voice: the first voice's)
    int32_t step; // the runner's frame count then
} SameStartRec;
static struct {
    SameStartRec recs[VOICE_COUNT];
    uint32_t pass; // ndspiUpdateChn's runs under utaLock (the wrap below), read and written under utaLock only
} sameStart __attribute__((section(".bss.samestart_late")));
#define sameStartRecs sameStart.recs
_Static_assert(sizeof(sameStart) == 292, "samestart's late bss is the 292 B carved in z_sdmigrate.c");
_Static_assert(sizeof(void*) != 4 || sizeof(ndspWaveBuf) * UTA_CHANNELS * UTA_RING == 4608,
               "utaWb's size (the wrap's range test, one compare immediate)");

Runner* CtrHeldslow_liveRunner(void);
void __real_ndspChnWaveBufAdd(int id, ndspWaveBuf* buf);
void __wrap_ndspChnWaveBufAdd(int id, ndspWaveBuf* buf);
void __real_ndspiUpdateChn(void);
void __wrap_ndspiUpdateChn(void);
bool sameStartPtHeld(int p) __asm__("ptHeld"); // play-through's room-load hold (ctr_loadaudio_mix.inc)
#ifdef CTRPORT_ADPCM_SFXPACK
bool sameStartAdRead(AdSfxPhysical* p, uint32_t first, uint32_t count, int16_t* out, unsigned channels) __asm__("adRead");
void sameStartAdFlush(const void* data, uint32_t bytes) __asm__("adFlush");
#endif

// The first piece's window, moved lag DSP frames into the sound. False: unchanged (a plain add).
SAMESTART_CODE static bool sameStartShift(int p, UtaChan* c, uint32_t k, ndspWaveBuf* w, uint32_t lag) {
    (void) p; // (the pack's decode only)
    UtaSeg* g = &c->seg[0];
    uint32_t n = w->nsamples;
    float exact = (float) lag * 160.0f * c->rate / SAMESTART_DSP_RATE;
    uint32_t frame = (uint32_t) (160.0f * c->rate / SAMESTART_DSP_RATE) + 1u; // source frames in a DSP frame
    if (!(exact >= 0.5f) || !(exact < (float) g->frames)) return false;
    uint32_t off = (uint32_t) (exact + 0.5f);
    if (off >= g->frames || g->frames - off < frame || n == 0) return false;
    uint32_t m = n;
    if (m + frame > g->frames - off) m = g->frames - off; // uta's rule: no piece within a DSP frame of the end
#ifdef CTRPORT_ADPCM_SFXPACK
    __typeof__(adSfx)* ad = SAMESTART_ADDR(__typeof__(adSfx), adSfx);
    AdSfxPhysical* a = &ad->physical[p];
    if (a->meta) {
        uint32_t capacity = a->ring ? a->ring->frames : AS_PIECE_FRAMES;
        if (m > capacity) m = capacity;
        int16_t* dst = (int16_t*) w->data_vaddr;
        if (!sameStartAdRead(a, a->start[0] + off, m, dst, c->chans)) {
            if (sameStartAdRead(a, a->start[0], n, dst, c->chans)) sameStartAdFlush(dst, n * c->bytes);
            return false;
        }
        sameStartAdFlush(dst, m * c->bytes);
    } else
#endif
    {
        if (w->data_vaddr != g->data) return false;
        w->data_vaddr = g->data + off * c->bytes;
    }
    w->nsamples = m;
    c->piece[k].off = off;
    c->off = off + m - n; // utaFeed adds n next: the cursor is then the window's end
    return true;
}

// The voice that played this sound first in this step, or -1.
SAMESTART_CODE static int sameStartFirst(CtrAudioSystem* ca, int id, const UtaChan* c, int32_t step) {
    UtaChan* chans = SAMESTART_ADDR(UtaChan, utaChan);
    int8_t* inv = SAMESTART_ADDR(int8_t, utaInv);
    const Voice* v = &ca->voices[id];
    const UtaSeg* g = &c->seg[0];
    if (v->loop || v->paused || ca->suspended || c->paused || g->looping) return -1;
    for (int j = 0; j < VOICE_COUNT; j++) {
        const SameStartRec* r = &sameStartRecs[j];
        const Voice* u = &ca->voices[j];
        if (j == id || r->instanceId == 0 || r->instanceId != u->instanceId || r->step != step) continue;
        if (u->kind != VOICE_SFX || u->sfx != v->sfx || u->loop || u->paused || u->pitch != v->pitch ||
            u->wbStart[0] != v->wbStart[0] || u->wb[0].status == NDSP_WBUF_DONE) continue;
        int q = -1;
        for (int x = 0; x < UTA_CHANNELS; x++) {
            if (inv[x] == j) q = x;
        }
        if (q < 0) continue;
        if (sameStartPtHeld(q)) continue; // (never, as it was not held at its own add: see sameStartPiece)
        const UtaChan* d = &chans[q];
        const UtaSeg* h = &d->seg[0];
        if (d->state != UTA_FEED || d->paused || d->segs != 1 || d->rate != c->rate || h->mirror != &u->wb[0] ||
            h->data != g->data || h->frames != g->frames || h->looping) continue;
        return j;
    }
    return -1;
}

// A piece of utaWb on its way to the DSP (utaQueue's add, under utaLock).
SAMESTART_CODE static void sameStartPiece(int p, ndspWaveBuf* w) {
    if (threadGetCurrent() != NULL) return; // the game thread only (the main thread has no libctru thread)
    uint32_t index = (uint32_t) (w - SAMESTART_ADDR(ndspWaveBuf, utaWb));
    uint32_t k = index % UTA_RING;
    if (index / UTA_RING != (uint32_t) p) return;
    UtaChan* c = &SAMESTART_ADDR(UtaChan, utaChan)[p];
    if (c->state != UTA_FEED || c->segs != 1 || c->cur != 0 || c->off != 0 || c->started ||
        c->piece[k].kind != UTA_PIECE_SOUND || c->piece[k].seg != 0 || c->piece[k].off != 0) return;
    CtrAudioSystem* ca = *SAMESTART_ADDR(CtrAudioSystem*, utaCa);
    int id = SAMESTART_ADDR(int8_t, utaInv)[p];
    if (ca == NULL || id < 0 || id >= VOICE_COUNT) return;
    Voice* v = &ca->voices[id];
    Runner* runner = CtrHeldslow_liveRunner();
    if (v->kind != VOICE_SFX || v->sfx == NULL || c->seg[0].mirror != &v->wb[0] || runner == NULL) return;
    if (sameStartPtHeld(p)) { // r5 (c26rev7 SS-2): held for the room load, it starts at the window's close
        sameStartRecs[id].instanceId = 0; // no record: no later play lines up with it
        return;
    }
    int32_t step = (int32_t) runner->frameCount;
    uint32_t pass = sameStart.pass; // still: a publication runs under utaLock, held here until the add
    uint32_t base = pass;
    int j = sameStartFirst(ca, id, c, step);
    if (j >= 0) {
        uint32_t lag = pass - sameStartRecs[j].pass;
        if (lag == 0 || (lag <= SAMESTART_MAX_LAG && sameStartShift(p, c, k, w, lag))) base = sameStartRecs[j].pass;
    }
    sameStartRecs[id].instanceId = v->instanceId;
    sameStartRecs[id].pass = base;
    sameStartRecs[id].step = step;
}

// libctru's publication (ndspThreadMain after the frame callback; ndspInitialize at start and wake): under utaLock
// while uta runs, counted there. Before uta starts and after it stops (utaActive false; the lock is set up before it
// goes true) a plain call: no first piece is added then.
__attribute__((optimize("Os"))) UT_COLD_TEXT(samestart) void __wrap_ndspiUpdateChn(void) {
    LightLock* lock = SAMESTART_ADDR(LightLock, utaLock);
    if (!*SAMESTART_ADDR(volatile bool, utaActive)) {
        __real_ndspiUpdateChn();
        return;
    }
    LightLock_Lock(lock);
    __real_ndspiUpdateChn();
    sameStart.pass++;
    LightLock_Unlock(lock);
}

// Every physical add (streams, the decode thread's, every piece): only uta's pieces go further than the range test.
__attribute__((optimize("Os"))) UT_COLD_TEXT(samestart) void __wrap_ndspChnWaveBufAdd(int id, ndspWaveBuf* buf) {
    uintptr_t at = (uintptr_t) buf - (uintptr_t) SAMESTART_ADDR(ndspWaveBuf, utaWb);
    if (at < sizeof(ndspWaveBuf) * UTA_CHANNELS * UTA_RING) sameStartPiece(id, buf);
    __real_ndspChnWaveBufAdd(id, buf);
}
#endif
