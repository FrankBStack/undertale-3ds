// Shared whole-mix physical operation, factored from pausemus pmPhysical.
// Caller owns utaLock. No logical pause flag or queued source is changed.
// Pausemus may exclude its privately owned UI channel when releasing its menu.
// The room-load caller excludes none. Occupancy bookkeeping stays in pausemus.
LM_CODE void CtrAudio_transportMixLocked(CtrAudioSystem* ca, bool hold, int except) {
    for (int p = 0; p < VOICE_COUNT; p++) {
        if (p == except) continue;
        int i = *CtrLoadmix_legacy.mapped ? CtrLoadmix_legacy.inverse[p] : p;
        const UtaChan* c = &CtrLoadmix_legacy.channels[p];
        const Voice* v = &ca->voices[i];
        PT_PHYS_PAUSED(p, hold || (c->state != UTA_IDLE ? c->paused : ca->suspended || v->paused));
    }
}
