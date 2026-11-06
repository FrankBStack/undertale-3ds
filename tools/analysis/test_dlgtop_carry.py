"""Compile the actual cold helpers against host framebuffers; no game data."""
from pathlib import Path
import shutil,subprocess

ROOT=Path(__file__).resolve().parents[2]

def main():
    out=ROOT/'scratch/dlgtop-carry-test';out.mkdir(parents=True,exist_ok=True)
    source=(ROOT/'platform/3ds/source/main.c').read_text()
    helpers=source.split('#define DLGTOP_FIX ',1)[1].split('\n#endif',1)[0]
    helpers=helpers[helpers.index('\n')+1:]
    helpers=helpers.replace('#define DLGTOP_GUARD __attribute__((noinline, noipa, section(".text.late.dlgtopguard")))', '#define DLGTOP_GUARD')
    loader=(ROOT/'platform/3ds/source/z_loadscreen.c').read_text()
    predicate='bool Loadgame_delayFirst(bool force) {'+loader.split('bool Loadgame_delayFirst(bool force) {',1)[1].split('\n}',1)[0]+'\n}'
    header=r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
typedef uint16_t u16;
enum {GFX_TOP=0,GFX_LEFT=0};
static unsigned char top[400*240*3],spare[400*240*3];
static bool doubleBuffer;
static unsigned toggles;
static bool CtrScreens_onBottom;
static struct {u16* frameBuffer;} menuConsole;
static void gfxSetDoubleBuffering(int screen,bool on) {assert(screen==0);doubleBuffer=on;toggles++;}
static void* CtrPacer_backFramebuffer(int screen,int eye) {assert(screen==0&&eye==0);return doubleBuffer?spare:top;}
#define DLGTOP_FIX
static struct {bool firstBelow;unsigned pictures;uint64_t loadStart;} ls;
static uint64_t tick;
static uint64_t svcGetSystemTick(void) {return tick;}
static uint32_t lsMs(uint64_t start,uint64_t end) {return (uint32_t)(end-start);}
'''
    fixture=r'''
int main(void) {
    unsigned char game[320*240*3],expected[320*240*2],bottom[320*240*2];
    for(size_t i=0;i<sizeof(game);i++) game[i]=(unsigned char)(i*13+7);
    for(size_t i=0;i<sizeof(expected);i++) expected[i]=(unsigned char)(i*3+71);
    // No carry (including screensCarry's early returns): use the intact source.
    memcpy(top,expected,sizeof(expected));memset(spare,0xEE,sizeof(spare));
    Loadgame_restoreMenu(bottom,top,sizeof(bottom));
    assert(toggles==0&&memcmp(bottom,expected,sizeof(expected))==0);
    menuConsole.frameBuffer=(u16*)top;CtrScreens_onBottom=true;doubleBuffer=false;
    // Real order: carry the BGR8 game onto the shown top buffer, then move
    // the RGB565 console to bottom. The old copy reads overwritten game bytes.
    Loadgame_carryCopy(top+40*240*3,game,sizeof(game));
    assert(!doubleBuffer&&toggles==2);
    assert(memcmp(top,expected,sizeof(expected))!=0);
    assert(memcmp(spare,expected,sizeof(expected))==0);
    assert(memcmp(top+40*240*3,game,sizeof(game))==0);
    Loadgame_restoreMenu(bottom,menuConsole.frameBuffer,sizeof(bottom));
    assert(!doubleBuffer&&toggles==4);
    assert(memcmp(bottom,expected,sizeof(expected))==0);
    // A backup is consumed once; a subsequent skipped carry uses its source.
    memset(top,0x4D,sizeof(top));memset(bottom,0,sizeof(bottom));
    Loadgame_restoreMenu(bottom,top,sizeof(bottom));
    assert(toggles==4&&memcmp(bottom,top,sizeof(bottom))==0);
    // The other direction still performs only the original game carry.
    CtrScreens_onBottom=false;toggles=0;memset(spare,0xEE,sizeof(spare));
    Loadgame_carryCopy(top,game,sizeof(game));
    assert(toggles==0&&memcmp(top,game,sizeof(game))==0);
    for(size_t i=0;i<sizeof(spare);i++) assert(spare[i]==0xEE);
    Loadgame_restoreMenu(bottom,top,sizeof(bottom));
    assert(toggles==0&&memcmp(bottom,top,sizeof(bottom))==0);
    // A spare already serving as the menu needs no backup or alternate source.
    menuConsole.frameBuffer=(u16*)spare;CtrScreens_onBottom=true;
    Loadgame_carryCopy(top,game,sizeof(game));
    assert(toggles==2&&!Loadgame_backupRan);
    Loadgame_restoreMenu(bottom,spare,sizeof(bottom));
    assert(toggles==2&&memcmp(bottom,spare,sizeof(bottom))==0);
    for(unsigned below=0;below<2;below++) for(unsigned pictures=0;pictures<2;pictures++) {
        ls.firstBelow=below;ls.pictures=pictures;ls.loadStart=0;
        tick=0;assert(Loadgame_delayFirst(false)==(below!=0));
        tick=199;assert(Loadgame_delayFirst(false)==(below!=0));
        tick=200;assert(!Loadgame_delayFirst(false));
        assert(Loadgame_delayFirst(true)==(below!=0&&pictures==0));
    }
    return 0;
}
'''
    c=out/'carry.c';exe=out/'carry.exe';c.write_text(header+helpers+'\n'+predicate+fixture)
    cc=shutil.which('gcc') or shutil.which('clang');assert cc,'Host C compiler required'
    subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',str(c),'-o',str(exe)],check=True,timeout=30,stdin=subprocess.DEVNULL)
    subprocess.run([str(exe)],check=True,timeout=10,stdin=subprocess.DEVNULL)
    print('PASS: actual carry helpers preserve the RGB565 page before BGR8 overwrite; top immediate/bottom 200 ms predicate')

if __name__=='__main__':main()
