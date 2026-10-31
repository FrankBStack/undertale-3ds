// Game-frame budget for music transport. Included after ctr_loadaudio.inc.
// Logical voices/pauses, the decoder and PCM buffers stay with their owners.
#include "ctr_loadaudio_budget.inc"
#define LC_RO __attribute__((section(".rodata.late.loadaudio")))
enum { LC_PRESENT = 1, LC_MUSIC = 2, LC_LOOP = 4, LC_PAUSED = 8, LC_PROVISIONAL = 16 };

typedef struct {
    uint32_t version, serial, epoch, seconds, anchor, flags;
} LaClockPublication;

typedef struct {
    uint32_t serial, epoch, seconds, anchor, flags;
} LaClockSnapshot;

typedef struct {
    uint32_t serial, frame;
    float offset;
    bool known, ready;
} LaClockOrigin;

typedef struct {
    uint64_t source, length, tick;
    uint32_t rate;
    float physicalRate;
    int physical;
    bool observed;
} LaClockSource;

// No new compiler edges into old functions or old BSS: retain their layout.
extern const struct {
    int (*physical)(int);
    void (*pause)(int, bool);
    LightLock* lock;
    UtaChan* channels;
    ndspWaveBuf (*buffers)[UTA_RING];
} CtrLoadaudio_clockLegacy;
#ifndef LC_HOST
__asm__(".pushsection .rodata.late.loadaudio,\"a\",%progbits\n.p2align 2\n"
        ".global CtrLoadaudio_clockLegacy\n.type CtrLoadaudio_clockLegacy,%object\n"
        "CtrLoadaudio_clockLegacy:\n.word utaPhys,utaChnSetPaused,utaLock,utaChan,utaWb\n"
        ".size CtrLoadaudio_clockLegacy,.-CtrLoadaudio_clockLegacy\n.popsection\n");
#endif

static struct {
    CtrAudioSystem* audio;
    ndspCallback callback;
    void (*seek)(AudioSystem*, int32_t, float);
    float (*position)(AudioSystem*, int32_t);
    int32_t (*play)(AudioSystem*, int32_t, int32_t, bool);
    CtrAudioSystem* installed; // original play table is already beneath a later worker's outer table
    Runner* runner; // game thread only; frameCount advances at the end of Step
    LaClockOrigin origin[VOICE_COUNT]; // game thread only
    LaClockPublication published[VOICE_COUNT]; // game thread writes atomic words
    LaBudget budget[VOICE_COUNT]; // callback only
    uint64_t since[VOICE_COUNT]; // last valid source observation
    uint32_t identity[VOICE_COUNT], epoch[VOICE_COUNT];
    uint32_t heldSerial[VOICE_COUNT];
    bool held[VOICE_COUNT];
    uint32_t unknown; // callback diagnostic; never turns a failed observation into a PASS
} lc LA_BSS;

static const char lcMusic[] LC_RO = "mus_", lcEffect[] LC_RO = "mus_sfx_", lcOther[] LC_RO = "zz_";

LA_TEXT static uint32_t lcBits(float value) {
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return bits;
}

LA_TEXT static float lcFloat(uint32_t bits) {
    float value;
    memcpy(&value, &bits, sizeof(value));
    return value;
}

LA_TEXT static float lcPitch(float pitch) {
    return pitch < 0.01f ? 0.01f : pitch > 8 ? 8 : pitch;
}

LA_TEXT static bool lcEnabled(void) {
#ifdef CTR_AUDIO_PCM_HASH
    return latGateOn();
#else
    return true;
#endif
}

LA_TEXT static bool lcMusicVoice(CtrAudioSystem* ca, const Voice* voice) {
    if (voice->kind == VOICE_FREE) return false;
    if (voice->soundIndex >= AUDIO_STREAM_INDEX_BASE) return true;
    if (voice->soundIndex < 0 || (uint32_t) voice->soundIndex >= ca->soundCount) return false;
    const char* name = ca->base.audioGroups[0]->sond.sounds[voice->soundIndex].name;
    return name != NULL && ((!strncmp(name, lcMusic, 4) && strncmp(name, lcEffect, 8)) || !strncmp(name, lcOther, 3));
}

