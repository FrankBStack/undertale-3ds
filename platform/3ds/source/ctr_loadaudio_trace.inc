// pcmhash + UNDERTALE only. Bounded RAM observations; no callback/opener I/O.
// This is a diagnostic, not part of the 716 B production gate's price.
#define LAT_BSS __attribute__((section(".bss.late.loadaudio")))
#define LAT_CONST __attribute__((section(".rodata.late.loadaudio")))
#define LAT_REQUESTS 512
#define LAT_LOADS 64
#define LAT_POINTS 1024

typedef struct {
    uint32_t serial, slot, load, frame;
    int32_t sound;
    u64 request, queue, progress;
    u64 openBegin, openEnd, fillBegin, fillEnd, readTicks;
    uint32_t sample, submitSample;
    uint32_t queueSeq, progressSeq;
    uint32_t queueFrames;
    float queueRate;
    char name[64];
    bool queueReady, progressReady, submitObserved, printed, openReady, callObserved;
} LatVoice;
typedef struct {
    u64 begin, end, submit;
    uint32_t frame, submitFrame;
    int32_t from, to;
    bool printed;
} LatLoad;
typedef struct {
    uint32_t mark, requestedFrame, frame, voice, rate, raw, seq;
    u64 tick, source, total;
    double clock;
    float pitch;
    uint32_t transport[6]; // quota bits, origin frame/offset bits, validity, hold, seek epoch
    bool loop, paused, observed, printed;
} LatPoint;
static struct {
    Runner* runner;
    CtrAudioSystem* audio;
    LatVoice voices[LAT_REQUESTS];
    LatLoad loads[LAT_LOADS];
    LatPoint points[LAT_POINTS];
    uint32_t current[VOICE_COUNT]; // index + 1, published before any queue
    uint32_t used, loadCount, overflow;
    uint32_t pointCount, mark, markFrame;
    u64 callTick;
    int32_t callSound;
    CtrAudioSystem* callAudio;
    bool frameReady;
    bool overflowPrinted;
} lat LAT_BSS;
static const char latLoadFormat[] LAT_CONST =
    "[loadaudio] load %lu from %ld to %ld frame %lu submit_frame %lu begin %llu end %llu submit %llu hold %u\n";
static const char latVoiceFormat[] LAT_CONST =
    "[loadaudio] voice %lu load %lu slot %lu serial %lu sound %ld request %llu queue %llu progress %llu sample %lu submit_sample %lu submit_observed %u name '%s'\n";
static const char latOverflowFormat[] LAT_CONST = "[loadaudio] overflow %lu; incomplete observation\n";
// Compact versioned fields; decoded/named by loadaudio_sync.py. Diagnostic
// constants share the fixed Old reserve, so repeated labels waste that budget.
// v2: voice,frame,call,open begin/end,read begin/end/ticks,queue/progress seq,
//     first queue frames,physical rate.
static const char latPhasesFormat[] LAT_CONST =
    "[latency] v2 %lu %lu %u %llu %llu %llu %llu %llu %lu %lu %lu %.6f\n";
// m3: m2 fields, then six transport words. These diagnose publication/hold
// phase independently of the physical source; they never replace that source.
static const char latPointFormat[] LAT_CONST =
    "[latency] m3 %lu %lu %lu %lu %llu %lu %llu %llu %lu %lu %.9f %.6f %u %u %u %lu %lu %lu %lu %lu %lu\n";
static const char latMusicPrefix[] LAT_CONST = "mus_", latOtherPrefix[] LAT_CONST = "zz_";
static const char latUnknown[] LAT_CONST = "?";
static const char latNameFormat[] LAT_CONST = "%s";

LAT_CODE static void latReset(void) {
    // Retain historical rows for the later drain; invalidate their live slots.
    lat.runner = NULL;
    lat.frameReady = false;
    lat.mark = 0;
    lat.callAudio = NULL;
    __atomic_store_n(&lat.audio, NULL, __ATOMIC_RELEASE);
    for (unsigned i = 0; i < VOICE_COUNT; i++) __atomic_store_n(&lat.current[i], 0, __ATOMIC_RELEASE);
}

LAT_CODE static bool latGateOn(void) {
#if defined(CTRPORT_LOADAUDIO_CONTROL) || defined(CTRPORT_LOADAUDIO_OBSERVER_ONLY)
    return false;
#else
    return true;
#endif
}

