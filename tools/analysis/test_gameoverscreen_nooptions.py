"""N policy through frozen release menu composition and real input edges.

Hardware, font, clock and audio services are stubs. No SD path is opened.
Before N, missing guards use the existing unguarded delegate paths, so these
tests report behavior failures rather than merely missing symbol failures.
"""
from pathlib import Path
import json, re, shutil, subprocess, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import ROOT, SOURCE, PRELUDE, body
from gameoverscreen_frozen import FREEZE, frozen  # the frozen excerpts: no git show of a private commit

assert FREEZE == 'ecbcd6e1a4590f085a11dfd72286d22c9b096913'
ELFS = []


PRE = r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_display.h"
#include "ctr_input_combo.h"
#define nullptr NULL
#define GO_CODE
#define MT_CODE
#define UPD1_CODE
#define BT_CODE3
#define LY_CODE
#define LY_CODE18
#define ARGUI_NOINLINE
#define LY_NOTE(...) ((void)0)
#define LY_UP_ON 1
#define LY_UP_WAIT 2
#define LY_UP18() ((lyRoot2.up18 & LY_UP_ON) != 0 && CtrScreens_game == 0)
typedef struct {bool open,edited;CtrDisplaySettings settings;} CtrMenu;
typedef struct {int unused;} PrintConsole;
typedef struct Renderer {int unused;} Renderer;
typedef struct {Renderer base;bool displayDirty,bottomYielded;struct {bool shown;} dlg;} CtrRenderer;
typedef struct {const char *label,*value,*help;bool dis;} ObRow;
typedef ObRow LyOptRow;
static struct {unsigned flags;} go;
static struct {uint8_t up18;} lyRoot2;
static uint8_t CtrScreens_game,CtrScreens_gameAtOpen;
static bool CtrScreens_onBottom;
static int opens,composes,sounds,saves,holds,configured,moved,shots,shotLCD;
static int layoutYields;
typedef int gfxScreen_t;
enum {GFX_LEFT=0,GSP_RGB565_OES=2};
static struct {bool menuIsOpen;void* texCache;unsigned hintFrames;} g={false,(void*)1,0};
static unsigned gFpsScreen=2,gHintSeen=1;
static bool CtrScreens_otherOff;
static int painted=-1;
static bool CtrBench_running(void){return false;}
static int gfxGetScreenFormat(int s){return s==0?GSP_RGB565_OES:0;}
static void* CtrPacer_backFramebuffer(int s,int eye){(void)eye;painted=s;return (void*)1;}
static struct {int page;uint8_t cur[4];} CtrOptbattle_state;
static struct {uint8_t pageRow;} btm;
#define obOn btm.pageRow
enum {OB_LAYOUT=128,OB_STYLUS,OB_CONTROLS=4,OB_ROWS=12};
static const uint8_t obOrder[]={0,1,2,3,4,OB_LAYOUT,OB_STYLUS,5,6,7,8,9};
static const uint8_t obY[]={8,22,42,56,76,90,104,124,138,152,182,196};
enum {OB_LBL_LAYOUT,OB_LBL_STYLUS,OB_NEEDS_TOP,OB_ORIGINAL,OB_SPLIT,OB_HLP_ORIGINAL,
 OB_HLP_SPLIT,OB_OFF,OB_MENUS,OB_SOUL,OB_HLP_OFF,OB_HLP_MENUS,OB_HLP_SOUL,OB_HEART};
