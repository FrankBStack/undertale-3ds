// soulahead (change audiomain, 11-15, from maintainer's Old 3DS report of a long music delay in the first SOUL fight; included
// at ctr_audio_system.c's end, UNDERTALE only): Photoshop Flowey's first SOUL fight starts its music late.
//
// Its SOUL warning and its SOUL song open from the card at their first play (Old 3DS 127-190 ms, Old 2DS 176-208 ms,
// in every one of 329 bench logs), and on PC both start in the frame of the call. Every later SOUL's warning comes from
// a shed cue's spare (flowhitch) and its song from flowend's number guess (the song before it, number + 1); nothing
// names the first two before they play. The SOUL's end jingle opens cold after every SOUL too (112-172 ms).
//
// This link names them to flowend's first spare (the decoder the number guess uses), at the opener's waits, from the
// file the opener opened last (flowendLastPath, while its guess is due):
//   the first phase song          -> the SOUL warning   (no SOUL song opened yet in this room)
//   the SOUL warning              -> the first SOUL song (the same)
//   a SOUL song, number N         -> the end jingle (N + 1 is named after the jingle)
//   the end jingle                -> SOUL song N + 1 (none after the sixth)
//   any other file while the jingle is held -> SOUL song N again (the jingle was not next: SOUL N was lost, and the
//                                    retry fights it again in the same room), once flowend's guess for that file has
//                                    run (the open jingle kept the spare from it)
// The phase-song spare keeps flowend's own table (part 1 -> part 2 and back): its guess still runs after the first
// phase song. The spare is taken only when it is free: idle, already this link's, or unused past flowend's 120 s keep;
// another guess's spare is left alone (the play then opens cold, as before). When this link names the spare for the
// warning, a SOUL song or the jingle, flowend's guess for that file is not made (its due flag is cleared): the number
// guess and the created-stream guess would otherwise replace the name before it opens. After the first phase song the
// guess is still made: the phase-song table fills the other spare and leaves the first alone.
//
// The spare holds a file this link named for at most SOULAHEAD_KEEP_MS (flowend's keep) of the game's time: unused that
// long, it is closed. Time the game does not run does not count: the spare's open tick moves on by each wait's time
// while the options menu holds the game (and its audio), as the game's own clock stops (maintainer's N8.1 session, 11-14:
// the menu held 102.4 s between the first phase song and the warning and 180.1 s between the warning and the first SOUL
// song, 25 s and 7 s of play; a wall-clock keep would have closed both spares before their plays), while a HOME stay
// suspends the audio, and by a wait gap's time past its DSP frames (sleep, Rosalina's menu).
// A held jingle hands over to the next SOUL song, which starts its own keep. A room change (a reset, the fight left)
// closes it and forgets the fight's progress. A loss in the fight is not one: the fight's own reload goes on in the
// room (r3, from the #77 hardware rows), so a loss keeps the progress and names the lost SOUL's song again. A spare
// only ever reaches a play that opens its exact path (flowend's take), so a wrong name costs one open and plays nothing.
//
// r2 (review c26rev7): two observations are made where they happen, not at the next wait.
//  - A play's take of this link's file is recorded in flowhitch's latest cues at the take itself (the open's
//    read-ahead start, right after it in openStream), from its own stream's voice, as flowhitch's open link records a
//    cold open: another open before the next wait (another stream context) no longer hides it, and the order is the
//    cold opens' order.
//  - The room: the game thread notes each room change in the runner (Physics_initRoom, before the new room's
//    instances run) with the voices' serial count then. An open whose voice was asked for before the latest room
//    change (a lower serial) is the room before's: it names nothing, whenever the opener opens it or sees the change.
//
// Opener thread only, as all of the spare's statics (the room's two words are the game thread's). They are reached
// through address words loaded inside the functions (bootahead's pattern): a new C reference to flowend's statics
// reorders the file's late code. Code in an AAC text tail input (.aacout.text.soulahead, aacout.cmake), no constants;
// its state (48 B) is late bss (.bss.soulahead_late). Two calls are wrapped (CMakeLists.txt, UNDERTALE with Tremor), so
// openStream and the runner keep their code. The file names are FNV-1a hashes of the data's names before the extension
// (RoomPlan_fnv1a, as flowend's song table).
#ifdef ENABLE_WAD16 // AAC tenants carry an explicit guard (test_aacslot_shared.py)
#ifdef CTRPORT_HAVE_TREMOR
#define SOULAHEAD_CODE __attribute__((noinline, noipa, optimize("Os"), section(".aacout.text.soulahead")))
#define SOULAHEAD_ADDR(type, name) ({ type* at_; __asm__ volatile("ldr %0, 1f\n\tb 2f\n1:\t.word " #name "\n2:" : "=r"(at_) : : "memory"); at_; })
#define SOULAHEAD_PART1 0x5638720Au // the fight's first phase song
#define SOULAHEAD_WARN 0xCC92EECBu // the SOUL warning
#define SOULAHEAD_JINGLE 0x758F52C5u // the jingle at each SOUL's end
#define SOULAHEAD_SOUL 0xA02C8B12u // the SOUL songs' name before their one-digit number (9 characters)
#define SOULAHEAD_SOULS 6
#define SOULAHEAD_KEEP_MS 120000.0 // flowend's FLOWEND_AHEAD_KEEP_MS
#define SOULAHEAD_DSP_TICKS 1310720u // one DSP frame: 160 samples of 8192 system ticks (32728 Hz)
#define SOULAHEAD_AWAY_MS 250 // time this much past the DSP's frames is time away (a second's mark: 4x)

