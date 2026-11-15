// Append adapters after fpsghost. Keep the previous retirement bodies and
// their section sizes: none of the earlier late tenants needs to move.
#ifndef CTRPORT_LATERECLAIM_DLG_SECTION
#define CTRPORT_LATERECLAIM_DLG_SECTION ".text_dlgcloseblack_late"
#endif
#line 3
#define DLGTOP_WAKE_CODE __attribute__((section(CTRPORT_LATERECLAIM_DLG_SECTION), noinline, noclone, noipa, used, optimize("Os")))

DLGTOP_WAKE_CODE static C3D_RenderTarget* dlgtopRecord(CtrRenderer* r) {
    C3D_RenderTarget* target = dlgtopBorrowed(r);
    if (target == nullptr) return nullptr;
    // Record query: validate without consuming parked state or taking LIGHT.
    if (!CtrLayout_dialogueLease((Renderer*) r, target, -1)) {
        dlgtopLease.target = nullptr;
        dlgtopLease.parked = 0;
        return nullptr;
    }
    if (dlgtopLease.parked == 2 && !dlgtopBoxOpen(r)) return nullptr;
    return target;
}

DLGTOP_WAKE_CODE static C3D_RenderTarget* dlgtopSubmit(CtrRenderer* r) {
    C3D_RenderTarget* target = dlgtopRecord(r);
    return dlgtopLease.parked == 2 ? nullptr : target;
}

DLGTOP_WAKE_CODE static void dlgtopCloseValidated(void) {
    dlgtopClose();
    if (dlgtopLease.target == nullptr) dlgtopLease.parked = 0;
}

DLGTOP_WAKE_CODE static void CtrDlgtop_idleGate(Renderer* renderer) {
    // Prepare may revoke a descriptor. Reset before any fresh Take, not in
    // the fixed Prepare/Take bodies and not in any record/submit query.
    if (dlgtopLease.target == nullptr) dlgtopLease.parked = 0;
    CtrDlgtop_idleChain(renderer);
}
#undef DLGTOP_WAKE_CODE