// Every field is an atomic 32-bit word. Readers try once, without spinning;
// they cannot consume a torn game-thread double or half an authored seek.
LA_TEXT static bool lcSnapshot(unsigned id, LaClockSnapshot* out) {
    LaClockPublication* p = &lc.published[id];
    uint32_t before = __atomic_load_n(&p->version, __ATOMIC_ACQUIRE);
    if (before & 1) return false;
    out->serial = __atomic_load_n(&p->serial, __ATOMIC_RELAXED);
    out->epoch = __atomic_load_n(&p->epoch, __ATOMIC_RELAXED);
    out->seconds = __atomic_load_n(&p->seconds, __ATOMIC_RELAXED);
    out->anchor = __atomic_load_n(&p->anchor, __ATOMIC_RELAXED);
    out->flags = __atomic_load_n(&p->flags, __ATOMIC_RELAXED);
    __atomic_thread_fence(__ATOMIC_ACQUIRE);
    return before == __atomic_load_n(&p->version, __ATOMIC_RELAXED);
}

LA_TEXT static float lcSeconds(CtrAudioSystem* ca, unsigned id) {
    Voice* voice = &ca->voices[id];
    LaClockOrigin* origin = &lc.origin[id];
    float seconds = (float) voice->clockSeconds;
    if (origin->known && origin->ready && origin->serial == voice->serial) seconds -= origin->offset;
    return seconds > 0 ? seconds : 0;
}

LA_TEXT static void lcPublish(CtrAudioSystem* ca, unsigned id, bool seek) {
    Voice* voice = &ca->voices[id];
    LaClockPublication* p = &lc.published[id];
    uint32_t flags = LC_PRESENT;
    if (lcMusicVoice(ca, voice)) flags |= LC_MUSIC;
    if (voice->loop) flags |= LC_LOOP;
    if (voice->paused || ca->suspended) flags |= LC_PAUSED;
    bool fresh = !(p->flags & LC_PRESENT) || p->serial != voice->serial;
    LaClockOrigin* origin = &lc.origin[id];
    bool tracked = origin->known && origin->serial == voice->serial;
    if (tracked && !origin->ready && lc.runner != NULL) {
        // Step increments frameCount before Draw. A Draw request's first
        // update earns no elapsed frame; a Step request's first update does.
        uint32_t elapsed = (uint32_t) lc.runner->frameCount - origin->frame;
        origin->offset = (float) voice->clockSeconds - elapsed * (lcPitch(voice->pitch) / 30);
        if (origin->offset < 0) origin->offset = 0; // a pause before the first update earns no time
        origin->ready = true;
    }
    if (seek && tracked) { origin->offset = 0; origin->ready = true; }
    float seconds = lcSeconds(ca, id);
    // Cover the interval until the next picture. At submission a freshly
    // earned frame has not played yet. A tracked voice may spend at most
    // one following quantum, less the physical-control reserve, during a stall.
    if (tracked && !(flags & LC_PAUSED)) seconds += lcPitch(voice->pitch) / 30;
    uint32_t epoch = fresh ? 0 : p->epoch;
    uint32_t anchor = fresh ? lcBits(0.0f) : p->anchor;
    if (seek) { epoch++; anchor = lcBits((float) voice->clockSeconds); }
    uint32_t version = __atomic_load_n(&p->version, __ATOMIC_RELAXED);
    __atomic_store_n(&p->version, version + 1, __ATOMIC_SEQ_CST);
    __atomic_store_n(&p->serial, voice->serial, __ATOMIC_RELAXED);
    __atomic_store_n(&p->epoch, epoch, __ATOMIC_RELAXED);
    __atomic_store_n(&p->seconds, lcBits(seconds), __ATOMIC_RELAXED);
    __atomic_store_n(&p->anchor, anchor, __ATOMIC_RELAXED);
    __atomic_store_n(&p->flags, flags, __ATOMIC_RELAXED);
    __atomic_store_n(&p->version, version + 2, __ATOMIC_RELEASE);
}

