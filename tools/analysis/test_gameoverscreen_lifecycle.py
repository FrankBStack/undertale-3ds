"""N admission failures and sequential room callers, using the product body.

Host services are spies; this neither draws pixels nor exercises an OS return.
"""
from pathlib import Path
import json, re, shutil, subprocess, sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import ROOT,SOURCE,PRELUDE,body

def fixture():
    source=(SOURCE/'ctr_gameoverscreen.inc').read_text(encoding='utf-8')
    text=PRELUDE.replace('static bool CtrLayout_targetsHeld(void){return true;}',
        'static bool held;static bool CtrLayout_targetsHeld(void){return held;}')
    text=text.replace('static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){(void)r;(void)below;(void)d;}',
        'static unsigned restores;static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){'
        '(void)d;if(below)abort();restores++;((CtrRenderer*)r)->displayDirty=true;}')
    text+='\n'.join(re.findall(r'(?m)^enum \{ GO_[^\n]+',source))+'\n'
    text+=body(source,'CtrGameover_pendingRoom')+'\n'
    text+=r'''
#define CHECK(c) do{if(!(c)){fprintf(stderr,"line %d\n",__LINE__);return 1;}}while(0)
int main(void){
 unsigned cases=0,acquired=0;int ages[]={0,2,3,-1},dest[]={-1,306,310,-200};
 for(unsigned original=0;original<2;original++)for(unsigned given=0;given<2;given++)
 for(unsigned same=0;same<2;same++)for(unsigned pair=0;pair<2;pair++)
 for(unsigned age=0;age<4;age++)for(unsigned d=0;d<4;d++){
  CtrRenderer renderer={0};Runner runner={.pendingRoom=dest[d],.currentRoomIndex=306,
    .frameCount=100+ages[age],.renderer=&renderer.base,.dataWin=(void*)(uintptr_t)(same?1:2)};
  renderer.base.runner=&runner;
  go.dw=(void*)1;go.id[GO_ROOM]=310;go.frame=100;go.flags=0;go.display=7;
  CtrScreens_game=original;CtrScreens_gameGiven=given;held=pair;realRooms=restores=0;
  Runner before=runner;
  CtrGameover_pendingRoom(&runner);
  bool want=same&&pair&&ages[age]>=0&&ages[age]<=2&&dest[d]==310;
  CHECK(realRooms==1&&restores==0);CHECK(memcmp(&before,&runner,sizeof(runner))==0);
  CHECK(CtrScreens_game==original&&CtrScreens_gameGiven==given);
  CHECK(go.flags==(want?(GO_ACTIVE|GO_ENTER|(original?GO_GAME:0)|(given?GO_GIVEN:0)):0));
  if(want){
   acquired++;
   // The real room delegate updates the room before any next main-loop caller.
   runner.currentRoomIndex=310;runner.pendingRoom=-1;
   CtrGameover_pendingRoom(&runner);CHECK(realRooms==2&&restores==0&&(go.flags&GO_ACTIVE));
   runner.pendingRoom=310;CtrGameover_pendingRoom(&runner);
   CHECK(realRooms==3&&restores==0&&(go.flags&GO_ACTIVE));
   runner.pendingRoom=-200;CtrGameover_pendingRoom(&runner);
   CHECK(realRooms==4&&restores==1&&go.flags==0&&renderer.displayDirty);
   CHECK(CtrScreens_game==original&&CtrScreens_gameGiven==given);
   runner.currentRoomIndex=-200;runner.pendingRoom=-1;
   CtrGameover_pendingRoom(&runner);CHECK(realRooms==5&&restores==1&&go.flags==0);
  }
  cases++;
 }
 printf("{\"admission_cases\":%u,\"acquired\":%u,\"save_files_opened\":0}\n",cases,acquired);
 return 0;
}
'''
    return text

class Lifecycle(unittest.TestCase):
    def test_admission_guards_and_sequential_room_callers(self):
        out=ROOT/'scratch/gameoverscreen-N-lifecycle';out.mkdir(parents=True,exist_ok=True)
        src=out/'lifecycle.c';src.write_text(fixture(),encoding='utf-8')
        cc=shutil.which('gcc') or shutil.which('clang');self.assertTrue(cc)
        p=subprocess.run([cc,'-std=c11','-O2','-Wall','-Wextra','-Werror',
            '-Wno-unused-function','-Wno-unused-variable','-Wno-unused-parameter',
            '-Wno-misleading-indentation','-I',str(SOURCE),str(src),'-o',str(out/'lifecycle.exe')],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=25)
        (out/'compile.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stdout+p.stderr);self.assertEqual(p.stdout+p.stderr,'')
        p=subprocess.run([str(out/'lifecycle.exe')],stdin=subprocess.DEVNULL,
            capture_output=True,text=True,timeout=5)
        (out/'run.log').write_text(p.stdout+p.stderr,encoding='utf-8')
        self.assertEqual(p.returncode,0,p.stderr)
        result=json.loads(p.stdout);self.assertEqual(result['admission_cases'],256)
        self.assertEqual(result['acquired'],8)
        (out/'results.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':unittest.main()