enum {LY_OPT_GAME,LY_OPT_DIALOGUE,CTR_LAYOUT_ROW_GAME,CTR_LAYOUT_ROW_TEXT};
static const char lyValBottom[]="Bottom",lyHlpBottom[]="Bottom help",lyNeedsTop[]="Needs Top";
static const char* obNth(unsigned i){(void)i;return "row";}
static unsigned Battletouch_zero18;
static unsigned CtrBattlesplit_setting(void){return 1;}
static int btMode(void){return 0;}
static const char* Battletouch_obValue18(unsigned i){return obNth(i);}
static const char* Battletouch_obHelp18(unsigned i){return obNth(i);}
static const char* CtrLayout_menuNoteFor(unsigned i){(void)i;return NULL;}
static void CtrOptbattle_row(const CtrMenu* m,unsigned p,unsigned i,LyOptRow* r){
 (void)m;(void)p;(void)i;*r=(LyOptRow){"Game",CtrScreens_game?"Bottom":"Top","help",false};
}
static void CtrOptbattle_composeOriginal(const CtrMenu* m,uint16_t* fb){(void)m;(void)fb;}
static void CtrOptmenu_text(uint16_t* f,int x,int y,const char* s,unsigned c){(void)f;(void)x;(void)y;(void)s;(void)c;}
static uint16_t frame[320*240];
static void CtrOptbattle_compose(const CtrMenu*,uint16_t*);
static void CtrArgui_menuOpen(CtrMenu* m,PrintConsole* c,const CtrDisplaySettings* d,CtrDisplayCaps caps){
 (void)c;(void)caps;m->open=true;m->settings=*d;holds++;CtrOptbattle_compose(m,frame);sounds++;
}
static struct {CtrDisplaySettings before;const CtrDisplaySettings* display;CtrMenu* menu;} upd1Options;
static struct {int kind;bool timing;uint64_t capsStart,capsTicks,openStart,openTicks;} mt;
static struct {bool previewsDue;unsigned idle;} mtg;
enum {MT_OPEN=1};
static uint64_t mtTick(void){return 0;}
static void mtBegin(int k){mt.kind=k;opens++;}
static void CtrLayout_yield8(Renderer* r,bool y){(void)r;(void)y;layoutYields++;}
static void configureScreens(CtrRenderer* r);
static void CtrGameover_configure(CtrRenderer* r);
static void CtrLayout_optRow(const void*,uint32_t,uint32_t,void*);
static void CtrMenutime_open(CtrMenu*,PrintConsole*,const CtrDisplaySettings*,CtrDisplayCaps);
static void CtrLog_setConsoleEnabled(bool b){(void)b;}
static CtrDisplayCaps CtrRenderer_capsAuditfixh(void* r){(void)r;CtrDisplayCaps c={0};return c;}
#define logInfo(...) ((void)0)
'''


def fixture():
    layout=frozen('z_layout.c'); battle=frozen('z_battletouch.c'); menu=frozen('z_menutime.c')
    go=(SOURCE/'ctr_gameoverscreen.inc').read_text(); main=frozen('main.c')
    enums='\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+',go))
    text=PRE+enums+'\n'
    for name in ('lyUpFlip18','lyOptRow18','CtrLayout_optRow'):
        text+=body(layout,name)+'\n'
    for name in ('obRow','obCursor','CtrOptbattle_compose'):
        b=body(battle,name)
        if name=='CtrOptbattle_compose':b=b.replace('{','{\ncomposes++;',1)
        text+=b+'\n'
        if name=='obRow':
            # C-prime's real compose now reaches this grey-row adapter first.
            # Keep that production body in the fixture instead of bypassing it.
            text+='#define BT_CODEG\n#define CTR_BATTLE_LAYOUT_TOP 2\n'
            text+='#define Battletouch_obRowOld obRow\n'
            text+=body(battle,'btObRowGrey')+'\n'
            text+='#define Battletouch_obRowGrey btObRowGrey\n'
    text+=body(frozen('z_upd1_options.c'),'Upd1_menuOpen')+'\n'+body(menu,'CtrMenutime_open')+'\n'
    if '__wrap_CtrMenutime_open(' in go:
        text+='#define __real_CtrMenutime_open CtrMenutime_open\n'+body(go,'__wrap_CtrMenutime_open')+'\n'
    else:
        text+='#define __wrap_CtrMenutime_open CtrMenutime_open\n'
    # Production beginFrame setup prefix: execute its dirty writes and exact
    # configure-call policy; filesystem/framebuffer readback is a service stub.
    renderer=frozen('ctr_renderer.c')
    prefix=body(renderer,'CtrRenderer_beginFrame')
    prefix=prefix[prefix.index('    r->screenshotCaptured'):prefix.index('    dlgBeginFrame')]
    text+='''
