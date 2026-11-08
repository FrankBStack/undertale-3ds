"""Prove only one recorded-fill call operand, appended code/constants and build ID change."""
import argparse
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
import check_layout
from check_knsurf_layout import elf_read, branch

def one(layout,name):
    values={value for (symbol,kind),entries in layout.symbols.items() if symbol==name for value in entries}
    assert len(values)==1,(name,values)
    return next(iter(values))

def pin_helper(layout,data):
    """Decode the complete helper, including the predicate and both callees."""
    address,size=one(layout,'CtrDlgwhite_solidDrawIsNoop')
    assert size==40,('helper size',size)
    words=struct.unpack('<10I',elf_read(data,address,size))
    expected=(0xe92d4010,0xe1a04000,None,0xe3500000,0x08bd8010,
              0xe1a00004,None,0xe16f0f10,0xe1a002a0,0xe8bd8010)
    for index,word in enumerate(expected):
        if word is not None:assert words[index]==word,('helper instruction',index,hex(words[index]))
    for index,name in ((2,'solidDrawIsNoop'),(6,'recordingSurface')):
        assert words[index]>>24==0xeb,('helper direct call',index)
        assert branch(words[index],address+index*4)==one(layout,name)[0],('helper callee',name)
    return address,size

def prove(base_path,candidate_path,base_map=None,candidate_map=None):
    nm,readelf=check_layout.tool('nm',None),check_layout.tool('readelf',None)
    base=check_layout.load(base_path,nm,readelf,base_map)
    cand=check_layout.load(candidate_path,nm,readelf,candidate_map)
    before,after=base_path.read_bytes(),candidate_path.read_bytes()
    helper,size=pin_helper(cand,after)
    assert helper==base.plain['__late_text_end'] and cand.plain['__late_text_end']==helper+size, 'append exactly the pinned helper'
    for kind in ('rodata','data'):
        assert base.plain[f'__late_{kind}_end']==cand.plain[f'__late_{kind}_end'],('unexpected late storage',kind)
    routes={one(base,'solidDrawIsNoop')[0]:one(cand,'CtrDlgwhite_solidDrawIsNoop')[0]}
    counts={address:0 for address in routes}; patches={}
    for key in base.symbols.keys() & cand.symbols.keys():
        assert base.symbols[key]==cand.symbols[key],('moved/resized existing symbol',key)
        if key[1] not in 'tTwW': continue
        for address,size in base.symbols[key]:
            a,b=elf_read(before,address,size),elf_read(after,address,size)
            if a==b: continue
            assert size%4==0,('unaligned body',key)
            for offset in range(0,size,4):
                wa,wb=struct.unpack_from('<I',a,offset)[0],struct.unpack_from('<I',b,offset)[0]
                if wa==wb:continue
                pc=address+offset
                assert wa>>24==wb>>24==0xeb,('not unchanged ARM BL',key,hex(pc),hex(wa),hex(wb))
                old,new=branch(wa,pc),branch(wb,pc)
                assert old in routes and routes[old]==new,('unexpected callee',key,hex(pc),hex(old),hex(new))
                if pc not in patches: counts[old]+=1
                patches[pc]=4
    assert list(counts.values())==[1],counts
    start,size=one(base,'emitQuad')
    assert all(start<=pc<start+size for pc in patches),patches
    for name in ('__bss_start__','__bss_end__','__end__'):
        assert base.plain[name]==cand.plain[name],('BSS delta',name)
    build_id,build_size=one(base,'ctrportBuildId');assert one(cand,'ctrportBuildId')==(build_id,build_size)
    masks=list(patches.items())+[(build_id,build_size)]
    for kind in ('text','rodata','data'):
        lo,hi=base.plain[f'__late_{kind}_end'],cand.plain[f'__late_{kind}_end']
        assert hi>=lo,(kind,'late shrink');masks.append((lo,hi-lo))
    for section in base.sections:
        if section.kind=='NOBITS' or not section.size:continue
        a,b=[bytearray(elf_read(data,section.addr,section.size)) for data in (before,after)]
        for address,size in masks:
            lo,hi=max(address,section.addr),min(address+size,section.end)
            if lo<hi:a[lo-section.addr:hi-section.addr]=b[lo-section.addr:hi-section.addr]=bytes(hi-lo)
        assert a==b,('unrelated allocated bytes',section.name)
    print('PASS: one decoded emitQuad call; all existing symbols/allocated bytes retained; 0 B BSS; append-only code/constants')
    print('Late text delta:',cand.plain['__late_text_end']-base.plain['__late_text_end'],'B')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('base',type=Path);p.add_argument('candidate',type=Path)
    p.add_argument('--base-map',type=Path);p.add_argument('--map',dest='candidate_map',type=Path)
    args=p.parse_args();prove(args.base,args.candidate,args.base_map,args.candidate_map)
    maps=[]
    if args.base_map:maps+=['--base-map',str(args.base_map)]
    if args.candidate_map:maps+=['--map',str(args.candidate_map)]
    raise SystemExit(subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('check_layout.py')),
        str(args.base),str(args.candidate),'--full',*maps],stdin=subprocess.DEVNULL,timeout=120).returncode)