// The game's new logical voice, before startVoiceSource can queue any audio.
LAT_CODE static void latRequest(CtrAudioSystem* ca, int id) {
    if (lat.runner == NULL || lat.loadCount == 0 || !ca->ndspReady) return;
    int32_t sound = ca->voices[id].soundIndex;
    const char* name = latUnknown;
    if (sound >= AUDIO_STREAM_INDEX_BASE) {
        unsigned slot = (unsigned) (sound - AUDIO_STREAM_INDEX_BASE);
        if (slot < MAX_STREAM_ENTRIES && ca->streamEntries[slot].active) name = ca->streamEntries[slot].path;
    } else if (sound >= 0 && (uint32_t) sound < ca->soundCount) {
        name = ca->base.audioGroups[0]->sond.sounds[sound].name;
    }
    // Full fight coverage, without spending the bounded ring on typing SFX.
    // Keep streams, loops, music, large SFX and unknown-size/pending sources.
    // Only a known small cache entry can be excluded; shed entries lose bytes.
    uint32_t bytes = sound >= 0 && (uint32_t) sound < ca->soundCount && ca->sfxCache != NULL
        ? ca->sfxCache[sound].bytes : 0;
    if (sound < AUDIO_STREAM_INDEX_BASE && bytes != 0 && bytes < 256u * 1024u && !ca->voices[id].loop &&
        (name == NULL || (strncmp(name, latMusicPrefix, 4) && strncmp(name, latOtherPrefix, 3)))) {
        __atomic_store_n(&lat.current[id], 0, __ATOMIC_RELEASE);
        return;
    }
    if (lat.used == LAT_REQUESTS) { lat.overflow++; return; }
    uint32_t index = lat.used++;
    LatVoice* row = &lat.voices[index];
    row->serial = ca->voices[id].serial;
    row->slot = (uint32_t) id;
    row->load = lat.loadCount;
    row->frame = (uint32_t) lat.runner->frameCount;
    row->sound = sound;
    snprintf(row->name, sizeof(row->name), latNameFormat, name != NULL ? name : latUnknown);
    row->callObserved = lat.callAudio == ca && lat.callSound == sound && lat.callTick != 0;
    row->request = row->callObserved ? lat.callTick : svcGetSystemTick();
    __atomic_store_n(&lat.audio, ca, __ATOMIC_RELEASE);
    __atomic_store_n(&lat.current[id], index + 1, __ATOMIC_RELEASE);
}

LAT_CODE static void latPhysicalAdd(int channel, ndspWaveBuf* buffer) {
    // Run the same lower layer as before; do not bypass audiocap if enabled.
#ifdef CTR_AUDIO_CAPTURE_WRAP_H
    CtrCap_chnWaveBufAdd(channel, buffer);
#else
    (ndspChnWaveBufAdd)(channel, buffer);
#endif
    int id = channel >= 0 && channel < UTA_CHANNELS ? utaInv[channel] : -1;
    if ((unsigned) id >= VOICE_COUNT) return; // detached tail
    uint32_t index = __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE);
    if (index == 0) return;
    LatVoice* row = &lat.voices[index - 1];
    CtrAudioSystem* ca = __atomic_load_n(&lat.audio, __ATOMIC_ACQUIRE);
    if (row->queueReady || ca == NULL || ca != utaCa || ca->voices[id].serial != row->serial) return;
    // A logical voice has one producer (game SFX feeder or stream decoder).
    row->queue = svcGetSystemTick();
    row->queueSeq = buffer->sequence_id;
    row->queueFrames = buffer->nsamples;
    row->queueRate = utaChan[channel].rate;
    __atomic_store_n(&row->queueReady, true, __ATOMIC_RELEASE);
}

// Called by the original NDSP callback, after uta's lock has been released.
// POS/SEQ are the raw physical getters: no additional locks or allocations.
LAT_CODE static void latSample(CtrAudioSystem* ca) {
    for (unsigned id = 0; id < VOICE_COUNT; id++) {
        uint32_t index = __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE);
        if (index == 0) continue;
        LatVoice* row = &lat.voices[index - 1];
        if (row->progressReady || !__atomic_load_n(&row->queueReady, __ATOMIC_ACQUIRE) ||
            ca != __atomic_load_n(&lat.audio, __ATOMIC_ACQUIRE) ||
            ca->voices[id].serial != row->serial || ca->voices[id].kind == VOICE_FREE) continue;
        int channel = utaPhys((int) id);
        uint32_t sequence = UTA_PHYS_SEQ(channel);
        uint32_t position = UTA_PHYS_POS(channel);
        if (position == 0 || sequence == 0 || UTA_PHYS_SEQ(channel) != sequence) continue;
        // A stop/reuse may race the raw query. Never attribute the new source
        // to the old row when either the logical identity or mapping changed.
        if (__atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE) != index ||
            ca->voices[id].serial != row->serial || ca->voices[id].kind == VOICE_FREE ||
            utaPhys((int) id) != channel) continue;
        row->sample = position;
        row->progressSeq = sequence;
        row->progress = svcGetSystemTick();
        __atomic_store_n(&row->progressReady, true, __ATOMIC_RELEASE);
    }
}