static void configureScreens(CtrRenderer* r){(void)r;configured++;lyUpFlip18();if(CtrScreens_game!=CtrScreens_onBottom){moved++;CtrScreens_onBottom=CtrScreens_game;}}
static bool saveScreenshot(void* r,void* path,bool notice,bool player){(void)r;(void)path;(void)notice;(void)player;shots++;shotLCD=CtrScreens_onBottom;return true;}
static uint64_t osGetTime(void){return 10;}
typedef struct {bool screenshotCaptured,screenshotRequested,screenshotTimingAffected,screenshotPlayer,displayDirty;uint64_t screenshotNoticeUntil;char screenshotSuffix[8];} ShotState;
'''
    if 'CtrGameover_configure(' in go:text+=body(go,'CtrGameover_configure')+'\n'
    else:text+='static void CtrGameover_configure(CtrRenderer* r){configureScreens(r);}\n'
    prefix=prefix.replace('configureScreens(r)','CtrGameover_configure((CtrRenderer*)r)')
    text+='static void shotBegin(ShotState* r){\n'+prefix+'}\n'
    text+=body(go,'CtrGameover_yield')+'\n'
    paint=body(frozen('ctr_argui.c'),'arguiPaintScreen')
    text+=paint[:paint.index('#if defined(ENABLE_WAD17)')]+'}\n'
    # The actual main ordinary and scheduled open blocks, with the linker target
    # made explicit. This tests menu.open/compose, never the schedule log text.
    ordinary=main[main.index('        bool openMenu ='):main.index('        } else if (menu.open)')]+ '\n        }\n'
    scheduled=main[main.index('        if (autopauseLeft < 0'):main.index('        if (autopauseLeft > 0')]
    for name,block in [('ordinary',ordinary),('scheduled',scheduled)]:
        text+='static void '+name+'(CtrMenu* m,CtrInputComboAction combo){\nCtrMenu menu=*m;bool benchActive=false;unsigned down=0;void* renderer=NULL;CtrDisplaySettings display={0},displayAtMenuOpen={0};PrintConsole menuConsole={0};int autopauseLeft=-1,autopause[]={10,3};struct {int frameCount;} runnerValue={10},*runner=&runnerValue;\n'
        text+='#define arrlen(a) (sizeof(a)/sizeof((a)[0]))\n'
        text+=block.replace('CtrMenu_open(', '__wrap_CtrMenutime_open(')+'\n*m=menu;\n}\n'
    text+=r'''
