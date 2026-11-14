"""Prove all changed CSWTCH suffixes, including overlapping rename chains.

Test-only verifier for RULES.md's compiler-local numeric-rename exception.
The normal full layout gate still checks every other symbol and section.
"""
import argparse
import hashlib
from pathlib import Path
import re
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_layout
from check_bench_prewindow_layout import read_virtual


def prove(old, new, before, after):
    def tables(layout):
        return {key: slots for key, slots in layout.symbols.items()
                if key[1] == 'r' and re.fullmatch(r'CSWTCH\.\d+', key[0])}
    a, b = tables(old), tables(new)
    changed_old = {key: slots for key, slots in a.items() if b.get(key) != slots}
    changed_new = {key: slots for key, slots in b.items() if a.get(key) != slots}
    proof = []
    used = set()
    for key, slots in sorted(changed_old.items()):
        matches = [other for other, target in changed_new.items() if target == slots and other != key]
        assert len(matches) == 1, ('No unique same-slot numeric rename', key, matches)
        target = matches[0]
        assert target not in used, ('Not a bijection', target)
        used.add(target)
        for addr, size in slots:
            assert before(addr, size) == after(addr, size), ('Changed table bytes', key, target)
            assert old.section_at(addr, size) == new.section_at(addr, size), ('Changed section', key)
            assert old.section_at(addr, size).region == 'rodata', key
        proof.append((key[0], target[0], slots))
    assert used == changed_new.keys(), ('Unproven new tables', changed_new.keys() - used)
    return proof


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    nm, readelf = check_layout.tool('nm', None), check_layout.tool('readelf', None)
    old = check_layout.load(args.base, nm, readelf)
    new = check_layout.load(args.candidate, nm, readelf)
    before, after = read_virtual(args.base), read_virtual(args.candidate)
    calls = {'saveResults': ('emit', 'benchfidEmitWindow'),
             'CtrBench_beginFrameTimed': ('CtrBench_beginFrame', 'benchfidBeginFrame'),
             'screensLoad': ('CtrDisplay_load', 'benchfidLoad'),
             '__wrap_CtrDisplay_override': ('CtrDisplay_override', 'benchfidOverride'),
             'beginMeasuring': ('benchRoomsOpen', 'benchfidRoomsOpen'),
             'benchRoomsTick': ('benchRoomsCollect', 'benchfidRoomsCollect'),
             'benchRoomsRelease': ('benchRoomsReport', 'benchfidRoomsReport')}
    def entries(layout, name):
        return {addr for (symbol, kind), slots in layout.symbols.items()
                if symbol == name and kind in ('t','T') for addr, size in slots}
    unchanged = 0
    for (name, kind), slots in old.symbols.items():
        if kind not in ('t','T') or new.symbols.get((name,kind)) != slots:
            continue  # The full gate below rejects moved/missing functions.
        for addr, size in slots:
            a, b = before(addr,size), after(addr,size)
            if a == b:
                unchanged += 1
                continue
            first = next(i for i in range(size) if a[i] != b[i]) & ~3
            assert name in calls and size % 4 == 0, ('Unrelated text changed', name,
                f'address=0x{addr+first:x}', f'offset=0x{first:x}',
                f'old={a[first:first+4].hex()}', f'new={b[first:first+4].hex()}')
            for offset in range(0,size,4):
                x,y = struct.unpack_from('<I',a,offset)[0],struct.unpack_from('<I',b,offset)[0]
                if x == y:
                    continue
                assert x & 0xff000000 == y & 0xff000000 and x & 0x0f000000 == 0x0b000000, ('Not a BL-only change',name,
                    f'address=0x{addr+offset:x}', f'offset=0x{offset:x}', f'old=0x{x:08x}', f'new=0x{y:08x}')
                def target(word):
                    immediate = word & 0xffffff
                    if immediate & 0x800000:
                        immediate -= 0x1000000
                    return addr+offset+8+immediate*4
                original, replacement = calls[name]
                assert target(x) in entries(old,original) and target(y) in entries(new,replacement), ('Unexpected call target',name,offset)
                print(f'PROVEN call target only {name}+0x{offset:x}: {original}->{replacement}',flush=True)
    print(f'Existing text byte-identical functions: {unchanged}; only {len(calls)} named callers may change BL targets',flush=True)
    proof = prove(old, new, before, after)
    allowed = set()
    for original, target, slots in proof:
        print(f'PROVEN numeric rename {original}->{target}: same address/size/section/bytes {slots}', flush=True)
        for addr, size in slots:
            print(f'  SHA-256 {hashlib.sha256(read_virtual(args.base)(addr, size)).hexdigest()}', flush=True)
        allowed.update((original, target))
    command = [sys.executable, '-I', str(Path(__file__).with_name('check_layout.py')),
               str(args.base), str(args.candidate), '--full']
    for name in sorted(allowed):
        command.extend(('--allow', name))
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=90).returncode


if __name__ == '__main__':
    raise SystemExit(main())
