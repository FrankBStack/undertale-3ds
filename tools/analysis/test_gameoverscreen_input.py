"""Game-over N keeps the frame's input take (battletouch's game-over tap, 11-14 ruling 1).

While N holds the screens (GO_ACTIVE) its display link returned without calling the rest of the display chain, so
inputlate's link, the frame's only CtrInput_take (and so battletouch's take wrap, the only route to btViewT's
game-over Z) never ran: on N5 (8d1d598bc) a tap on the game-over text did nothing. This compiles N's own
CtrGameover_display, inputlate's own link (z_inputlate.c) and the renderer's own setDisplay (ctr_renderer.c) on the
host, with spies for the take, the delivery and CtrLayout_display18. Host only: no 3DS compile, no SD, no GPU.
"""
from pathlib import Path
import json, re, shutil, subprocess, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import SOURCE, PRELUDE, body


def fixture():
    go = (SOURCE/'ctr_gameoverscreen.inc').read_text(encoding='utf-8')
    late = (SOURCE/'z_inputlate.c').read_text(encoding='utf-8')
    renderer = (SOURCE/'ctr_renderer.c').read_text(encoding='utf-8')
    old = 'typedef struct {Renderer base; bool displayDirty,inFrame,bottomYielded; struct {bool shown;} dlg;} CtrRenderer;'
    assert PRELUDE.count(old) == 1
    text = PRELUDE.replace(old, 'typedef struct {Renderer base; bool displayDirty,inFrame,bottomYielded; '
                           'struct {bool shown;} dlg; CtrDisplaySettings display; CtrDisplayCaps displayCaps;} CtrRenderer;')
    text += '\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+', go)) + '\n'
    text += r'''
typedef struct {uint32_t held,pressed,released;} CtrInputEdges;
typedef struct {int unused;} CtrInputStats;
typedef uint32_t u32;
static Runner* game; static Renderer* gameRenderer; static uint32_t previousKeys;
static bool inputlateInFrame,menuOpen,menuWasOpen,benchWasActive,benchPaused,suppressHeld,blockPolledKeys,playback;
static unsigned takes,sent,realSets; static const CtrInputMap* takenMap;
static bool CtrBench_running(void){return false;}
static u32 __real_hidKeysHeld(void){return 0;}
static u32 hidKeysDown(void){return 0;}
static CtrInputEdges CtrInput_take(const CtrInputMap* map,u32 held,u32 down,bool enabled,bool suppress,CtrInputStats* s){
 (void)held;(void)down;(void)suppress;(void)s;takes++;takenMap=map;
 return (CtrInputEdges){enabled?1u:0u,0,0};}
static void sendInput(Runner* r,CtrInputEdges in,uint32_t* keys){(void)r;*keys=in.held;sent++;}
'''
    text += body(renderer, 'CtrRenderer_setDisplay').replace(
        'void CtrRenderer_setDisplay(', 'static void __real_CtrRenderer_setDisplay_body(', 1) + '\n'
    text += ('static void __real_CtrRenderer_setDisplay(Renderer* r,const CtrDisplaySettings* s){'
             'realSets++;__real_CtrRenderer_setDisplay_body(r,s);}\n')
    link = body(late, 'CTR_DISPLAY_INPUTLATE')
    assert link.startswith('CODE void CTR_DISPLAY_INPUTLATE('), link[:60]
    text += link.replace('CODE void CTR_DISPLAY_INPUTLATE(', 'void __real_CtrRenderer_chainDisplayInputlate(', 1) + '\n'
    text += body(go, 'CtrGameover_display') + '\n'
    text += r'''
#define CHECK(c) do{if(!(c)){fprintf(stderr,"line %d: %s\n",__LINE__,#c);return 1;}}while(0)
static CtrRenderer R; static Runner G;
static void reset(unsigned flags,bool inFrame,bool lateFrame){
 memset(&R,0,sizeof R);R.base.runner=&G;R.displayCaps.wide=R.displayCaps.stereo=true;
 R.display.topMode=1;R.display.bottomMode=2;R.displayDirty=true;R.inFrame=inFrame;
 game=&G;gameRenderer=&R.base;inputlateInFrame=lateFrame;blockPolledKeys=false;
 go.flags=flags;takes=sent=realSets=0;takenMap=NULL;plainDisplay=0;
}
int main(void){
 CtrDisplaySettings player;memset(&player,0,sizeof player);player.topMode=0;player.bottomMode=1;
 unsigned cases=0;
 // Not held: the chain goes on through layout (spied here: it calls nothing further).
 reset(0,true,true);CtrGameover_display(&R.base,&player);
 CHECK(plainDisplay==1&&takes==0&&realSets==0);cases++;
 // Held, inside the frame: one take of the frame's input, with the renderer's own controls; the display is kept.
 for(unsigned enter=0;enter<2;enter++){
  reset(GO_ACTIVE|(enter?GO_ENTER:0),true,true);CtrDisplaySettings before=R.display;
  CtrGameover_display(&R.base,&player);
  CHECK(takes==1&&sent==1&&takenMap==&R.display.controls&&blockPolledKeys);
  CHECK(realSets==1&&memcmp(&before,&R.display,sizeof before)==0&&!R.displayDirty&&plainDisplay==0);cases++;
 }
 // Held, outside the renderer's frame (CtrLayout_moveUp's place): no take, as CtrLayout_display18 makes none there.
 reset(GO_ACTIVE,false,true);CtrDisplaySettings before=R.display;CtrGameover_display(&R.base,&player);
 CHECK(takes==0&&realSets==0&&memcmp(&before,&R.display,sizeof before)==0&&!R.displayDirty&&plainDisplay==0);cases++;
 // Held, inputlate's own guards say no (outside its frame bracket, or another renderer): no take.
 reset(GO_ACTIVE,true,false);CtrGameover_display(&R.base,&player);CHECK(takes==0&&!R.displayDirty);cases++;
 reset(GO_ACTIVE,true,true);gameRenderer=NULL;CtrGameover_display(&R.base,&player);CHECK(takes==0);cases++;
 // Thirty held frames in a row: one take each.
 reset(GO_ACTIVE,true,true);for(int f=0;f<30;f++){blockPolledKeys=false;CtrGameover_display(&R.base,&player);}
 CHECK(takes==30&&sent==30&&realSets==30&&R.display.bottomMode==2);cases++;
 printf("{\"cases\":%u,\"takes_last\":%u}\n",cases,takes);
 return 0;
}
'''
    return text


class GameoverInput(unittest.TestCase):
    def test_held_screens_still_take_the_frame_input(self):
        out = Path(__file__).resolve().parents[2]/'scratch/gameoverscreen-N-input'
        out.mkdir(parents=True, exist_ok=True)
        src = out/'input.c'
        src.write_text(fixture(), encoding='utf-8')
        cc = shutil.which('gcc') or shutil.which('clang')
        self.assertTrue(cc)
        p = subprocess.run([cc, '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-Wno-unused-function',
                            '-Wno-unused-variable', '-Wno-unused-parameter', '-Wno-unused-but-set-variable', '-Wno-misleading-indentation',
                            '-I', str(SOURCE), str(src), '-o', str(out/'input.exe')],
                           stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=25)
        (out/'compile.log').write_text(p.stdout+p.stderr, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stdout+p.stderr)
        p = subprocess.run([str(out/'input.exe')], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
        (out/'run.log').write_text(p.stdout+p.stderr, encoding='utf-8')
        self.assertEqual(p.returncode, 0, p.stderr)
        result = json.loads(p.stdout)
        self.assertEqual(result, {'cases': 7, 'takes_last': 30})


if __name__ == '__main__':
    unittest.main()
