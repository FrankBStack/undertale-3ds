// Shared UNDERTALE fatal-exit fix. Included after z_argcrash.c's old code so
// the existing private readiness flag and every old address stay unchanged.
// No save-folder classification, scan policy, or additional state lives here.
void __real_gfxExit(void);
void CtrFatalGfx_exit(void);
__attribute__((noinline, noipa, section(".text_fatalgfx")))
void CtrFatalGfx_exit(void) {
    // exitStep("done") logs after gfxExit and may request another fatal paint.
    // Invalidate the painter before the GSP mapping and framebuffers disappear.
    argcrashGfxReady = false;
    __real_gfxExit();
}
