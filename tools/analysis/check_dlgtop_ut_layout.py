"""Exact-layout and byte-scope proof for retained cold loading slots on 75zq."""
from pathlib import Path
import argparse,hashlib,json,re,struct,subprocess,sys
UNIT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(Path(__file__).resolve().parent))
import check_layout as layout
from arm_got_permutation import ElfBytes,ArmMetadata

def no_fallthrough(word):
 # ARM unconditional B/BX, or an unconditional load/pop restoring pc.
 # Kept local so this public gate needs no unrelated pacer test fixtures.
 if word>>28 != 14:return False
 return ((word&0x0f000000)==0x0a000000 or
         (word&0x0ffffff0)==0x012fff10 or
         ((word&0x0e100000)==0x08100000 and bool(word&0x8000)) or
         ((word&0x0c10f000)==0x0410f000))

# psBits is cold setup text: its clipping callee shrinks the stack frame by 8 B.
# Its original extent remains, with an independently checked unreachable zero tail.
COLD={'Loadgame_carryCopy','Loadgame_restoreMenu','CtrBootlog_hide','CtrScreens_moveConsoles',
      'lsClear','lsDrawText','lsDrawDog',
      'lsBegin','lsDrawEye','lsPresent','lsStep','lsStep.constprop.0','lsFinish',
      'lsDataWin','lsPackRun','psBits','psDrawEye','psPresent','psSaveShot','BxHash_present'}
REDIRECTS={'main':{'consoleInit':'__wrap_consoleInit'},
 'screensDestroy':{'screensMoveGame':'Loadgame_keepScreen'},
 'screensCarry':{'memcpy':'Loadgame_carryCopy'},
 'lsDrawText':{'lsRect':'Loadgame_rect'},
 'psBits':{'psRect':'Loadgame_rect'},
 'lsDogDraw':{'lsDogRect':'Loadgame_rect'}}

def layout_command(base,cand,rename,game,object_waivers=None):
 # A manifest pins the exact ELF pair and proves each rename's destination; check_layout owns that proof.
 waivers=['--object-waivers',str(object_waivers),'--game',game] if object_waivers else []
 return ['py','-3','-I',str(UNIT/'tools/analysis/check_layout.py'),str(base),str(cand),'--full',
         *[arg for n in rename for arg in ('--allow',n)],*waivers]

def expected_main_redirects(player_baseline,composed_baseline):
 # fa0612c9d predates main's three redirects; a reviewed player tip or a composed zq base already holds them.
 return 0 if player_baseline or composed_baseline else 3

