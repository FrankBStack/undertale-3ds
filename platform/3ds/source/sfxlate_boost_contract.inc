// Heap state occupies the existing 4 B alignment hole before LoadRequest.
// Fail closed if any private field or total extent changes on either model.
#ifdef CTRPORT_AUDIOBOOST
_Static_assert(__builtin_offsetof(CtrAudioSystem, loadLock) == CTRPORT_AUDIOBOOST_LOADLOCK_AT, "boost loadLock ABI");
_Static_assert(__builtin_offsetof(CtrAudioSystem, msgLock) == CTRPORT_AUDIOBOOST_MSGLOCK_AT, "boost msgLock ABI");
_Static_assert(__builtin_offsetof(CtrAudioSystem, loader) == CTRPORT_AUDIOBOOST_LOADER_AT, "boost loader ABI");
_Static_assert(__builtin_offsetof(CtrAudioSystem, opener) == CTRPORT_AUDIOBOOST_OPENER_AT, "boost opener ABI");
_Static_assert(__builtin_offsetof(CtrAudioSystem, threadPriority) == CTRPORT_AUDIOBOOST_PRIORITY_AT, "boost priority ABI");
_Static_assert(__builtin_offsetof(CtrAudioSystem, audioBoostState) == CTRPORT_AUDIOBOOST_STATE_AT, "boost state ABI");
_Static_assert(sizeof(CtrAudioSystem) == 19512, "boost audio object grew");
__asm__(".pushsection .rodata_sfxboost,\"a\",%progbits\n"
        ".p2align 2\n.global ctrAudioBoostTarget\n"
        ".type ctrAudioBoostTarget,%object\nctrAudioBoostTarget:\n"
        ".word gShutdownTarget\n.size ctrAudioBoostTarget,4\n.popsection\n");
#endif
