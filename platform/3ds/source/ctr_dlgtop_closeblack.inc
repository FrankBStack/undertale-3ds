// Retain the original close body and all earlier late tenants. Only the first
// ordinary 0->1 park waits for its existing black transfer to reach Top. Buffer
// retirement still belongs to room/settings/yield/destroy, never this wrapper.
#ifndef CTRPORT_LATERECLAIM_DLG_SECTION
#define CTRPORT_LATERECLAIM_DLG_SECTION ".text_dlgcloseblack_late"
#endif
#line 4
#define DLGTOP_CLOSEBLACK_CODE __attribute__((section(CTRPORT_LATERECLAIM_DLG_SECTION), noinline, noclone, noipa, used, optimize("Os")))

DLGTOP_CLOSEBLACK_CODE static void dlgtopCloseBlack(void) {
    CtrRenderer* r = dlgtopLease.owner;
    C3D_RenderTarget* target = dlgtopLease.target;
    unsigned parked = dlgtopLease.parked;
    dlgtopClose();
    if (parked != 0 || dlgtopLease.parked != 1 || r == nullptr || r->inFrame ||
        dlgtopLease.owner != r || dlgtopLease.target != target ||
        !CtrLayout_dialogueLease((Renderer*) r, target, -1)) return;
    // Submission is not adoption. Finish the existing GPU frame, then wait out
    // both a held flip and the pending GSP present. Do not clear/copy a CPU page,
    // steal a console writer, release the loan or manufacture an extra flip.
    CtrGpu_waitIdle();
    while (!CtrPacer_screenReady(GFX_TOP))
        CtrScreens_pacerWaitShown(GFX_TOP, true);
}
#undef DLGTOP_CLOSEBLACK_CODE