LA_TEXT static void laClockFrame(CtrAudioSystem* ca, Runner* runner) {
    lc.runner = runner;
    if (!lcEnabled() || __atomic_load_n(&lc.audio, __ATOMIC_ACQUIRE) != ca) return;
    for (unsigned i = 0; i < VOICE_COUNT; i++) lcPublish(ca, i, false);
}

// A request may happen in Step/Draw before that frame's update publishes it.
// Credit only its current frame, so a warm sound starts at the authored call
// yet a stalled first frame cannot grant unlimited wall-clock playback.
LA_TEXT static bool lcCurrent(CtrAudioSystem* ca, unsigned id, LaClockSnapshot* out) {
    Voice* voice = &ca->voices[id];
    if (!lcSnapshot(id, out)) return false;
    bool music = lcMusicVoice(ca, voice);
    if ((out->flags & LC_PRESENT) && out->serial == voice->serial &&
        ((out->flags & LC_MUSIC) != 0) == music) return true;
    if (!music) return false;
    *out = (LaClockSnapshot){.serial = voice->serial, .seconds = lcBits(lcPitch(voice->pitch) / 30),
        .flags = LC_PRESENT | LC_MUSIC | LC_PROVISIONAL | (voice->loop ? LC_LOOP : 0)};
    return true;
}

LA_TEXT static bool lcMatches(const Voice* voice, int32_t sound) {
    return voice->kind != VOICE_FREE &&
        (sound >= SOUND_INSTANCE_ID_BASE && sound < AUDIO_STREAM_INDEX_BASE
            ? voice->instanceId == sound : voice->soundIndex == sound);
}

LA_TEXT static int32_t lcPlay(AudioSystem* audio, int32_t sound, int32_t priority, bool loop) {
    uint32_t frame = lc.runner != NULL ? (uint32_t) lc.runner->frameCount : 0;
    int32_t result = lc.play(audio, sound, priority, loop);
    if (!lcEnabled()) return result;
    CtrAudioSystem* ca = (CtrAudioSystem*) audio;
    for (unsigned i = 0; i < VOICE_COUNT; i++) {
        Voice* voice = &ca->voices[i];
        if (voice->kind != VOICE_FREE && voice->instanceId == result)
            lc.origin[i] = (LaClockOrigin){.serial = voice->serial, .frame = frame, .known = lc.runner != NULL};
    }
    return result;
}

LA_TEXT static void lcSeek(AudioSystem* audio, int32_t sound, float seconds) {
    lc.seek(audio, sound, seconds);
    CtrAudioSystem* ca = (CtrAudioSystem*) audio;
    for (unsigned i = 0; i < VOICE_COUNT; i++)
        if (lcMatches(&ca->voices[i], sound)) lcPublish(ca, i, true);
}

// PC-facing music position follows the same game-frame clock as the quota.
// Invoke the original query first for retirement and diagnostic invalid handles.
LA_TEXT static float lcPosition(AudioSystem* audio, int32_t sound) {
    float result = lc.position(audio, sound);
#ifdef CTR_AUDIO_PCM_HASH
    // Explicit diagnostic-only stall controls, identical in both selector arms.
    // They freeze game frames, not the DSP. Never count these as real-load or
    // in-play performance evidence. Adjacent marks 1..255 remain observations.
    if ((uint32_t) sound - 0x80000100u < 2u) {
        svcSleepThread(sound == INT32_MIN + 256 ? 1000000000LL : 100000000LL);
        return 0;
    }
#endif
    if (!lcEnabled()) return result;
    CtrAudioSystem* ca = (CtrAudioSystem*) audio;
    for (unsigned i = 0; i < VOICE_COUNT; i++) {
        Voice* voice = &ca->voices[i];
        if (!lcMatches(voice, sound) || !lcMusicVoice(ca, voice)) continue;
        float length = 0;
        if (voice->kind == VOICE_SFX && voice->sfx != NULL && voice->sfx->sampleRate)
            length = (float) voice->sfx->frames / voice->sfx->sampleRate;
        else if (voice->soundIndex >= 0 && (uint32_t) voice->soundIndex < ca->soundCount)
            length = ca->soundLengths[voice->soundIndex];
        else if (voice->soundIndex >= AUDIO_STREAM_INDEX_BASE &&
                 voice->soundIndex - AUDIO_STREAM_INDEX_BASE < MAX_STREAM_ENTRIES)
            length = ca->streamEntries[voice->soundIndex - AUDIO_STREAM_INDEX_BASE].lengthSeconds;
        float seconds = lcSeconds(ca, i);
        if (length <= 0) return seconds;
        if (voice->loop) return fmodf(seconds, length);
        return seconds < length ? seconds : length;
    }
    return result;
}