int main(int argc,char** argv){
 if(argc!=4)return 90;int original=atoi(argv[1]),attempts=atoi(argv[2]),mode=atoi(argv[3]);
 CtrMenu menu={0};CtrInputCombo input={0};CtrInputComboAction combo={0};
 go.flags=GO_ACTIVE;lyRoot2.up18=original?LY_UP_ON:0;
 CtrScreens_game=CtrScreens_onBottom=1;CtrScreens_gameAtOpen=original;
 if(mode==0){for(int i=0;i<attempts;i++){
   combo=CtrInputCombo_step(&input,CTR_COMBO_SELECT,CTR_COMBO_SELECT,0);ordinary(&menu,combo);
   combo=CtrInputCombo_step(&input,0,0,CTR_COMBO_SELECT);ordinary(&menu,combo);
 }}
 if(mode==1)scheduled(&menu,combo);
 if(mode==2||mode==3){ShotState shot={0};shot.screenshotRequested=mode==2;shot.screenshotNoticeUntil=mode==3?1:0;shotBegin(&shot);}
 if(mode==4||mode==5){CtrRenderer r={0};r.displayDirty=true;r.bottomYielded=true;CtrGameover_yield(&r.base,true);CtrGameover_yield(&r.base,false);if(r.bottomYielded||r.displayDirty||!r.dlg.shown)return 92;}
 arguiPaintScreen(NULL,false);if(painted!=1)return 93;
 printf("{\"open\":%d,\"opens\":%d,\"compose\":%d,\"sounds\":%d,\"holds\":%d,\"saves\":%d,\"raw\":%d,\"up\":%d,\"at_open\":%d,\"configured\":%d,\"moved\":%d,\"shots\":%d,\"shot_lcd\":%d,\"layout_yields\":%d,",menu.open,opens,composes,sounds,holds,saves,CtrScreens_game,lyRoot2.up18,CtrScreens_gameAtOpen,configured,moved,shots,shotLCD,layoutYields);
 /* Same consumed input state crosses hand-back; no replay until a new press. */
 go.flags=0;menu.open=false;combo=CtrInputCombo_step(&input,0,0,0);ordinary(&menu,combo);int replay=menu.open;
 combo=CtrInputCombo_step(&input,CTR_COMBO_SELECT,CTR_COMBO_SELECT,0);ordinary(&menu,combo);
 combo=CtrInputCombo_step(&input,0,0,CTR_COMBO_SELECT);ordinary(&menu,combo);
 printf("\"replay\":%d,\"fresh_open\":%d,\"fresh_compose\":%d}\n",replay,menu.open,composes);
 return 0;
}
'''
    return text


class NoOptions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'scratch/gameoverscreen-N-host';cls.out.mkdir(parents=True,exist_ok=True)
        src=cls.out/'release.c';src.write_text(fixture());cls.exe=cls.out/'release.exe'
        cc=shutil.which('gcc') or shutil.which('clang');assert cc
        p=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
                          '-Wno-unused-variable','-Wno-unused-but-set-variable','-Wno-unused-parameter',
                          '-Wno-misleading-indentation','-I',str(SOURCE),str(src),'-o',str(cls.exe)],
                         stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=25)
        (cls.out/'compile.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stdout+p.stderr
        cls.results=[]

    def case(self,original=1,attempts=1,mode=0):
        p=subprocess.run([str(self.exe),str(original),str(attempts),str(mode)],stdin=subprocess.DEVNULL,
                         capture_output=True,text=True,timeout=5,check=True)
        r=json.loads(p.stdout);self.results.append(dict(original=original,attempts=attempts,mode=mode,result=r))
        (self.out/'results.json').write_text(json.dumps(self.results,indent=2)+'\n');return r

    def test_release_select_drop_untouched_single_double_both_preferences(self):
        for original in (0,1):
            for attempts in (0,1,2):
                with self.subTest(original=original,attempts=attempts):
                    r=self.case(original,attempts)
                    for field in ('open','opens','compose','sounds','holds','saves','replay'):
                        self.assertEqual(r[field],0,field)
                    self.assertEqual(r['raw'],1);self.assertEqual(r['up'],original)
                    self.assertEqual(r['at_open'],original);self.assertEqual(r['fresh_open'],1)
                    self.assertEqual(r['fresh_compose'],1)

    def test_schedule_asserts_actual_open_and_compose(self):
        r=self.case(mode=1);self.assertEqual(r['open'],0);self.assertEqual(r['compose'],0)
        self.assertEqual(r['raw'],1);self.assertEqual(r['up'],1)

    def test_bottom_player_screenshot_is_taken_of_held_bottom(self):
        r=self.case(mode=2);self.assertEqual(r['shots'],1);self.assertEqual(r['shot_lcd'],1)
        self.assertEqual(r['configured'],0);self.assertEqual(r['moved'],0)
        self.assertEqual(r['raw'],1);self.assertEqual(r['up'],1)

    def test_bottom_player_notice_expiry_cannot_move(self):
        r=self.case(mode=3);self.assertEqual(r['configured'],0);self.assertEqual(r['moved'],0)
        self.assertEqual(r['raw'],1);self.assertEqual(r['up'],1)

    def test_home_and_sleep_use_held_role_yield(self):
        for mode in (4,5):
            r=self.case(mode=mode);self.assertEqual(r['layout_yields'],0)
            self.assertEqual(r['raw'],1);self.assertEqual(r['up'],1)


def handback_fixture(mutant=None):
    """Run the product hand-back, observing its hardware restore service call."""
    go=(SOURCE/'ctr_gameoverscreen.inc').read_text()
    text=PRELUDE.replace(
        'static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){(void)r;(void)below;(void)d;}',
        '''static unsigned restoreCount,restoreDisplay;static bool restoreBelow;
static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){
 restoreCount++;restoreBelow=below;restoreDisplay=d;
 ((CtrRenderer*)r)->displayDirty=true;CtrScreens_onBottom=CtrScreens_game&&CtrScreens_gameGiven;
}''')
    text+='\n#include "ctr_input_combo.h"\n'
    text+='\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+',go))+'\n'
    text+='''typedef struct {bool open;} CtrMenu;