typedef struct {
    u64 tick; // the mark: the system tick at a wait (the time away, below)
    uint32_t cb; // the DSP's frame callbacks so far (utaCb) at the mark
    uint32_t seen; // the hash of the opened file this link last read while flowend's guess was due (0: none)
    uint32_t mine; // the hash of the file this link named to the first spare, while the spare still holds it (0: none)
    uint32_t room; // the room changes handled (roomSeq at the last wait)
    uint32_t roomSeq; // game thread: room changes so far (written after roomSerial)
    uint32_t roomSerial; // game thread: the voices' serial count at the latest room change
    uint32_t openSerial; // the serial of the voice whose stream opened last (its request's)
    uint32_t openHash; // that open's file (flowendLastPath's hash then)
    uint8_t held; // the options menu or a HOME stay held the game at the last wait
    uint8_t soul; // the SOUL song opened last in this room (1-6; 0: none yet)
    uint8_t next; // the SOUL song to name after the end jingle (0: none)
    uint8_t openLive; // that open's voice was still asking for it
} SoulAhead;
static SoulAhead soulAhead __attribute__((section(".bss.soulahead_late")));

// The FNV-1a hash of a path's last part before its extension; *base and *len get that part.
SOULAHEAD_CODE static uint32_t soulaheadName(const char* path, const char** base, size_t* len) {
    const char* b = strrchr(path, '/');
    b = b != NULL ? b + 1 : path;
    const char* dot = strrchr(b, '.');
    *base = b;
    *len = dot != NULL ? (size_t) (dot - b) : strlen(b);
    return RoomPlan_fnv1a((const uint8_t*) b, *len);
}

// The SOUL song's number in a file's last part (1-6), else 0.
SOULAHEAD_CODE static int soulaheadSoul(const char* base, size_t len) {
    if (len != 10 || RoomPlan_fnv1a((const uint8_t*) base, 9) != SOULAHEAD_SOUL) return 0;
    int n = base[9] - '0';
    return n >= 1 && SOULAHEAD_SOULS >= n ? n : 0;
}

// Whether this link may name the first spare: idle, its own, or unused past the keep (any guess may replace it then).
SOULAHEAD_CODE static bool soulaheadFree(void) {
    uint8_t state = *SOULAHEAD_ADDR(uint8_t, flowendAheadState); // 0 none, 1 path wanted, 2 open
    if (state == 0 || soulAhead.mine != 0) return true;
    return state == 2 && svcGetSystemTick() - *SOULAHEAD_ADDR(u64, flowendAheadTick) >= (u64) (SOULAHEAD_KEEP_MS * CPU_TICKS_PER_MSEC);
}

// Closes the first spare (this link's) and forgets it.
SOULAHEAD_CODE static void soulaheadDrop(void) {
    uint8_t* state = SOULAHEAD_ADDR(uint8_t, flowendAheadState);
    if (*state == 2) CtrDecoder_close(SOULAHEAD_ADDR(CtrDecoder, flowendAhead));
    *state = 0;
    soulAhead.mine = 0;
}

