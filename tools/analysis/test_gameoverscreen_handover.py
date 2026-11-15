"""Link-free N handover sequences; host service spies, no native OS/SD/GPU proof.

This supplemental audit uses the E-prime renderer's APT and screenshot/notice
prefix, with the unchanged N helper. It never invokes a 3DS compiler or build.
"""
from pathlib import Path
import hashlib,json,re,shutil,subprocess,sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import ROOT,SOURCE,PRELUDE,body
from gameoverscreen_frozen import FREEZE,frozen

BASE='ecbcd6e1a4590f085a11dfd72286d22c9b096913'  # read from committed excerpts (gameoverscreen_frozen)
assert BASE==FREEZE
HELPER_SHA='62448c29dd2ad1b56d7b875b81dfb6e3ad8f7d480c0b95f40c731cd4caf59f3b'

def fixture(mutant=None):
    go=(SOURCE/'ctr_gameoverscreen.inc').read_text()
    assert hashlib.sha256((SOURCE/'ctr_gameoverscreen.inc').read_bytes()).hexdigest()==HELPER_SHA
    renderer=frozen('ctr_renderer.c')
    text=PRELUDE.replace('bool displayDirty,inFrame,bottomYielded;',
        '''bool displayDirty,inFrame,bottomYielded,bottomBacklightOff;
 bool screenshotCaptured,screenshotRequested,screenshotTimingAffected,screenshotPlayer;
 uint64_t screenshotNoticeUntil;char screenshotSuffix[8];CtrDisplaySettings display;''')
    text=text.replace('static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){(void)r;(void)below;(void)d;}',
        '''static unsigned restores,restoreDisplay,configured,chainBegins,dlgtopBegins,shots;
static unsigned shotLCD;static char order[8];static unsigned orderN;
static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){
 if(below)abort();restores++;restoreDisplay=d;order[orderN++]='r';
 ((CtrRenderer*)r)->displayDirty=true;CtrScreens_onBottom=CtrScreens_gameBelow();
}'''.replace('CtrScreens_gameBelow()','(CtrScreens_game==1 && CtrScreens_gameGiven)'))
    text=text.replace('static void __real_Runner_handlePendingRoomChange(Runner* r){(void)r;realRooms++;}',
                      "static void __real_Runner_handlePendingRoomChange(Runner* r){(void)r;realRooms++;order[orderN++]='d';}")
    text+='\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+',go))+'\n'
    text+='''
typedef int APT_HookType;
enum {APTHOOK_ONSUSPEND,APTHOOK_ONRESTORE,APTHOOK_ONWAKEUP};
static bool gfxIsWide(void){return false;}
static void leaveWideMode(void){abort();}
static void goResolve(Runner* r){(void)r;abort();}
static void goEnter(CtrRenderer* r){(void)r;abort();}
static void CtrLayout_chain18(Renderer* r){(void)r;chainBegins++;}
static void CtrDlgtop_begin(Renderer* r){(void)r;dlgtopBegins++;}
static void configureScreens(CtrRenderer* r){configured++;r->displayDirty=false;}
static bool saveScreenshot(CtrRenderer* r,void* p,bool screens,bool player){
 (void)r;(void)p;(void)screens;(void)player;shots++;shotLCD=CtrScreens_onBottom;return true;}
static uint64_t osGetTime(void){return 10;}
'''
    text+=body(renderer,'onAptEvent')+'\n'
    # The frame's input take while N holds the screens (inputlate's link; 11-14 ruling 1).
    text+='''static unsigned inputTakes;static const CtrDisplaySettings* takenDisplay;
static void __real_CtrRenderer_chainDisplayInputlate(Renderer* r,const CtrDisplaySettings* s){
 (void)r;inputTakes++;takenDisplay=s;}
'''
    for name in ('CtrGameover_beginFrame','CtrGameover_display','CtrGameover_yield',
                 'CtrGameover_configure','CtrGameover_pendingRoom'):
        value=body(go,name)
        if mutant=='flags' and name=='CtrGameover_pendingRoom':
            assert value.count('            go.flags = 0;')==1
            value=value.replace('            go.flags = 0;','            /* mutation: flags retained */')
        if mutant=='restore' and name=='CtrGameover_pendingRoom':
            needle='            CtrRenderer_bsMoveGame(runner->renderer, false, go.display);'
            assert value.count(needle)==1
            value=value.replace(needle,'            /* mutation: restore omitted */')
        if mutant=='configure' and name=='CtrGameover_configure':
            value=value.replace('if ((go.flags & GO_ACTIVE)==0) configureScreens(renderer);','configureScreens(renderer);')
        if mutant=='dlgtop' and name=='CtrGameover_beginFrame':
            value=value.replace('    CtrDlgtop_begin(renderer);','    /* mutation: S4 begin omitted */')
        text+=value+'\n'
    prefix=body(renderer,'CtrRenderer_beginFrame')
    prefix=prefix[prefix.index('    r->screenshotCaptured'):prefix.index('    dlgBeginFrame')]
    assert prefix.count('configureScreens(r)')==1
    prefix=prefix.replace('configureScreens(r)','CtrGameover_configure(r)')
    text+='static void shotBegin(CtrRenderer* r){\n'+prefix+'}\n'
    text+=r'''
#define CHECK(e) do {if(!(e)){fprintf(stderr,"line %d: %s\n",__LINE__,#e);return 1;}}while(0)
int main(void){
 unsigned count=0;int destinations[]={-1,310,134,-200};
 for(unsigned original=0;original<2;original++)for(unsigned given=0;given<2;given++)
 for(unsigned cause=0;cause<5;cause++)for(unsigned dest=0;dest<4;dest++){
  CtrRenderer r={0};Runner runner={.pendingRoom=destinations[dest],.currentRoomIndex=310,.renderer=&r.base};
  r.base.runner=&runner;r.bottomBacklightOff=true;r.bottomYielded=true;r.dlg.shown=false;
  go.flags=GO_ACTIVE|GO_DELTA|(original?GO_GAME:0)|(given?GO_GIVEN:0);go.frame=121;go.display=0x135724;
  CtrScreens_game=CtrScreens_gameGiven=CtrScreens_onBottom=1;
  restores=restoreDisplay=configured=chainBegins=dlgtopBegins=shots=realRooms=orderN=plainDisplay=inputTakes=0;
  memset(order,0,sizeof(order));shotLCD=99;
  if(cause<3)onAptEvent(cause,&r);
  if(cause==3)r.screenshotRequested=true;
  if(cause==4)r.screenshotNoticeUntil=1;
  shotBegin(&r);CHECK(configured==0);CHECK(CtrScreens_onBottom==1);
  CHECK(shots==(cause==3));if(cause==3)CHECK(shotLCD==1);
  if(cause==4)CHECK(r.screenshotNoticeUntil==0);
  CtrGameover_beginFrame(&r.base);
  CHECK(!r.displayDirty&&!r.bottomYielded&&r.dlg.shown);CHECK(dlgtopBegins==1&&chainBegins==0);
  CHECK(r.bottomBacklightOff==(cause!=APTHOOK_ONRESTORE&&cause!=APTHOOK_ONWAKEUP));
  r.displayDirty=true;CtrDisplaySettings settings={0};CtrGameover_display(&r.base,&settings);
  CHECK(!r.displayDirty&&plainDisplay==0&&inputTakes==0);
  r.inFrame=true;r.displayDirty=true;CtrGameover_display(&r.base,&settings);r.inFrame=false;
  CHECK(!r.displayDirty&&plainDisplay==0&&inputTakes==1&&takenDisplay==&r.display);
  r.displayDirty=true;CtrGameover_yield(&r.base,true);CtrGameover_yield(&r.base,false);
  CHECK(!r.displayDirty&&!r.bottomYielded&&r.dlg.shown);
  CtrGameover_pendingRoom(&runner);CHECK(realRooms==1);
  if(dest<2){
   CHECK((go.flags&GO_ACTIVE)!=0);CHECK(restores==0&&orderN==1&&order[0]=='d');
   CHECK(CtrScreens_game==1&&CtrScreens_gameGiven&&CtrScreens_onBottom);
   shotBegin(&r);CHECK(configured==0);
  }else{
   CHECK(go.flags==0);CHECK(CtrScreens_game==original&&CtrScreens_gameGiven==given);
   CHECK(restores==1&&restoreDisplay==0x135724&&r.displayDirty);
   CHECK(orderN==2&&order[0]=='r'&&order[1]=='d');CHECK(go.frame==-4&&!r.dlg.shown);
   CHECK(CtrScreens_onBottom==(original&&given));
   shotBegin(&r);CHECK(configured==1&&!r.displayDirty);
   shotBegin(&r);CHECK(configured==1);
   CtrGameover_beginFrame(&r.base);CHECK(chainBegins==1);
  }
  count++;
 }
 printf("{\"sequence_cases\":%u,\"os_services\":\"spies\",\"sd_written\":false}\n",count);
 return 0;
}
'''
    return text

