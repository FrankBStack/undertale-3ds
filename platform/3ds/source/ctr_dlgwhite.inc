// A fill matching the application clear is still needed in a recording.
// Preserve the original no-op test and query recording only for a would-be drop.
#ifdef ENABLE_WAD16
__attribute__((section(".text_dlgwhite"), noinline, noclone, used, optimize("Os")))
bool CtrDlgwhite_solidDrawIsNoop(CtrRenderer* r, const CtrColor* c) {
    bool originalSolid(const CtrRenderer*, const CtrColor*) __asm__("solidDrawIsNoop");
    if (!originalSolid(r, c)) return false;
    return recordingSurface(r) == nullptr;
}
#endif