// The sound table's index of the sound whose file's last part hashes to hash (or, with hash 0, SOUL song soul); *fb and
// *fl get that part. -1: none.
SOULAHEAD_CODE static int32_t soulaheadSound(CtrAudioSystem* ca, uint32_t hash, int soul, const char** fb, size_t* fl) {
    DataWin* dw = ca->base.audioGroups != NULL ? ca->base.audioGroups[0] : NULL;
    for (uint32_t i = 0; dw != NULL && dw->sond.count > i; i++) {
        const char* file = dw->sond.sounds[i].file;
        if (file == NULL) continue;
        uint32_t h = soulaheadName(file, fb, fl);
        if (hash != 0 ? h == hash : soulaheadSoul(*fb, *fl) == soul) return (int32_t) i;
    }
    return -1;
}

// Names to the first spare that sound (soulaheadSound's), in the folder and with the extension of last (an opened file's
// path: the fight's music files sit together, as flowend's song table also assumes). A decoder the spare holds for
// another path is closed; the same path is kept as it is. False: no such sound (nothing changed).
SOULAHEAD_CODE static bool soulaheadWant(CtrAudioSystem* ca, const char* last, uint32_t hash, int soul) {
    const char* base;
    size_t len;
    const char* fb;
    size_t fl;
    soulaheadName(last, &base, &len);
    if (soulaheadSound(ca, hash, soul, &fb, &fl) < 0) return false;
    char path[FLOWEND_AHEAD_PATH];
    int n = snprintf(path, sizeof(path), SOULAHEAD_ADDR(const char, flowendSongName), (int) (base - last), last, (int) fl, fb, base + len);
    if (n <= 0 || n >= FLOWEND_AHEAD_PATH) return false;
    uint8_t* state = SOULAHEAD_ADDR(uint8_t, flowendAheadState);
    char* held = SOULAHEAD_ADDR(char, flowendAheadPath);
    if (!(*state != 0 && strcmp(held, path) == 0)) {
        if (*state == 2) CtrDecoder_close(SOULAHEAD_ADDR(CtrDecoder, flowendAhead));
        memcpy(held, path, (size_t) n + 1);
        *state = 1; // flowend's wait opens it at a quiet second
    }
    soulAhead.mine = RoomPlan_fnv1a((const uint8_t*) fb, fl);
    return true;
}

// A play took this link's file from the spare, so flowhitch's open link (which records a cue's or a shed sound's play
// as its latest, for the shed cues' spares) did not see it: recorded here as that link records it, si being the sound
// of its stream's voice. The SOUL warning is such a sound, and its later plays come from flowhitch's spares (0.0-1.2
// ms in the bench logs).
SOULAHEAD_CODE static void soulaheadRecent(CtrAudioSystem* ca, int32_t si) {
    if (si < 0 || (uint32_t) si >= ca->soundCount) return;
    bool marked = false; // flowhitchMarked's test: the guard shed it this room
    int16_t* shed = SOULAHEAD_ADDR(int16_t, flowhitchSound);
    for (uint32_t i = 0, n = *SOULAHEAD_ADDR(uint32_t, flowhitchCount); n > i; i++) marked |= shed[i] == si;
    if (ca->soundForms[si] == FORM_STREAMED && !marked) return;
    int16_t* recent = SOULAHEAD_ADDR(int16_t, flowhitchRecent);
    int i = 0;
    while (FLOWHITCH_RECENT - 1 > i && recent[i] != si + 1) i++;
    for (; i > 0; i--) recent[i] = recent[i - 1];
    recent[0] = (int16_t) (si + 1);
}