class Handover(unittest.TestCase):
    def test_deferred_setup_and_handover_mutations(self):
        out=ROOT/'scratch/gameoverscreen-handover-host-r47';out.mkdir(parents=True,exist_ok=True)
        cc=shutil.which('gcc') or shutil.which('clang');self.assertTrue(cc)
        receipts=[]
        for arm in ('baseline','flags','restore','configure','dlgtop'):
            source=out/(arm+'.c');source.write_text(fixture(None if arm=='baseline' else arm))
            exe=source.with_suffix('.exe')
            p=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
                '-Wno-unused-variable','-Wno-unused-parameter','-Wno-misleading-indentation',
                '-I',str(SOURCE),str(source),'-o',str(exe)],stdin=subprocess.DEVNULL,
                capture_output=True,text=True,timeout=25)
            source.with_suffix('.compile.log').write_text(p.stdout+p.stderr)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            self.assertEqual(p.stdout+p.stderr,'')
            result=subprocess.run([str(exe)],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=5)
            source.with_suffix('.run.log').write_text(result.stdout+result.stderr)
            self.assertEqual(result.returncode==0,arm=='baseline',(arm,result.stdout,result.stderr))
            if arm=='baseline':self.assertEqual(json.loads(result.stdout)['sequence_cases'],80)
            receipts.append(dict(arm=arm,exit=result.returncode,stdout=result.stdout,stderr=result.stderr,
                                 source_sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
        (out/'results.json').write_text(json.dumps(dict(base=BASE,helper_sha256=HELPER_SHA,
            host_cases=80,mutants_killed=4,arms=receipts,product_builds=0,console_claim=False),indent=2)+'\n')

if __name__=='__main__':unittest.main()