LAT_CODE static void latBoundary(Runner* runner, bool loaded) {
    lat.runner = runner;
    lat.frameReady = !loaded && runner->pendingRoom == -1;
    if (loaded) {
        if (lat.loadCount != 0) {
            LatLoad* load = &lat.loads[lat.loadCount - 1];
            load->end = svcGetSystemTick();
            load->to = runner->currentRoomIndex;
        }
    } else if (runner->pendingRoom != -1) {
        if (lat.loadCount == LAT_LOADS) { lat.overflow++; return; }
        LatLoad* load = &lat.loads[lat.loadCount++];
        load->begin = svcGetSystemTick();
        load->frame = (uint32_t) runner->frameCount;
        load->from = runner->currentRoomIndex;
        load->to = runner->pendingRoom;
    }
}

// Exactly the gate's marked destination submission, after the presentation
// chain returns and before the release applies. This is not LCD scan-out.
LAT_CODE static void latPresented(Renderer* renderer) {
    u64 tick = svcGetSystemTick();
    CtrAudioSystem* ca = __atomic_load_n(&lat.audio, __ATOMIC_ACQUIRE);
    for (uint32_t i = 0; i < lat.loadCount; i++) {
        LatLoad* load = &lat.loads[i];
        if (load->submit != 0) continue;
        load->submit = tick;
        load->submitFrame = (uint32_t) renderer->runner->frameCount;
    }
    for (uint32_t i = 0; i < lat.used; i++) {
        LatVoice* row = &lat.voices[i];
        if (lat.loads[row->load - 1].submit != tick || ca == NULL ||
            ca->voices[row->slot].serial != row->serial ||
            !__atomic_load_n(&row->queueReady, __ATOMIC_ACQUIRE)) continue;
        row->submitSample = UTA_PHYS_POS(utaPhys((int) row->slot));
        row->submitObserved = true;
    }
}

// Drain at least 60 game frames after first presentation. Zero event ticks are
// explicitly unobserved, never a computed negative gap or an inferred success.
LAT_CODE static void latDrain(void) {
    if (lat.runner == NULL) return;
    uint32_t frame = (uint32_t) lat.runner->frameCount;
    for (uint32_t i = 0; i < lat.loadCount; i++) {
        LatLoad* load = &lat.loads[i];
        if (load->submit == 0 || frame < load->submitFrame || frame - load->submitFrame < 60) continue;
        if (!load->printed) {
            load->printed = true;
            logQuiet(latLoadFormat, (unsigned long) (i + 1), (long) load->from, (long) load->to,
                     (unsigned long) load->frame, (unsigned long) load->submitFrame,
                     (unsigned long long) load->begin, (unsigned long long) load->end,
                     (unsigned long long) load->submit, (unsigned) latGateOn());
        }
    }
    for (uint32_t i = 0; i < lat.used; i++) {
        LatVoice* row = &lat.voices[i];
        LatLoad* load = &lat.loads[row->load - 1];
        if (row->printed || load->submit == 0 || frame < load->submitFrame || frame < row->frame ||
            frame - load->submitFrame < 60 || frame - row->frame < 60) continue;
        row->printed = true;
        bool queued = __atomic_load_n(&row->queueReady, __ATOMIC_ACQUIRE);
        bool progressed = __atomic_load_n(&row->progressReady, __ATOMIC_ACQUIRE);
        logQuiet(latVoiceFormat, (unsigned long) (i + 1), (unsigned long) row->load,
                 (unsigned long) row->slot, (unsigned long) row->serial, (long) row->sound,
                 (unsigned long long) row->request, (unsigned long long) (queued ? row->queue : 0),
                 (unsigned long long) (progressed ? row->progress : 0), (unsigned long) (progressed ? row->sample : 0),
                 (unsigned long) row->submitSample, (unsigned) row->submitObserved, row->name);
        bool opened = __atomic_load_n(&row->openReady, __ATOMIC_ACQUIRE);
        logQuiet(latPhasesFormat, (unsigned long) (i + 1), (unsigned long) row->frame, (unsigned) row->callObserved,
                 (unsigned long long) (opened ? row->openBegin : 0), (unsigned long long) (opened ? row->openEnd : 0),
                 (unsigned long long) (queued ? row->fillBegin : 0), (unsigned long long) (queued ? row->fillEnd : 0),
                 (unsigned long long) (queued ? row->readTicks : 0), (unsigned long) row->queueSeq, (unsigned long) row->progressSeq,
                 (unsigned long) row->queueFrames, (double) row->queueRate);
    }
    for (uint32_t i = 0; i < lat.pointCount; i++) {
        LatPoint* row = &lat.points[i];
        if (row->printed || frame < row->frame || frame - row->frame < 60) continue;
        row->printed = true;
        logQuiet(latPointFormat, (unsigned long) row->mark, (unsigned long) row->requestedFrame, (unsigned long) row->frame,
                 (unsigned long) row->voice, (unsigned long long) row->tick, (unsigned long) row->rate,
                 (unsigned long long) row->source, (unsigned long long) row->total, (unsigned long) row->raw,
                 (unsigned long) row->seq, row->clock, (double) row->pitch, (unsigned) row->loop,
                 (unsigned) row->paused, (unsigned) row->observed,
                 (unsigned long) row->transport[0], (unsigned long) row->transport[1],
                 (unsigned long) row->transport[2], (unsigned long) row->transport[3],
                 (unsigned long) row->transport[4], (unsigned long) row->transport[5]);
    }
    if (lat.overflow != 0 && !lat.overflowPrinted) {
        lat.overflowPrinted = true;
        logQuiet(latOverflowFormat, (unsigned long) lat.overflow);
    }
}

