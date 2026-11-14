"""Shared host hardware/stdio stubs for game-over policy tests."""
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'platform/3ds/source'

def body(text,name):
    match=re.search(r'(?m)^[^\n;{}]*\b'+re.escape(name)+r'\([^;{}]*\)\s*\{',text)
    assert match,name
    end=text.index('\n}',match.end())+2
    return text[match.start():end]

PRELUDE=r'''
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ctr_display.h"
#define nullptr NULL
#define GO_CODE
#define LATE
#define SCREENS_LATE
#define OPT_STATIC static
#define SETTINGS_VERSION 2
#define R_SUCCEEDED(x) ((x)>=0)
#define GSPLCD_SCREEN_TOP 1
#define logWarn(...) do { warnings++; fprintf(stderr,__VA_ARGS__); } while (0)
static int warnings;
typedef struct Renderer Renderer;
typedef struct Runner {int pendingRoom,currentRoomIndex,frameCount; void* dataWin; Renderer* renderer;} Runner;
struct Renderer {Runner* runner;};
typedef struct {Renderer base; bool displayDirty,inFrame,bottomYielded; struct {bool shown;} dlg;} CtrRenderer;
static struct {void* dw; uint16_t id[8]; int frame; unsigned display,flags;} go;
uint8_t CtrScreens_game,CtrScreens_gameAtOpen,CtrOptmenu_onTop;
bool CtrScreens_gameGiven,CtrScreens_onBottom,CtrScreens_topBacklightOff,CtrSave_failed;
static struct {bool menuIsOpen;} g;
static int displayedBelow,realRooms,plainDisplay;
static int physicalMoves;
static bool CtrScreens_noticeShown,screensBlankDue;
static void CtrLayout_display18(Renderer* r,const CtrDisplaySettings* s){(void)r;(void)s;plainDisplay++;}
static void CtrBattlesplit_gameoverReturn(Renderer* r){(void)r;}
static void CtrRenderer_bsMoveGame(Renderer* r,bool below,unsigned d){(void)r;(void)below;(void)d;}
static bool CtrScreens_gameBelow(void){return CtrScreens_game==1 && CtrScreens_gameGiven;}
static bool CtrLayout_gameoverRole(Renderer* r,bool below){(void)r;displayedBelow=below;return true;}
static bool CtrLayout_targetsHeld(void){return true;}
static void CtrLayout_yield8(Renderer* r,bool y){(void)r;(void)y;}
static void screensConfigureKeepBottom(CtrRenderer* r){(void)r;physicalMoves++;CtrScreens_onBottom=CtrScreens_gameBelow();}
static void CtrScreens_screenshotNotice(bool b){(void)b;}
static void CtrScreens_flushConsoles(void){}
static void __real_Runner_handlePendingRoomChange(Runner* r){(void)r;realRooms++;}
static int CtrDimlight_topOnInit(void){return 0;}
static void GSPLCD_PowerOnBacklight(int s){(void)s;}
static void gspLcdExit(void){}
static void CtrLog_setConsoleEnabled(bool e){(void)e;}
void CtrDisplay_defaults(CtrDisplaySettings* s){memset(s,0,sizeof(*s));}
static void screensLoad(CtrDisplaySettings* s,const char* p,CtrDisplayCaps caps,uint8_t* game){
 (void)s;(void)caps;FILE* f=fopen(p,"r");char line[256];int v=0;*game=0;
 if(!f)return;while(fgets(line,sizeof(line),f))if(sscanf(line," game_screen = %d",&v)==1)*game=(uint8_t)v;fclose(f);
}
static void __real_CtrDisplay_saveEdits(const CtrDisplaySettings* a,const CtrDisplaySettings* b,const char* p,CtrDisplayCaps c){(void)a;(void)b;(void)p;(void)c;}
static const char appendMode[]="a",gameLine[]="game_screen = %d\n";
static void CtrNotice_writeDismissals(FILE* f){(void)f;}
'''