def prove(base,cand,out,game,model,player_baseline=False,object_waivers=None,composed_baseline=False):
 target=game+'-'+model
 a,b=[layout.load(p,layout.tool('nm',None),layout.tool('readelf',None)) for p in (base,cand)]
 # Compiler-local switch names may change their numeric suffix. Prove every
 # table's identical extent and bytes before allowing only this rename class.
 def switches(image,path):
  return sorted((x,s,ElfBytes(path).read(x,s)) for (n,k),values in image.symbols.items()
                if re.fullmatch(r'CSWTCH\.\d+',n) for x,s in values)
 assert switches(a,base)==switches(b,cand),'Switch table address, size or bytes changed'
 rename=sorted({n for image in (a,b) for n,k in image.symbols if re.fullmatch(r'CSWTCH\.\d+',n)})
 check=subprocess.run(layout_command(base,cand,rename,game,object_waivers),
  capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=180)
 assert check.returncode==0,check.stdout[-5000:]+check.stderr
 before,after=ArmMetadata(ElfBytes(base)),ArmMetadata(ElfBytes(cand))
 def funcs(meta):return {n:(x,s) for n,x,s,i,_,_ in meta.symbols if s and i&15==2}
 old,new=funcs(before),funcs(after)
 changed=[];ranges=[]
 for n in sorted(COLD&old.keys()&new.keys()):
  x,s=old[n];assert new[n]==(x,s),(n,'slot moved')
  p,q=before.memory.read(x,s),after.memory.read(x,s)
  if p!=q:
   ranges.append((x,x+s,n));changed.append(dict(name=n,address=x,size_B=s,
    base_sha256=hashlib.sha256(p).hexdigest(),candidate_sha256=hashlib.sha256(q).hexdigest()))
 tails=[];packed=[]
 fills={'lsDrawDog':['Loadgame_packFallback'],
        'lsDrawText':['Loadgame_layout','Loadgame_framebuffer'],
        'lsBegin':['Loadgame_consoleBack'],
        'psSaveShot':['Loadgame_prepare','Loadgame_format','Loadgame_present','Loadgame_saveShot','Loadgame_swap']} if game=='undertale' else {}
 marker={n:x for n,x,s,info,_,index in after.symbols}
 for n,x,s,info,_,index in after.symbols:
  if not n.startswith('__loadgame_body_end_'):continue
  name=n.removeprefix('__loadgame_body_end_');assert name in new,name
  lo,size=new[name]
  if name in old:
   assert old[name]==(lo,size),name
  else:
   # These player helpers were added after the frozen fa0612c9d baseline.
   # Their reviewed extents are still contractual; the nearer player proof
   # additionally checks their original PCs and every other allocated byte.
   assert not player_baseline and name in ('Loadgame_carryCopy','Loadgame_restoreMenu'),name
   assert lo>=a.plain['__late_text_end'] and b.section_at(lo,size).name=='.late.text',name
  end=x+1;assert lo<end<=lo+size,(name,'invalid tail')
  if name in ('Loadgame_carryCopy','Loadgame_restoreMenu'):
   expected=112 if name=='Loadgame_carryCopy' else (36 if model=='o3ds' else 44)
   guarded_target='Loadgame_guardedCarry' if name=='Loadgame_carryCopy' else 'Loadgame_guardedRestore'
   assert size==expected and end==lo+4,(name,'reviewed entry slot changed')
   word=struct.unpack('<I',after.memory.read(lo,4))[0]
   assert word&0xff000000==0xea000000,(name,'entry must be an unconditional tail branch')
   delta=word&0xffffff;delta-=0x1000000 if delta&0x800000 else 0
   assert lo+8+(delta<<2)==new[guarded_target][0],(name,'wrong guarded target')
  if name in fills:
   body_end=end;end=marker['__loadgame_slot_end_'+name]+1
   cursor=body_end
   for helper in fills[name]:
    hx,hs=new[helper]
    assert cursor<=hx<hx+hs<=end<=lo+size,(name,helper,'packed helper outside retained slot')
    assert after.memory.read(cursor,hx-cursor)==bytes(hx-cursor),(name,helper,'nonzero alignment gap')
    packed.append(dict(slot=name,helper=helper,address=hx,size_B=hs))
    cursor=hx+hs
   assert cursor==end,(name,'unexplained packed bytes')
   pcs=[pc for pc in range(lo,body_end,4) if after.kind(pc)=='$a']
   assert pcs and no_fallthrough(struct.unpack('<I',after.memory.read(pcs[-1],4))[0]),(name,'fallthrough into packed helper')
  assert after.memory.read(end,lo+size-end)==bytes(lo+size-end),(name,'nonzero tail')
  if end<lo+size:
   pcs=[pc for pc in range(lo,end,4) if after.kind(pc)=='$a']
   assert pcs and no_fallthrough(struct.unpack('<I',after.memory.read(pcs[-1],4))[0]),(name,'fallthrough')
   tails.append((end,lo+size,name))
 for index,section in enumerate(after.sections):
  if not section[2]&4:continue
  maps=after.maps.get(index,[])
  for i,(start,kind) in enumerate(maps):
   if kind!='$a':continue
   end=maps[i+1][0] if i+1<len(maps) else section[3]+section[5]
   raw=after.memory.read(start,end-start)
   for j in range(0,len(raw)-3,4):
    word=struct.unpack_from('<I',raw,j)[0]
    if word>>25&7==5:
     delta=word&0xffffff;delta-=0x1000000 if delta&0x800000 else 0
     dest=start+j+8+(delta<<2)
     assert not any(lo<=dest<hi for lo,hi,n in tails),('Branch into retained tail',hex(start+j),hex(dest))
 bid=next((x,x+s) for n,x,s,info,_,_ in after.symbols if n=='ctrportBuildId')
 redirects=[];counts={};words=0
 section_by_name={n:s for n,s in zip(after.names,after.sections)}
 def branch(word,pc):
  if word>>25&7!=5:return None
  offset=word&0xffffff;offset-=0x1000000 if offset&0x800000 else 0
  return pc+8+(offset<<2)
 for name,section in zip(before.names,before.sections):
  if not section[2]&2 or section[1]==8:continue
  other=section_by_name[name];lo,hi=section[3],section[3]+section[5]
  # Original live bytes plus newly consumed reserve are bounded by the same
  # reserved block. Baseline reserve bytes must already have been all zero.
  if name in ('.late.text.reserve','.late.rodata.reserve','.late.data.reserve'):
   assert before.memory.read(lo,hi-lo)==bytes(hi-lo),name
   assert after.memory.read(other[3],other[5])==bytes(other[5]),name
   continue
  assert other[3]==lo
  if name in ('.late.text','.late.rodata','.late.data'):
   kind=name.removeprefix('.late.');hi=a.plain['__late_'+kind+'_end']
   assert b.plain['__late_'+kind+'_end']>=hi
  else:assert other[5]==section[5],(name,'allocated size changed')
  assert section[1:3]==other[1:3],(name,'section type/flags changed')
  pa=before.memory.raw[section[4]:section[4]+hi-lo]
  pb=after.memory.raw[other[4]:other[4]+hi-lo]
  for i in range(0,len(pa),4):
   wa,wb=pa[i:i+4],pb[i:i+4]
   if wa==wb:continue
   pc=lo+i
   if bid[0]<=pc and pc+len(wa)<=bid[1]:continue
   if any(x<=pc and pc+len(wa)<=y for x,y,n in ranges):continue
   assert len(wa)==len(wb)==4,(name,hex(pc),'partial word')
   va,vb=struct.unpack('<I',wa)[0],struct.unpack('<I',wb)[0]
   if va==a.plain['__end__'] and vb==b.plain['__end__'] and after.kind(pc)!='$a':continue
   ta,tb=branch(va,pc),branch(vb,pc)
   found=None
   if ta is not None and tb is not None and va&0xff000000==vb&0xff000000:
    for caller,targets in REDIRECTS.items():
     if caller not in old:continue
     x,s=old[caller]
     if not x<=pc<x+s:continue
     for source,dest in targets.items():
      if source in old and dest in new and (ta,tb)==(old[source][0],new[dest][0]):
       found=(caller,source,dest);break
     if found:break
   assert found,(name,hex(pc),hex(va),hex(vb),'unexplained byte outside named cold slots')
   redirects.append(dict(caller=found[0],old=found[1],new=found[2],address=pc))
   counts[found]=counts.get(found,0)+1;words+=1
 assert sum(v for k,v in counts.items() if k[0]=='main')==expected_main_redirects(player_baseline,composed_baseline),counts
 doors=[]
 for name in ('CtrBench_handleRoomChange','Runner_handlePendingRoomChange','__wrap_Runner_handlePendingRoomChange'):
  if name not in old:continue
  x,size=old[name];assert new[name]==(x,size)
  assert before.memory.read(x,size)==after.memory.read(x,size),(name,'door path changed')
  doors.append(dict(name=name,address=x,size_B=size,sha256=hashlib.sha256(before.memory.read(x,size)).hexdigest()))
 assert doors and 'Loadgame_roomChange' not in new
 assert sum(v for k,v in counts.items() if k[0]=='CtrGsfix_yield')==0,counts
 report=dict(base_sha256=hashlib.sha256(base.read_bytes()).hexdigest(),candidate_sha256=hashlib.sha256(cand.read_bytes()).hexdigest(),
  exact_full_layout_failures=0,retained_cold_slots=changed,zero_tails=[dict(start=x,end=y,name=n) for x,y,n in tails],
  packed_cold_helpers=packed,
  branch_redirects=redirects,byte_equal_door_functions=doors,outside_bytes='Exact except fixed build ID, decoded listed call redirects, and __end__',
  steady_yield_entry_unchanged=True,new_text_B=b.plain['__late_text_end']-a.plain['__late_text_end'])
 (out/('scope-'+target+'.json')).write_text(json.dumps(report,indent=2)+'\n')
 print('EXACT SLOT AND BYTE SCOPE PASS',target,'cold bodies',len(changed),'redirects',words,flush=True)

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('base',type=Path);parser.add_argument('candidate',type=Path)
 parser.add_argument('--game',choices=('undertale','deltarune'),required=True)
 parser.add_argument('--model',choices=('o3ds','n3ds'),required=True)
 parser.add_argument('--player-baseline',action='store_true',help='Compare against reviewed player tip 31418d481, whose call redirects already exist')
 parser.add_argument('--composed-baseline',action='store_true',
                     help="Compare against a zq stage: main's redirects already exist, the carry and restore helpers are new here")
 parser.add_argument('--out',type=Path,required=True)
 parser.add_argument('--object-waivers',type=Path,help='Manifest pinned to this exact ELF pair, forwarded to check_layout')
 args=parser.parse_args();args.out.mkdir(parents=True,exist_ok=True)
 if args.player_baseline and args.composed_baseline:parser.error('choose one baseline')
 prove(args.base,args.candidate,args.out,args.game,args.model,args.player_baseline,args.object_waivers,args.composed_baseline)

if __name__=='__main__':main()
