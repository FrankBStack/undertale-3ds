// e5xDrawTriangleFan's way in, one line in ctr_renderer.c so that nothing there moves: fanQuads, at the file's end, in
// late text (UNDERTALE Old); everywhere else the fan as it was.
#if !defined(ENABLE_WAD17) && !defined(CTRPORT_TARGET_N3DS)
static void fanQuads(Renderer* renderer, float cx, float cy, const float* xs, const float* ys, int32_t pointCount, uint32_t centerColor,
                     uint32_t edgeColor, float alpha) __attribute__((noipa, section(".text_fanquads")));
#define E5X_FAN fanQuads
#else
#define E5X_FAN ctrDrawTriangleFan
#endif