// Outermost UT play vtable entry, before cache installation/probe/claim work.
LAT_CODE static void latCall(CtrAudioSystem* ca, int32_t sound) {
    lat.callTick = svcGetSystemTick();
    lat.callSound = sound;
    lat.callAudio = ca;
}

// Decoder identity rather than a sound name: repeated and concurrent cues must
// not borrow another instance's open or first-fill duration.
LAT_CODE static LatVoice* latDecoder(CtrDecoder* decoder) {
    CtrAudioSystem* ca = __atomic_load_n(&lat.audio, __ATOMIC_ACQUIRE);
    if (ca == NULL) return NULL;
    for (unsigned i = 0; i < STREAM_CONTEXTS; i++) {
        StreamContext* stream = &ca->streams[i];
        if (&stream->decoder != decoder || (unsigned) stream->owner >= VOICE_COUNT) continue;
        unsigned id = (unsigned) stream->owner;
        uint32_t index = __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE);
        if (index != 0 && ca->voices[id].serial == lat.voices[index - 1].serial) return &lat.voices[index - 1];
    }
    return NULL;
}

LAT_CODE static bool latOpenFile(CtrDecoder* decoder, const char* path) {
    LatVoice* row = latDecoder(decoder);
    u64 begin = svcGetSystemTick();
    bool ok = (CtrDecoder_openFile)(decoder, path);
    if (row != NULL) {
        row->openBegin = begin; row->openEnd = svcGetSystemTick();
        __atomic_store_n(&row->openReady, true, __ATOMIC_RELEASE);
    }
    return ok;
}

LAT_CODE static bool latOpenMemory(CtrDecoder* decoder, const uint8_t* data, uint32_t size) {
    LatVoice* row = latDecoder(decoder);
    u64 begin = svcGetSystemTick();
    bool ok = (CtrDecoder_openMemory)(decoder, data, size);
    if (row != NULL) {
        row->openBegin = begin; row->openEnd = svcGetSystemTick();
        __atomic_store_n(&row->openReady, true, __ATOMIC_RELEASE);
    }
    return ok;
}

LAT_CODE static int32_t latRead(CtrDecoder* decoder, int16_t* output, uint32_t frames) {
    LatVoice* row = latDecoder(decoder);
    if (row != NULL && __atomic_load_n(&row->queueReady, __ATOMIC_ACQUIRE)) row = NULL;
    u64 begin = svcGetSystemTick();
#ifdef CTR_AUDIO_CAPTURE_WRAP_H
    int32_t got = CtrCap_decRead(decoder, output, frames);
#else
    int32_t got = (CtrDecoder_read)(decoder, output, frames);
#endif
    if (row != NULL) {
        u64 end = svcGetSystemTick();
        if (row->fillBegin == 0) row->fillBegin = begin;
        row->fillEnd = end; row->readTicks += end - begin;
    }
    return got;
}