LA_TEXT static bool laClockPaused(int id) {
    if (!lcEnabled() || (unsigned) id >= VOICE_COUNT) return false;
    CtrAudioSystem* ca = __atomic_load_n(&lc.audio, __ATOMIC_ACQUIRE);
    if (ca == NULL || !lcMusicVoice(ca, &ca->voices[id])) return false;
    LaClockSnapshot p;
    if (lcSnapshot((unsigned) id, &p) && p.serial == ca->voices[id].serial &&
        (p.flags & LC_MUSIC) && lcFloat(p.seconds) <= lcFloat(p.anchor)) return true;
    return __atomic_load_n(&lc.held[id], __ATOMIC_ACQUIRE) &&
        __atomic_load_n(&lc.heldSerial[id], __ATOMIC_RELAXED) == ca->voices[id].serial;
}

#define LC_LIVE(wb) ((wb)->status == NDSP_WBUF_PLAYING || (wb)->status == NDSP_WBUF_QUEUED)

// Both locks are try-only. The caller owns them until its pause bit is applied,
// so a tail/channel remap cannot turn this observation into a hold of a new voice.
LA_TEXT static void lcSource(CtrAudioSystem* ca, unsigned id, StreamContext* stream, LaClockSource* out) {
    Voice* voice = &ca->voices[id];
    int physical = CtrLoadaudio_clockLegacy.physical((int) id);
    out->physical = physical;
    if (physical < 0 || physical >= UTA_CHANNELS) return;
    out->physicalRate = CtrLoadaudio_clockLegacy.channels[physical].rate;
    uint32_t seq = UTA_PHYS_SEQ(physical), raw = UTA_PHYS_POS(physical);
    if (stream != NULL && !stream->seekPending && !stream->stopRequested) {
        out->rate = stream->sampleRate; out->length = stream->totalFrames;
        for (unsigned j = 0; seq && j < STREAM_BUFFERS; j++) {
            StreamBuffer* b = &stream->bufs[j];
            if (LC_LIVE(&b->wb) && b->wb.sequence_id == seq) {
                out->source = b->startFrame + raw; out->observed = true; break;
            }
        }
    } else if (stream == NULL && voice->kind == VOICE_SFX && voice->sfx != NULL) {
        out->rate = voice->sfx->sampleRate; out->length = voice->sfx->frames;
        UtaChan* channel = &CtrLoadaudio_clockLegacy.channels[physical];
        for (unsigned j = 0; seq && j < UTA_RING; j++) {
            unsigned seg = channel->piece[j].seg;
            ndspWaveBuf* b = &CtrLoadaudio_clockLegacy.buffers[physical][j];
            if (LC_LIVE(b) && b->sequence_id == seq && seg < 2 &&
                channel->piece[j].kind != UTA_PIECE_TAIL && channel->seg[seg].mirror == &voice->wb[seg]) {
                out->source = raw + (uint64_t) channel->piece[j].off + voice->wbStart[seg];
                out->observed = true; break;
            }
        }
        for (int j = 0; !out->observed && seq && channel->state == UTA_IDLE && j < voice->wbCount; j++) {
            if (LC_LIVE(&voice->wb[j]) && voice->wb[j].sequence_id == seq) {
                out->source = raw + (uint64_t) voice->wbStart[j]; out->observed = true;
            }
        }
    }
    out->tick = svcGetSystemTick();
    if (seq != UTA_PHYS_SEQ(physical) || !out->length || !out->rate) out->observed = false;
    if (out->observed && voice->loop) out->source %= out->length;
}

