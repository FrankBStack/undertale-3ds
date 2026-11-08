"""Exercise production background dispatch, lifecycle and drawing on synthetic data."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = r'''
#include <assert.h>
#include <stdio.h>
#include "../../platform/3ds/source/z_gmlstubs.c"
static Runner runner;
static VMContext ctx;
static RuntimeBackground saved[8];
static int draws, delegatedGet, delegatedSet;
static uint32_t drawnBlend;
static bool restore;
int32_t RValue_toInt32Other(RValue v) {
    assert(v.type == RVALUE_INT32 || v.type == RVALUE_BOOL); return v.int32;
}
GMLReal RValue_toRealOther(RValue v) { return RValue_toInt32Other(v); }
RValue __real_VMBuiltins_getVariable(VMContext* c, Instance* i, int16_t id, const char* n, int32_t a) {
    (void)c; (void)i; (void)id; (void)n; (void)a; ++delegatedGet; return RValue_makeReal(123);
}
void __real_VMBuiltins_setVariable(VMContext* c, Instance* i, int16_t id, const char* n, RValue v, int32_t a) {
    (void)c; (void)i; (void)id; (void)n; (void)v; (void)a; ++delegatedSet;
}
void Gmlstubs_initRoomOriginal(Runner* r, int32_t index) {
    (void)index;
    if (restore) memcpy(r->backgrounds, saved, sizeof saved);
    else for (int i=0; i<8; ++i) r->backgrounds[i].foreground = false;
}
void Gmlstubs_drawBackgroundOriginal(Runner* r, int32_t t, bool s, float w, float h,
    bool tx, bool ty, float x, float y, float ox, float oy, float sx, float sy, uint32_t b, float a) {
    (void)r; (void)t; (void)s; (void)w; (void)h; (void)tx; (void)ty;
    (void)x; (void)y; (void)ox; (void)oy; (void)sx; (void)sy; (void)a;
    ++draws; drawnBlend=b;
}
static void set(int id, int index, double value) {
    __wrap_VMBuiltins_setVariable(&ctx, NULL, id, "", RValue_makeReal(value), index);
}
static double get(int id, int index) {
    return RValue_toReal(__wrap_VMBuiltins_getVariable(&ctx, NULL, id, "", index));
}
static int compare(const void* key, const void* entry) {
    return strcmp(key, ((const BackgroundVarEntry*)entry)->name);
}
int main(void) {
    ctx.runner=&runner;
    BackgroundVarEntry ordinary={"x", 42};
    assert(((BackgroundVarEntry*)Gmlstubs_varSearch("x", &ordinary, 1, sizeof ordinary, compare))->id == 42);
    assert(((BackgroundVarEntry*)Gmlstubs_varSearch("background_blend", &ordinary, 1, sizeof ordinary, compare))->id == GMLSTUBS_BLEND);
    assert(((BackgroundVarEntry*)Gmlstubs_varSearch("background_foreground", &ordinary, 1, sizeof ordinary, compare))->id == GMLSTUBS_FOREGROUND);
    assert(Gmlstubs_varSearch("missing", &ordinary, 1, sizeof ordinary, compare) == NULL);
    for (int i=0; i<8; ++i) assert(get(GMLSTUBS_BLEND,i) == 0xffffff);
    const uint32_t colours[]={0,128,0xffffff,0x123456,0x800000,0xff00ff,0x1000000,0xffffffff};
    for (int i=0; i<8; ++i) { set(GMLSTUBS_BLEND,i,colours[i]); assert(get(GMLSTUBS_BLEND,i) == (colours[i]&0xffffff)); }
    RuntimeBackground before[8]; memcpy(before,runner.backgrounds,sizeof before);
    set(GMLSTUBS_BLEND,-1,123); set(GMLSTUBS_BLEND,8,123);
    assert(memcmp(before,runner.backgrounds,sizeof before)==0);
    assert(get(GMLSTUBS_BLEND,-1)==0 && get(GMLSTUBS_FOREGROUND,8)==0);
    set(GMLSTUBS_FOREGROUND,3,1); assert(get(GMLSTUBS_FOREGROUND,3)==1);
    memcpy(saved,runner.backgrounds,sizeof saved);
    Gmlstubs_initRoom(&runner,0);
    for (int i=0; i<8; ++i) assert(get(GMLSTUBS_BLEND,i)==0xffffff && get(GMLSTUBS_FOREGROUND,i)==0);
    restore=true; Gmlstubs_initRoom(&runner,0);
    assert(memcmp(saved,runner.backgrounds,sizeof saved)==0);
    Room room={0}; DataWin data={0}; Background bg={0}; Renderer renderer={0};
    runner.currentRoom=&room; runner.dataWin=&data; runner.renderer=&renderer;
    data.bgnd.count=1; data.bgnd.backgrounds=&bg; bg.tpagIndex=17;
    for(int i=0;i<8;++i)runner.backgrounds[i].visible=false;
    runner.backgrounds[3].visible=true; runner.backgrounds[3].backgroundIndex=0;
    set(GMLSTUBS_BLEND,3,128);
    Gmlstubs_drawLegacy(&runner,false); assert(draws==0);
    Gmlstubs_drawLegacy(&runner,true); assert(draws==1 && drawnBlend==128);
    set(GMLSTUBS_FOREGROUND,3,0); Gmlstubs_drawLegacy(&runner,false); assert(draws==2);
    get(42,0); set(42,0,0); assert(delegatedGet==1 && delegatedSet==1);
    puts("PASS lookup, all eight colours, bounds, foreground, fresh/saved rooms, draw tint and pass, delegation");
    return 0;
}
'''


def main():
    out = ROOT/'build/gmlstubs/host-test'
    out.mkdir(parents=True, exist_ok=True)
    fixture = out/'fixture.c'
    # Keep the fixture source reference absolute; no generated sources are tracked.
    fixture.write_text(FIXTURE.replace('../../platform/', (ROOT/'platform').as_posix()+'/'))
    for level in ('-O0', '-O2', '-Os'):
        binary=out/('fixture'+level+'.exe')
        subprocess.run([shutil.which('gcc'), '-std=gnu11', level, '-Wall', '-Wextra', '-Werror',
                        '-Wno-unused-function', '-DENABLE_WAD16', '-I'+str(ROOT/'engine/src'),
                        '-I'+str(ROOT/'engine/vendor/stb/ds'), str(fixture), '-o', str(binary)],
                       stdin=subprocess.DEVNULL, timeout=60, check=True)
        subprocess.run([str(binary)], stdin=subprocess.DEVNULL, timeout=10, check=True)


if __name__ == '__main__':
    main()
