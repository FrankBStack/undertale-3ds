// Only present can wake a parked loan, immediately before its real replay.
// Bounds are the replay bounds clipped to the same application dimensions.
#ifndef CTRPORT_LATERECLAIM_DLG_SECTION
#define CTRPORT_LATERECLAIM_DLG_SECTION ".text_dlgcloseblack_late"
#endif
#line 3
#define DLGTOP_ADMIT_CODE __attribute__((section(CTRPORT_LATERECLAIM_DLG_SECTION), noinline, noclone, noipa, used, optimize("Os")))
DLGTOP_ADMIT_CODE static C3D_RenderTarget* dlgtopPresentTarget(CtrRenderer* r, const CtrSurface* app) {
    if (!r->display.dialogueBottom || r->bottomYielded) return nullptr;
    C3D_RenderTarget* target = dlgtopRecord(r);
    if (target == nullptr || dlgtopLease.parked == 0) return target;
    int32_t appW = app->width, appH = app->height;
    CtrSurface* rec = &r->dlg.rec;
    ptrdiff_t n = r->dlg.armed ? arrlen(rec->ops) : 0;
    float x0 = INFINITY, y0 = INFINITY, x1 = -INFINITY, y1 = -INFINITY;
    for (ptrdiff_t i = 0; n > i; i++) {
        float ox0, oy0, ox1, oy1;
        recOpBounds(rec->ops[i].x, rec->ops[i].y, &ox0, &oy0, &ox1, &oy1);
        x0 = minF(x0, ox0);
        y0 = minF(y0, oy0);
        x1 = maxF(x1, ox1);
        y1 = maxF(y1, oy1);
    }
    x0 = maxF(x0, 0.0f);
    y0 = maxF(y0, 0.0f);
    x1 = minF(x1, (float) appW);
    y1 = minF(y1, (float) appH);
    if (dlgtopBoxOpen(r) && n > 0 && x0 < x1 && y0 < y1) {
        if (!CtrLayout_dialogueLease((Renderer*) r, target, 1)) {
            dlgtopLease.target = nullptr;
            dlgtopLease.parked = 0;
            return nullptr;
        }
        dlgtopLease.parked = 0;
    }
    return dlgtopLease.parked == 2 ? nullptr : target;
}
#undef DLGTOP_ADMIT_CODE