// Opener thread, at a wait of the spares' owner: the table in the header.
SOULAHEAD_CODE static void soulaheadStep(CtrAudioSystem* ca) {
    SoulAhead* s = &soulAhead;
    uint8_t* state = SOULAHEAD_ADDR(uint8_t, flowendAheadState);
    const char* last = SOULAHEAD_ADDR(const char, flowendLastPath);
    const char* base = last;
    size_t len = 0;
    // Taken by its play (recorded at the take: soulaheadOpened), or replaced by another guess (or by a new owner's drop):
    // no longer this link's.
    const char* held = SOULAHEAD_ADDR(const char, flowendAheadPath);
    if (s->mine != 0 && (*state == 0 || soulaheadName(held, &base, &len) != s->mine)) s->mine = 0;
    uint32_t room = __atomic_load_n(&s->roomSeq, __ATOMIC_ACQUIRE);
    if (room != s->room) { // a room change: the fight's progress and its spare go
        s->room = room;
        s->soul = 0;
        s->next = 0;
        s->seen = 0;
        if (s->mine != 0) soulaheadDrop();
    }
    // Time the game does not run is not play: the spare's open tick moves on by it (see the header). Held (the options
    // menu's hold, menuHeld, the game thread's byte; a HOME stay, the audio's suspend by CtrAudio_homeFreeze) at this
    // wait and the last: the whole time since. Otherwise the time since the mark past its DSP frames (utaCb, one every
    // 4.9 ms from the DSP's thread, above the game's), once SOULAHEAD_AWAY_MS or more: sleep finalizes the DSP and
    // Rosalina's menu stops it with this thread, so either way the frames stop (hardware/audio.md, the load mix's time
    // away), whether this thread waits on or not. The mark moves on at time away, at a hold and after a second of play:
    // play counts as away only when its DSP frames fall SOULAHEAD_AWAY_MS behind in that second, and then only makes the
    // keep longer. Stale reads move the keep by one wait at most. The open tick never moves past now (a spare opened
    // since the mark).
    bool hold = __atomic_load_n(SOULAHEAD_ADDR(uint8_t, menuHeld), __ATOMIC_RELAXED) != 0 ||
                __atomic_load_n(&ca->suspended, __ATOMIC_RELAXED);
    u64 now = svcGetSystemTick(), gap = now - s->tick;
    uint32_t cb = __atomic_load_n(SOULAHEAD_ADDR(uint32_t, utaCb), __ATOMIC_RELAXED);
    u64 dsp = (u64) (cb - s->cb) * SOULAHEAD_DSP_TICKS, slack = (u64) (SOULAHEAD_AWAY_MS * CPU_TICKS_PER_MSEC);
    u64 away = hold && s->held ? gap : gap >= dsp + slack ? gap - dsp : 0;
    u64* opened = SOULAHEAD_ADDR(u64, flowendAheadTick);
    if (s->mine != 0 && *state == 2) *opened += away < now - *opened ? away : now - *opened;
    if (away != 0 || hold || gap >= 4 * slack) {
        s->tick = now;
        s->cb = cb;
    }
    s->held = hold;
    if (s->mine != 0 && *state == 2 &&
        svcGetSystemTick() - *SOULAHEAD_ADDR(u64, flowendAheadTick) >= (u64) (SOULAHEAD_KEEP_MS * CPU_TICKS_PER_MSEC)) {
        bool jingle = s->mine == SOULAHEAD_JINGLE;
        soulaheadDrop(); // unused for the keep: closed
        if (jingle && s->next != 0 && last[0] != 0) soulaheadWant(ca, last, 0, s->next); // the next SOUL song's own keep
        if (jingle) s->next = 0;
    }
    uint8_t* due = SOULAHEAD_ADDR(uint8_t, flowendGuessDue);
    uint32_t h = last[0] != 0 ? soulaheadName(last, &base, &len) : 0;
    // The last open is the room before's (its voice asked for it before the latest room change; read after the count,
    // so a change this wait has not handled yet only makes more opens stale), its voice let it go, or it is not the
    // open soulaheadOpened saw: it names nothing (flowend's own guess for it is left as it was).
    uint32_t from = __atomic_load_n(&s->roomSerial, __ATOMIC_ACQUIRE);
    if (!s->openLive || h != s->openHash || (int32_t) (s->openSerial - from) < 0) {
        s->seen = 0;
        return;
    }
    if (*due == 0) {
        s->seen = 0;
        // Something other than a SOUL song or the jingle opened while the jingle is held, and flowend's guess for it has
        // run (the held jingle kept the spare, as any open spare within the keep): the jingle was not next. SOUL N was
        // lost (the reload's music), and the retry fights SOUL N again in this room, so its song is named again (r3;
        // r1-r2 named N + 1, the song after a SOUL saved). Its open names the jingle again, as at the first try.
        if (s->soul != 0 && s->mine == SOULAHEAD_JINGLE && h != 0 && h != SOULAHEAD_JINGLE && soulaheadSoul(base, len) == 0) {
            soulaheadWant(ca, last, 0, s->soul);
            s->next = 0;
        }
        return;
    }
    if (h == s->seen) return;
    s->seen = h;
    int soul = soulaheadSoul(base, len);
    if (h == SOULAHEAD_PART1) {
        if (s->soul == 0 && soulaheadFree()) soulaheadWant(ca, last, SOULAHEAD_WARN, 0);
    } else if (h == SOULAHEAD_WARN) {
        if (s->soul == 0 && soulaheadFree() && soulaheadWant(ca, last, 0, 1)) *due = 0;
    } else if (soul != 0) {
        s->soul = (uint8_t) soul;
        s->next = 0;
        if (soulaheadFree() && soulaheadWant(ca, last, SOULAHEAD_JINGLE, 0)) { // N + 1 is named after the jingle
            *due = 0;
            s->next = (uint8_t) (SOULAHEAD_SOULS > soul ? soul + 1 : 0);
        }
    } else if (h == SOULAHEAD_JINGLE) {
        if (s->next != 0 && soulaheadFree() && soulaheadWant(ca, last, 0, s->next)) *due = 0;
        s->next = 0;
    }
}