typedef struct {int unused;} PrintConsole;
static unsigned opens;
static void __real_CtrMenutime_open(void* m,PrintConsole* c,const CtrDisplaySettings* s,CtrDisplayCaps caps){
 (void)c;(void)s;(void)caps;((CtrMenu*)m)->open=true;opens++;
}
'''
    pending=body(go,'CtrGameover_pendingRoom')
    needle={'flags':'            go.flags = 0;',
            'restore':'            CtrRenderer_bsMoveGame(runner->renderer, false, go.display);'}
    if mutant:
        assert pending.count(needle[mutant])==1
        pending=pending.replace(needle[mutant],'            /* removed by host mutation check */')
    text+=pending+'\n'+body(go,'__wrap_CtrMenutime_open')+'\n'
    text+=r'''
int main(int argc,char** argv){
 if(argc!=4)return 90;unsigned original=(unsigned)atoi(argv[1]),given=(unsigned)atoi(argv[2]);
 CtrRenderer renderer={0};Runner runner={.pendingRoom=atoi(argv[3]),.currentRoomIndex=99,.renderer=&renderer.base};
 renderer.base.runner=&runner;renderer.dlg.shown=true;
 go.flags=GO_ACTIVE|GO_DELTA|(original?GO_GAME:0)|(given?GO_GIVEN:0);
 go.display=0x135724u;go.frame=121;CtrScreens_game=CtrScreens_gameGiven=CtrScreens_onBottom=1;
 CtrGameover_pendingRoom(&runner);
 CtrMenu menu={0};CtrInputCombo input={0};CtrDisplaySettings settings={0};CtrDisplayCaps caps={0};
 CtrInputComboAction combo=CtrInputCombo_step(&input,CTR_COMBO_SELECT,CTR_COMBO_SELECT,0);
 if(combo.menu)__wrap_CtrMenutime_open(&menu,NULL,&settings,caps);
 combo=CtrInputCombo_step(&input,0,0,CTR_COMBO_SELECT);
 if(combo.menu)__wrap_CtrMenutime_open(&menu,NULL,&settings,caps);
 printf("{\"flags\":%u,\"raw\":%u,\"given\":%u,\"dirty\":%u,\"restore_count\":%u,\"restore_below\":%u,\"restore_display\":%u,\"frame\":%d,\"shown\":%u,\"rooms\":%d,\"open\":%u,\"opens\":%u}\n",
 go.flags,CtrScreens_game,CtrScreens_gameGiven,renderer.displayDirty,restoreCount,restoreBelow,restoreDisplay,go.frame,renderer.dlg.shown,realRooms,menu.open,opens);
 return 0;
}
'''
    return text


class HandBack(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out=ROOT/'scratch/gameoverscreen-N-handback';cls.out.mkdir(parents=True,exist_ok=True)
        cls.exes={};cls.results=[]
        cc=shutil.which('gcc') or shutil.which('clang');assert cc
        for label in ('stock','flags','restore'):
            src=cls.out/(label+'.c');src.write_text(handback_fixture(None if label=='stock' else label))
            exe=src.with_suffix('.exe')
            p=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
                       '-Wno-unused-variable','-Wno-unused-parameter','-Wno-misleading-indentation',
                       '-I',str(SOURCE),str(src),'-o',str(exe)],stdin=subprocess.DEVNULL,
                       capture_output=True,text=True,timeout=25)
            src.with_suffix('.log').write_text(p.stdout+p.stderr)
            assert p.returncode==0,p.stdout+p.stderr
            cls.exes[label]=exe

    def case(self,label,original,given,to):
        p=subprocess.run([str(self.exes[label]),str(original),str(given),str(to)],
                         stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=5,check=True)
        r=json.loads(p.stdout)
        self.results.append(dict(arm=label,original=original,given=given,to=to,result=r))
        (self.out/'results.json').write_text(json.dumps(self.results,indent=2)+'\n')
        return r

    def assert_handback(self,r,original,given):
        self.assertEqual(r['flags'],0)
        self.assertEqual(r['raw'],original);self.assertEqual(r['given'],given)
        self.assertEqual(r['restore_count'],1);self.assertEqual(r['restore_below'],0)
        self.assertEqual(r['restore_display'],0x135724);self.assertEqual(r['dirty'],1)
        self.assertEqual(r['frame'],-4);self.assertEqual(r['shown'],0)
        self.assertEqual(r['rooms'],1);self.assertEqual(r['open'],1);self.assertEqual(r['opens'],1)

    def test_room_exit_and_restart_restore_and_allow_select(self):
        for to in (100,-200):
            for original in (0,1):
                for given in (0,1):
                    with self.subTest(to=to,original=original,given=given):
                        self.assert_handback(self.case('stock',original,given,to),original,given)

    def test_each_removed_handback_operation_is_detected(self):
        for label in ('flags','restore'):
            for to in (100,-200):
                with self.subTest(mutant=label,to=to):
                    r=self.case(label,0,0,to)
                    with self.assertRaises(AssertionError):self.assert_handback(r,0,0)
                    if label=='flags':
                        self.assertNotEqual(r['flags'],0);self.assertEqual(r['open'],0)
                    else:
                        self.assertEqual(r['restore_count'],0);self.assertEqual(r['dirty'],0)


class Routing(unittest.TestCase):
    def test_scoped_setup_retarget_and_fail_closed(self):
        import utwindow_compile as adapter
        self.assertTrue(hasattr(adapter,'route_gameover_setup'),'missing setup routing')
        sample='CtrRenderer_beginFrame:\n\tbl configureScreens\n\t.size CtrRenderer_beginFrame, .-CtrRenderer_beginFrame\nother:\n\tbl configureScreens\n'
        routed=adapter.route_gameover_setup(sample)
        self.assertEqual(routed,sample.replace('bl configureScreens','bl CtrGameover_configure',1))
        for bad in (sample.replace('\tbl configureScreens\n','',1),sample.replace('\tbl configureScreens\n','\tbl configureScreens\n'*2,1)):
            with self.assertRaises(AssertionError):adapter.route_gameover_setup(bad)

    def test_no_menu_route_and_outer_link_wrapper(self):
        import utwindow_compile as adapter
        self.assertFalse(hasattr(adapter,'route_menu'))
        self.assertFalse(hasattr(adapter,'compile_menu'))
        go=(SOURCE/'ctr_gameoverscreen.inc').read_text()
        self.assertNotIn('CtrGameover_menuRow',go);self.assertNotIn('CtrGameover_menuActivate',go)
        cmake=(ROOT/'platform/3ds/CMakeLists.txt').read_text()
        self.assertIn('--wrap=CtrMenutime_open',cmake)


class Linked(unittest.TestCase):
    def test_linked_outer_opens_and_setup(self):
        if not ELFS:self.skipTest('no --elf; product link belongs to integrate21')
        tools=Path('C:/devkitPro/devkitARM/bin')
        for elf in ELFS:
            symbols={}
            nm=subprocess.check_output([str(tools/'arm-none-eabi-nm.exe'),'-S','--defined-only',elf],
                                       stdin=subprocess.DEVNULL,timeout=60,text=True)
            for line in nm.splitlines():
                p=line.split()
                if len(p)==4 and p[2] in 'tT':symbols[p[3]]=(int(p[0],16),int(p[1],16))
            edges=(('main','__wrap_CtrMenutime_open',2),
                   ('__wrap_CtrMenutime_open','CtrMenutime_open',1),
                   ('CtrRenderer_beginFrame','CtrGameover_configure',1),
                   ('CtrGameover_configure','configureScreens',1))
            for caller,callee,count in edges:
                address,size=symbols[caller]
                dis=subprocess.check_output([str(tools/'arm-none-eabi-objdump.exe'),'-d','--no-show-raw-insn',
                         f'--start-address={address:#x}',f'--stop-address={address+size:#x}',elf],
                         stdin=subprocess.DEVNULL,text=True,timeout=60)
                self.assertEqual(len(re.findall(r'\sb(?:l|lx|\w\w)?\s+[0-9a-f]+ <'+re.escape(callee)+r'>',dis)),
                                 count,(elf,caller,callee))


if __name__=='__main__':
    while '--elf' in sys.argv:
        i=sys.argv.index('--elf');ELFS.append(sys.argv[i+1]);del sys.argv[i:i+2]
    unittest.main()
