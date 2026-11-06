"""Public UT only: route main.o's single stat relocation to the appended file-trigger guard.

The delegate emits its normal object, including every earlier layout adapter. Objcopy changes an undefined
symbol name, preserving all allocated bytes; the final link changes only that call operand. A changed caller
inventory fails closed. No main.c source, string pool or argv branch is rewritten.
"""
from pathlib import Path
import hashlib
import json
import re
import struct
import subprocess
import sys

MARKER = '--p51-compiler'


def inventory(data):
    assert data[:7] == b'\x7fELF\x01\x01\x01', 'expected little-endian ELF32'
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', data)
    assert h[1] == 1 and h[2] == 40, 'expected relocatable ARM object'
    sections = [struct.unpack_from('<10I', data, h[6] + h[11] * i) for i in range(h[12])]
    shstrings = sections[h[13]]
    shnames = data[shstrings[4]:shstrings[4] + shstrings[5]]
    allocated, edges = {}, []
    def name(pool, offset):
        return pool[offset:].split(b'\0', 1)[0].decode()
    for sec in sections:
        secname = name(shnames, sec[0])
        if sec[2] & 2:
            assert secname not in allocated
            allocated[secname] = (sec[1], sec[2], sec[5], sec[8], data[sec[4]:sec[4]+sec[5]] if sec[1] != 8 else b'')
        if sec[1] != 9:  # SHT_REL
            continue
        syms = sections[sec[6]]
        strings = sections[syms[6]]
        pool = data[strings[4]:strings[4]+strings[5]]
        caller = name(shnames, sections[sec[7]][0])
        for off in range(sec[4], sec[4]+sec[5], sec[9]):
            address, info = struct.unpack_from('<II', data, off)
            symbol = struct.unpack_from('<IIIBBH', data, syms[4] + (info >> 8)*syms[9])
            if name(pool, symbol[0]) in ('stat', '__wrap_bootHookStat'):
                edges.append((caller, address, info & 255, name(pool, symbol[0]), symbol[5]))
    return allocated, edges


def run(args):
    return subprocess.run(args, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split+1:]
    selected = ('-c' in command and '-DCTRPORT_PUBLIC_BENCH_FILE' in command and '-DENABLE_WAD16' in command and
                any(a.replace('\\', '/').endswith('/main.c') for a in command))
    status = run(delegate + command)
    if status or not selected:
        return status
    assert '-c' in command and command.count('-o') == 1
    output = Path(command[command.index('-o')+1])
    before = output.read_bytes()
    allocated, edges = inventory(before)
    assert len(edges) == 1 and edges[0][0] == '.text.late.screens' and edges[0][2:] == (28, 'stat', 0), (
        'unqualified screen probe relocation', edges)
    compiler = Path(command[0])
    tool, count = re.subn(r'gcc(\.exe)?$', r'objcopy\1', compiler.name)
    assert count == 1, ('unqualified compiler', compiler)
    status = run([str(compiler.with_name(tool)), '--redefine-sym', 'stat=__wrap_bootHookStat', str(output)])
    if status:
        return status
    after = output.read_bytes()
    final_allocated, final_edges = inventory(after)
    assert final_allocated == allocated, 'allocated object bytes changed'
    assert final_edges == [(*edges[0][:3], '__wrap_bootHookStat', 0)], 'unexpected relocation rewrite'
    receipt = dict(before_sha256=hashlib.sha256(before).hexdigest(), after_sha256=hashlib.sha256(after).hexdigest(),
                   edges=edges, routed_edges=final_edges, allocated_bytes_changed=0)
    output.with_suffix('.p51.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print('P51 public screen probe: '+json.dumps(receipt), flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