// Diagnostic-only bench command: audio_sound_get_track_position(INT32_MIN+n),
// n=1..255, requests a checkpoint after this game's next real submission.
// The builtin's return remains 0 for this invalid handle. No gameplay writes.
LAT_CODE static void latMark(uint32_t mark) {
    if (lat.mark != 0 || lat.runner == NULL) { lat.overflow++; return; }
    lat.mark = mark;
    lat.markFrame = (uint32_t) lat.runner->frameCount;
}

// Same physical-source reconstruction as pausemus's diagnostic, with try-locks:
// an unavailable sample stays UNOBSERVED rather than delaying the game frame.
LAT_CODE static void latSource(CtrAudioSystem* ca, unsigned id, LatPoint* point) {
    Voice* voice = &ca->voices[id];
    StreamContext* stream = NULL;
    if (voice->kind == VOICE_STREAM && voice->ctx >= 0) {
        stream = &ca->streams[voice->ctx];
        if (LightLock_TryLock(&stream->lock) != 0) return;
    } else if (voice->kind != VOICE_SFX) return;
    if (LightLock_TryLock(&utaLock) != 0) {
        if (stream != NULL) LightLock_Unlock(&stream->lock);
        return;
    }
    int physical = utaPhys((int) id);
    if (physical >= 0 && physical < UTA_CHANNELS) {
        uint32_t seq = UTA_PHYS_SEQ(physical), raw = UTA_PHYS_POS(physical);
        point->seq = seq; point->raw = raw;
        if (stream != NULL && !stream->seekPending) {
            point->rate = stream->sampleRate; point->total = stream->totalFrames;
            for (unsigned j = 0; seq != 0 && j < STREAM_BUFFERS; j++) {
                StreamBuffer* buffer = &stream->bufs[j];
                if (utaLive(&buffer->wb) && buffer->wb.sequence_id == seq) {
                    point->source = buffer->startFrame + raw; point->observed = true; break;
                }
            }
        } else if (stream == NULL && voice->sfx != NULL) {
            point->rate = voice->sfx->sampleRate; point->total = voice->sfx->frames;
            UtaChan* channel = &utaChan[physical];
            for (unsigned j = 0; seq != 0 && j < UTA_RING; j++) {
                unsigned seg = channel->piece[j].seg;
                if (utaLive(&utaWb[physical][j]) && utaWb[physical][j].sequence_id == seq && seg < 2 &&
                    channel->piece[j].kind != UTA_PIECE_TAIL && channel->seg[seg].mirror == &voice->wb[seg]) {
                    point->source = raw + channel->piece[j].off + (u64) voice->wbStart[seg];
                    point->observed = true; break;
                }
            }
            for (int j = 0; !point->observed && seq != 0 && j < voice->wbCount && channel->state == UTA_IDLE; j++) {
                if (utaLive(&voice->wb[j]) && voice->wb[j].sequence_id == seq) {
                    point->source = raw + (u64) voice->wbStart[j]; point->observed = true;
                }
            }
        }
        // Do not attribute a buffer switch racing the physical query.
        if (seq != UTA_PHYS_SEQ(physical)) point->observed = false;
    }
    point->tick = svcGetSystemTick();
    LightLock_Unlock(&utaLock);
    if (stream != NULL) LightLock_Unlock(&stream->lock);
}

LAT_CODE static void latFrame(Renderer* renderer, bool skipped) {
    if (!lat.frameReady || renderer->runner != lat.runner) return;
    lat.frameReady = false;
    if (lat.mark == 0 || skipped) return;
    CtrAudioSystem* ca = __atomic_load_n(&lat.audio, __ATOMIC_ACQUIRE);
    if (ca == NULL) return;
    unsigned before = lat.pointCount;
    for (unsigned id = 0; id < VOICE_COUNT; id++) {
        uint32_t index = __atomic_load_n(&lat.current[id], __ATOMIC_ACQUIRE);
        Voice* voice = &ca->voices[id];
        if (index == 0 || voice->kind == VOICE_FREE || voice->serial != lat.voices[index - 1].serial) continue;
        if (lat.pointCount == LAT_POINTS) { lat.overflow++; break; }
        LatPoint* row = &lat.points[lat.pointCount++];
        row->mark = lat.mark; row->requestedFrame = lat.markFrame;
        row->frame = (uint32_t) renderer->runner->frameCount; row->voice = index;
        row->clock = voice->clockSeconds; row->pitch = voice->pitch;
        row->loop = voice->loop; row->paused = voice->paused || ca->suspended;
        latClock(id, row->transport);
        latSource(ca, id, row);
    }
    if (before == lat.pointCount) lat.overflow++; // no sample rows is not a PASS
    lat.mark = 0;
}