// Opener thread, right after a stream's file opened (openStream's read-ahead start, wrapped): the open's voice and its
// file, for soulaheadStep. A take of this link's file from the spare (the stream's decoder holds the spare's Tremor
// state) is recorded as flowhitch's open link records a cold open, from the stream's voice, before any other open.
// Decoders of no stream context are left alone.
SOULAHEAD_CODE static void soulaheadOpened(CtrAudioSystem* ca, CtrDecoder* d) {
    SoulAhead* s = &soulAhead;
    uintptr_t off = (uintptr_t) d - (uintptr_t) &ca->streams[0].decoder;
    if (off % sizeof(StreamContext) != 0 || off / sizeof(StreamContext) >= STREAM_CONTEXTS) return;
    StreamContext* sc = &ca->streams[off / sizeof(StreamContext)];
    int32_t vi = sc->owner;
    bool voice = vi >= 0 && VOICE_COUNT > vi;
    const char* base;
    size_t len;
    const char* last = SOULAHEAD_ADDR(const char, flowendLastPath);
    s->openHash = last[0] != 0 ? soulaheadName(last, &base, &len) : 0;
    s->openSerial = voice ? ca->voices[vi].serial : 0;
    s->openLive = voice && !__atomic_load_n(&sc->stopRequested, __ATOMIC_RELAXED);
    const CtrDecoder* spare = SOULAHEAD_ADDR(const CtrDecoder, flowendAhead);
    if (s->mine != 0 && *SOULAHEAD_ADDR(uint8_t, flowendAheadState) == 0 && d->kind == CTR_DECODER_VORBIS && d->vf.vi == spare->vf.vi) {
        soulaheadRecent(ca, voice ? ca->voices[vi].soundIndex : -1);
        s->mine = 0;
    }
}

bool __real_CtrDecoder_startReadAhead(CtrDecoder* d);
SOULAHEAD_CODE bool __wrap_CtrDecoder_startReadAhead(CtrDecoder* d) {
    CtrAudioSystem* ca = *SOULAHEAD_ADDR(CtrAudioSystem*, gShutdownTarget);
    if (ca != NULL && ca->opener != NULL && threadGetCurrent() == ca->opener) soulaheadOpened(ca, d);
    return __real_CtrDecoder_startReadAhead(d);
}

// Game thread, at each room change in the runner (initRoom's physics set-up, before the new room's instances run): the
// voices' serial count then, and the count of changes after it.
void __real_Physics_initRoom(struct Runner* runner);
SOULAHEAD_CODE void __wrap_Physics_initRoom(struct Runner* runner) {
    CtrAudioSystem* ca = *SOULAHEAD_ADDR(CtrAudioSystem*, gShutdownTarget);
    if (ca != NULL) __atomic_store_n(&soulAhead.roomSerial, ca->serialCounter, __ATOMIC_RELEASE);
    __atomic_add_fetch(&soulAhead.roomSeq, 1, __ATOMIC_RELEASE);
    __real_Physics_initRoom(runner);
}

// Opener thread, at each note (bootahead's link calls it): this link's step at the spares' owner's waits, then loadclass
// 4c's link, as bootahead's called it before.
SOULAHEAD_CODE void CtrAudioSystem_chainNoteSoulahead(const char* state) {
    CtrAudioSystem* ca = *SOULAHEAD_ADDR(CtrAudioSystem*, gShutdownTarget);
    if (ca != NULL && ca->opener != NULL && threadGetCurrent() == ca->opener && !ca->openerQuit &&
        *SOULAHEAD_ADDR(CtrAudioSystem*, flowendAheadOwner) == ca && strcmp(state, SOULAHEAD_ADDR(const char, flowendWaiting)) == 0)
        soulaheadStep(ca);
    CtrAudioSystem_chainNotePair(state);
}
#endif // CTRPORT_HAVE_TREMOR
#endif // ENABLE_WAD16