LA_TEXT static void lcMiss(CtrAudioSystem* ca, unsigned id, uint32_t serial) {
    lc.unknown++;
    __atomic_store_n(&lc.heldSerial[id], serial, __ATOMIC_RELAXED);
    __atomic_store_n(&lc.held[id], true, __ATOMIC_RELEASE);
    // Do not wait behind a source lock. Try the physical hold independently;
    // a busy mapping remains a failed observation, never a timing PASS.
    if (LightLock_TryLock(CtrLoadaudio_clockLegacy.lock) != 0) return;
    int physical = CtrLoadaudio_clockLegacy.physical((int) id);
    if (physical >= 0 && physical < UTA_CHANNELS && ca->voices[id].serial == serial && lcMusicVoice(ca, &ca->voices[id]))
        CtrLoadaudio_clockLegacy.pause((int) id, true);
    LightLock_Unlock(CtrLoadaudio_clockLegacy.lock);
}

LA_TEXT static void lcTransport(CtrAudioSystem* ca, unsigned id, const LaClockSnapshot* p) {
    Voice* voice = &ca->voices[id];
    StreamContext* stream = NULL;
    if (voice->serial != p->serial) return;
    if (voice->kind == VOICE_STREAM && (unsigned) voice->ctx < STREAM_CONTEXTS) {
        stream = &ca->streams[voice->ctx];
        if (LightLock_TryLock(&stream->lock) != 0) { lcMiss(ca, id, p->serial); return; }
    } else if (voice->kind != VOICE_SFX) return;
    if (LightLock_TryLock(CtrLoadaudio_clockLegacy.lock) != 0) {
        if (stream != NULL) LightLock_Unlock(&stream->lock);
        lcMiss(ca, id, p->serial); return;
    }
    LaClockSource source = {0};
    lcSource(ca, id, stream, &source);
    bool fresh = lc.identity[id] != p->serial || lc.epoch[id] != p->epoch || !lc.since[id];
    if (fresh) {
        lc.identity[id] = p->serial; lc.epoch[id] = p->epoch; lc.since[id] = source.tick;
        lc.budget[id].valid = false;
    }
    bool held = lcFloat(p->seconds) <= lcFloat(p->anchor);
    if (source.observed) {
        double physicalRate = source.physicalRate > 0 ? source.physicalRate : source.rate * lcPitch(voice->pitch);
        uint64_t reserve = (uint64_t) (physicalRate * 0.017);
        // Pitch is bounded to 8 by the existing transport. A generous bound
        // rejects ambiguous whole-loop observations without inventing cycles.
        uint64_t span = (uint64_t) ((double) (source.tick - lc.since[id]) * source.rate * 8 / SYSCLOCK_ARM11)
            + reserve;
        uint64_t anchor = (uint64_t) ((double) lcFloat(p->anchor) * source.rate);
        uint64_t quota = (uint64_t) ((double) lcFloat(p->seconds) * source.rate);
        int decision = laBudgetStep(&lc.budget[id], p->serial, p->epoch, anchor,
            source.source, source.length, (p->flags & LC_LOOP) != 0, span, quota, reserve);
        if (decision == LA_BUDGET_UNKNOWN) { lc.unknown++; held = true; }
        else { held = decision == LA_BUDGET_HOLD; lc.since[id] = source.tick; }
    } else if (lc.budget[id].valid && !fresh) {
        lc.unknown++; held = true;
    }
    // A cold, still-unstarted channel may run once it has earned quota; a
    // sequence of zero cannot provide the first progress while paused forever.
    LaClockSnapshot check;
    if (source.physical >= 0 && source.physical < UTA_CHANNELS && voice->serial == p->serial &&
        lcCurrent(ca, id, &check) && check.serial == p->serial && check.epoch == p->epoch) {
        __atomic_store_n(&lc.heldSerial[id], p->serial, __ATOMIC_RELAXED);
        __atomic_store_n(&lc.held[id], held, __ATOMIC_RELEASE);
        bool logical = (check.flags & LC_PAUSED) || voice->paused || ca->suspended;
        CtrLoadaudio_clockLegacy.pause((int) id, logical);
    }
    LightLock_Unlock(CtrLoadaudio_clockLegacy.lock);
    if (stream != NULL) LightLock_Unlock(&stream->lock);
}

