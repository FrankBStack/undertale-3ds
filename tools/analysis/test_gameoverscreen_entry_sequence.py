"""MED-1: execute reviewed N entry/draw bodies and kill four behaviour mutants.

Host framebuffer/pacer spies prove call order and held-picture invariants,
not a physical LCD refresh or a continuous console black-flash witness.
No product files, player settings, game data or GPU services are written.
"""
from pathlib import Path
import hashlib
import json
import re
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import ROOT, SOURCE, body

PIN = 'a0bb7c0111c4254f0eba541240dc671061091a5629e2820453d2132ba622d980'
OUT = ROOT/'scratch/gameoverscreen-entry-sequence-r114'
MUTANTS = {
    'shift': ('                x += go.dx;\n                y += go.dy;', '                /* shift omitted */'),
    'record': ('                go.frame = runner->frameCount;', '                /* SOUL record omitted */'),
    'blank': ('    memset(spare, 0, 400u*240u*2u);', '    /* spare blank omitted */'),
    'show': ('    CtrScreens_pacerShow(GFX_TOP);', '    /* Top presentation omitted */'),
}

PRELUDE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#define nullptr NULL
#define GO_CODE
typedef uint8_t u8;
typedef struct {int tag;} DataWin;
typedef struct {int objectIndex; unsigned state;} Instance;
typedef struct {Instance* currentInstance;} VMContext;
typedef struct Renderer Renderer;
typedef struct {DataWin* dataWin; VMContext* vmContext; int frameCount,pendingRoom,currentRoomIndex; Renderer* renderer;} Runner;
struct Renderer {Runner* runner;};
typedef struct {Renderer base;bool displayDirty,bottomYielded;struct {bool shown;} dlg;} CtrRenderer;
typedef struct {float roomX0,roomY0,roomPerPx;} CtrBottomView;
enum {GFX_TOP,GFX_BOTTOM,GFX_LEFT=0,GSP_RGB565_OES=2,GSP_BGR8_OES=3};
static struct {DataWin* dw;uint16_t id[8];float shownX,shownY,dx,dy;int32_t frame;uint32_t display,flags;} go;
static uint8_t CtrScreens_game;
static bool CtrScreens_gameGiven,CtrScreens_onBottom;
static unsigned char topFront[400*240*2],topSpare[400*240*2],bottomFront[64],heldBottom[64];
static bool ready[2],idle,belowRole;
static unsigned topShows,bottomShows,fineDraws,coarseDraws,chains,begins;
static float drawnX,drawnY;
static char order[128];static unsigned orderN;
#define CHECK(e) do {if(!(e)){fprintf(stderr,"line %d: %s\n",__LINE__,#e);exit(1);}}while(0)
static void event(char c){CHECK(orderN+1<sizeof(order));order[orderN++]=c;order[orderN]=0;}
static bool zeroTop(void){for(unsigned i=0;i<sizeof(topFront);i++)if(topFront[i])return false;return true;}
static void CtrGpu_waitIdle(void){idle=true;event('I');}
static bool CtrPacer_screenReady(int s){return ready[s];}
static void CtrScreens_pacerWaitShown(int s,bool wait){CHECK(idle&&wait);ready[s]=true;event(s==GFX_TOP?'T':'B');}
static void CtrLog_setConsoleEnabled(bool enabled){CHECK(!enabled);event('C');}
static void CtrLog_beginConsole(void){event('L');}
static void CtrLog_endConsole(void){event('E');}
static u8* CtrPacer_backFramebuffer(int s,int eye){CHECK(s==GFX_TOP&&eye==GFX_LEFT&&ready[0]&&ready[1]);event('Q');return topSpare;}
static void GSPGPU_FlushDataCache(void* p,unsigned n){CHECK(p==topSpare&&n==sizeof(topSpare));event('F');}
static void CtrRenderer_bsLeave8(Renderer* r,bool whole){CHECK(!whole);event('S');}
static bool CtrLayout_gameoverRole(Renderer* r,bool below){CHECK(below);belowRole=true;event('R');return true;}
static void gfxSetScreenFormat(int s,int format){CHECK(ready[s]);CHECK(format==(s==GFX_TOP?GSP_RGB565_OES:GSP_BGR8_OES));event(s==GFX_TOP?'t':'b');}
static void gfxSetDoubleBuffering(int s,bool enabled){CHECK(s==GFX_BOTTOM?enabled:!enabled);event(s==GFX_BOTTOM?'D':'d');}
static void CtrScreens_pacerShow(int s){
 CHECK(s==GFX_TOP&&belowRole&&idle&&ready[0]&&ready[1]);
 CHECK(!memcmp(bottomFront,heldBottom,sizeof(heldBottom)));
 memcpy(topFront,topSpare,sizeof(topFront));topShows++;ready[0]=false;event('P');
}
static void CtrScreens_moveConsoles(bool below){CHECK(below);event('M');}
static void CtrPacer_setGameScreen(int s){CHECK(s==GFX_BOTTOM);event('G');}
static unsigned CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){CHECK(below&&d==0);event('V');return 0x123456u;}
static bool CtrBattlesplit_gameoverOther(void){return true;}
static bool CtrLayout_bottomView(Runner* r,CtrBottomView* v){*v=(CtrBottomView){20,40,2};return true;}
static bool CtrLayout_bottomSeam(int32_t* seam,int32_t* lift){*seam=100;*lift=30;return true;}
static bool CtrLayout_targetsHeld(void){return true;}
static void CtrBattlesplit_gameoverReturn(Renderer* r){abort();}
static bool CtrScreens_gameBelow(void){return CtrScreens_game&&CtrScreens_gameGiven;}
static void __real_Runner_handlePendingRoomChange(Runner* r){CHECK(!memcmp(bottomFront,heldBottom,sizeof(heldBottom)));r->currentRoomIndex=r->pendingRoom;r->pendingRoom=-1;}
static void CtrLayout_chain18(Renderer* r){chains++;}
static void CtrDlgtop_begin(Renderer* r){begins++;}
static void goResolve(Runner* r){CHECK(go.dw==r->dataWin);}
#define SPRITE_ARGS Renderer* renderer,int32_t tpag,float x,float y,float ox,float oy,float sx,float sy,float angle,uint32_t color,float alpha
static void ctrDrawSprite(SPRITE_ARGS){drawnX=x;drawnY=y;fineDraws++;if(go.flags&1u)CHECK(belowRole&&zeroTop());}
static void utkDrawSpriteBody(SPRITE_ARGS){drawnX=x;drawnY=y;coarseDraws++;CHECK(!(go.flags&1u));}
'''

MAIN = r'''
static void draw(bool coarse,Renderer* r,float x,float y){goDrawSprite(coarse,r,7,x,y,1,2,1,1,0,0xffffffu,1);}
int main(void){
 for(unsigned coarse=0;coarse<2;coarse++){
  DataWin dw={9};Instance inst={.objectIndex=1,.state=0xabcdef};VMContext vm={&inst};
  CtrRenderer r={0};Runner runner={.dataWin=&dw,.vmContext=&vm,.frameCount=100,.pendingRoom=-1,.currentRoomIndex=306,.renderer=&r.base};r.base.runner=&runner;
  memset(&go,0,sizeof(go));go.dw=&dw;go.frame=-4;
  for(unsigned i=0;i<8;i++)go.id[i]=(uint16_t)i;go.id[GO_ROOM]=310;
  CtrScreens_game=0;CtrScreens_gameGiven=false;CtrScreens_onBottom=false;
  memset(topFront,0xa2,sizeof(topFront));memset(topSpare,0xa1,sizeof(topSpare));
  memset(bottomFront,0x51,sizeof(bottomFront));memcpy(heldBottom,bottomFront,sizeof(heldBottom));
  topShows=bottomShows=fineDraws=coarseDraws=chains=begins=orderN=0;order[0]=0;
  ready[0]=ready[1]=idle=belowRole=false;
  draw(coarse,&r.base,120,220);
  CHECK(go.frame==100&&go.shownX==100&&go.shownY==240);
  CHECK(drawnX==120&&drawnY==220&&coarseDraws==coarse);
  CHECK(inst.objectIndex==1&&inst.state==0xabcdef);
  runner.pendingRoom=310;CtrGameover_pendingRoom(&runner);
  CHECK((go.flags&(GO_ACTIVE|GO_ENTER))==(GO_ACTIVE|GO_ENTER));
  CHECK(runner.currentRoomIndex==310&&topShows==0&&bottomShows==0);
  CHECK(!memcmp(bottomFront,heldBottom,sizeof(heldBottom)));
  CHECK(!strcmp(order,"C"));orderN=0;order[0]=0;
  runner.frameCount=101;CtrGameover_beginFrame(&r.base);
  CHECK(!strcmp(order,"ITBCLQFSRtbDPTdMGVE"));
  CHECK(topShows==1&&bottomShows==0&&zeroTop());
  CHECK(!memcmp(bottomFront,heldBottom,sizeof(heldBottom)));
  CHECK((go.flags&GO_ACTIVE)&&!(go.flags&GO_ENTER));
  CHECK(CtrScreens_onBottom&&CtrScreens_game==1&&CtrScreens_gameGiven);
  CHECK(go.display==0x123456u&&begins==1&&chains==0&&r.dlg.shown);
  inst.objectIndex=go.id[GO_DEFEATED];draw(coarse,&r.base,340,200);
  CHECK(drawnX==100&&drawnY==240&&go.dx==-240&&go.dy==40);
  CHECK(inst.objectIndex==go.id[GO_DEFEATED]&&inst.state==0xabcdef);
  runner.frameCount=120;CtrGameover_beginFrame(&r.base);draw(coarse,&r.base,340,200);
  CHECK(drawnX==100&&drawnY==240&&topShows==1&&bottomShows==0);
  runner.frameCount=159;CtrGameover_beginFrame(&r.base);inst.objectIndex=go.id[GO_SHARD];
  for(unsigned shard=0;shard<6;shard++){
   float x=340+(float)shard*3,y=200-(float)shard*5;
   draw(coarse,&r.base,x,y);CHECK(drawnX==x-240&&drawnY==y+40);
   CHECK(inst.objectIndex==go.id[GO_SHARD]&&inst.state==0xabcdef);
  }
  CHECK(fineDraws==(coarse?8u:9u)&&coarseDraws==coarse);
  CHECK(topShows==1&&bottomShows==0&&zeroTop());
  CHECK(!memcmp(bottomFront,heldBottom,sizeof(heldBottom)));
 }
 puts("entry/draw sequences PASS: fine + coarse; held Bottom, blank/show Top, SOUL + six shards");return 0;
}
'''


def fixture(source, mutant):
    # Pin the input before mutation. Mutants must compile and die on the C
    # behavioural checks, never on an asset/source hash assertion.
    if mutant:
        before, after = MUTANTS[mutant]
        assert source.count(before)==1, mutant
        source=source.replace(before,after)
    enums='\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+',source))
    return PRELUDE+enums+'\n'+'\n'.join(body(source,name) for name in
        ('goDrawSprite','goEnter','CtrGameover_beginFrame','CtrGameover_pendingRoom'))+MAIN


class EntrySequence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source=(SOURCE/'ctr_gameoverscreen.inc').read_text(encoding='utf-8')
        assert hashlib.sha256(cls.source.encode()).hexdigest()==PIN
        cls.cc=shutil.which('gcc') or shutil.which('clang')
        assert cls.cc
        OUT.mkdir(parents=True,exist_ok=True)
        cls.receipts=[]

    @classmethod
    def tearDownClass(cls):
        save=dict(source_path=str(SOURCE/'ctr_gameoverscreen.inc'),helper_sha256=PIN,host_only=True,product_changes=0,arms=cls.receipts)
        (OUT/'results.json').write_text(json.dumps(save,indent=2)+'\n',encoding='utf-8')

    def check_arm(self, mutant=None):
        name=mutant or 'baseline';path=OUT/(name+'.c');path.write_text(fixture(self.source,mutant))
        exe=path.with_suffix('.exe')
        command=[self.cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unused-function','-Wno-misleading-indentation',str(path),'-o',str(exe)]
        compile_result=subprocess.run(command,stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=25)
        path.with_suffix('.compile.log').write_text(compile_result.stdout+compile_result.stderr)
        self.assertEqual(compile_result.returncode,0,compile_result.stdout+compile_result.stderr)
        self.assertEqual(compile_result.stdout+compile_result.stderr,'')
        run=subprocess.run([str(exe)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=5)
        path.with_suffix('.run.log').write_text(run.stdout+run.stderr)
        self.receipts.append(dict(arm=name,compile_exit=compile_result.returncode,run_exit=run.returncode,stdout=run.stdout,stderr=run.stderr,source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
        self.assertEqual(run.returncode,1 if mutant else 0,(name,run.stdout,run.stderr))
        if mutant:
            expected = {'shift':'drawnX==100&&drawnY==240',
                        'record':'go.frame==100', 'blank':'zeroTop()',
                        'show':'!strcmp(order,'}[mutant]
            self.assertIn(expected,run.stderr,(name,run.stderr))

    def test_baseline(self): self.check_arm()
    def test_shard_shift_mutant_red(self): self.check_arm('shift')
    def test_soul_record_mutant_red(self): self.check_arm('record')
    def test_top_spare_blank_mutant_red(self): self.check_arm('blank')
    def test_top_presentation_mutant_red(self): self.check_arm('show')


if __name__=='__main__': unittest.main()