LA_TEXT static void lcCallback(void* data) {
    CtrAudioSystem* ca = __atomic_load_n(&lc.audio, __ATOMIC_ACQUIRE);
    if (ca == NULL || ca != data) return;
    if (lcEnabled()) for (unsigned i = 0; i < VOICE_COUNT; i++) {
        LaClockSnapshot p;
        if (lcCurrent(ca, i, &p)) {
            if (p.flags & LC_MUSIC) lcTransport(ca, i, &p);
        } else if (lcMusicVoice(ca, &ca->voices[i])) lcMiss(ca, i, ca->voices[i].serial);
    }
    lc.callback(data);
}

LA_TEXT static ndspCallback laClockRegister(ndspCallback callback, void* data) {
    __atomic_store_n(&lc.audio, NULL, __ATOMIC_RELEASE);
    if (callback == NULL) return NULL;
    CtrAudioSystem* ca = (CtrAudioSystem*) data;
    memset(lc.published, 0, sizeof(lc.published));
    memset(lc.budget, 0, sizeof(lc.budget));
    memset(lc.since, 0, sizeof(lc.since));
    memset(lc.held, 0, sizeof(lc.held));
    memset(lc.origin, 0, sizeof(lc.origin));
    lc.runner = NULL;
    lc.unknown = 0;
    lc.callback = callback;
    if (lc.installed != ca && ca->base.vtable->playSound != lcPlay) {
        lc.play = ca->base.vtable->playSound;
        ca->base.vtable->playSound = lcPlay;
    }
    lc.installed = ca;
    // Install before the worker takes a copy of the base vtable. On re-init the
    // original entry remains saved; never wrap our wrapper into itself.
    if (ca->base.vtable->setTrackPosition != lcSeek) {
        lc.seek = ca->base.vtable->setTrackPosition;
        ca->base.vtable->setTrackPosition = lcSeek;
    }
    if (ca->base.vtable->getTrackPosition != lcPosition) {
        lc.position = ca->base.vtable->getTrackPosition;
        ca->base.vtable->getTrackPosition = lcPosition;
    }
    __atomic_store_n(&lc.audio, ca, __ATOMIC_RELEASE);
    return lcCallback;
}

#ifdef CTR_AUDIO_PCM_HASH
// Game-thread checkpoint only. Callback-owned 64-bit budget fields are not
// read here: that would risk a torn diagnostic on ARM11. All shared words
// below use the same atomic reads as the production publication/hold path.
LA_TEXT static void latClock(unsigned id, uint32_t* words) {
    LaClockOrigin* origin = &lc.origin[id];
    LaClockSnapshot p;
    CtrAudioSystem* ca = __atomic_load_n(&lc.audio, __ATOMIC_ACQUIRE);
    bool valid = lcSnapshot(id, &p);
    words[0] = valid ? p.seconds : 0;
    words[1] = origin->frame;
    words[2] = lcBits(origin->offset);
    words[3] = (origin->known ? 1u : 0u) | (origin->ready ? 2u : 0u) |
        (ca != NULL && origin->serial == ca->voices[id].serial ? 4u : 0u) |
        (valid && ca != NULL && p.serial == ca->voices[id].serial ? 8u : 0u);
    words[4] = __atomic_load_n(&lc.held[id], __ATOMIC_ACQUIRE);
    words[5] = valid ? p.epoch : 0;
}
#endif
