"""Prove compiler-local table renames, then run the unchanged full layout gate.

The layout rules permit a numeric suffix rename only when the
symbol's address, size and bytes are identical. No movement or byte change is
allowed here. All other symbols and sections remain subject to check_layout.py.
"""
import argparse
from collections import Counter
import hashlib
from pathlib import Path
import re
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_layout


def read_virtual(path):
    data = path.read_bytes()
    assert data[:7] == b'\x7fELF\x01\x01\x01', 'expected little-endian ELF32'
    offset = struct.unpack_from('<I', data, 28)[0]
    stride, count = struct.unpack_from('<HH', data, 42)
    segments = [struct.unpack_from('<8I', data, offset + i * stride) for i in range(count)]

    def read(addr, size):
        for kind, pos, start, _, length, *_ in segments:
            if kind == 1 and start <= addr and addr + size <= start + length:
                return data[pos + addr - start:pos + addr - start + size]
        raise AssertionError(f'unmapped bytes: 0x{addr:08x} +{size} B')
    return read


def verified_renames(base, candidate):
    nm, readelf = check_layout.tool('nm', None), check_layout.tool('readelf', None)
    old, new = check_layout.load(base, nm, readelf), check_layout.load(candidate, nm, readelf)
    before, after = read_virtual(base), read_virtual(candidate)
    return prove_switches(old, new, before, after)


def prove_switches(old, new, before, after):
    # Numeric suffixes can collide across translation units. Prove every definition in the whole group,
    # including definitions whose shared name survives while one other definition is renamed.
    def switches(layout):
        return {key: slots for key, slots in layout.symbols.items()
                if key[1] == 'r' and re.fullmatch(r'CSWTCH\.\d+', key[0])}
    left, right = switches(old), switches(new)
    locations = Counter(slot for slots in left.values() for slot in slots)
    if locations != Counter(slot for slots in right.values() for slot in slots):
        return []
    for addr, size in locations:
        section = old.section_at(addr, size)
        if (before(addr, size) != after(addr, size) or section is None or section.region != 'rodata'
                or section != new.section_at(addr, size)):
            return []
    allowed = []
    for key in sorted(left.keys() | right.keys()):
        if left.get(key) == right.get(key):
            continue
        allowed.append(key[0])
        for addr, size in left.get(key, []):
            targets = [name for (name, _), slots in right.items() if (addr, size) in slots]
            print(f'PROVEN numeric rename {key[0]}->{"/".join(targets)}: same 0x{addr:08x}, {size} B, '
                  f'SHA-256 {hashlib.sha256(before(addr, size)).hexdigest()}', flush=True)
    return allowed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('candidate', type=Path)
    args = parser.parse_args()
    allowed = verified_renames(args.base, args.candidate)
    command = [sys.executable, '-I', str(Path(__file__).with_name('check_layout.py')),
               str(args.base), str(args.candidate), '--full']
    for name in allowed:
        command.extend(('--allow', name))
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=90).returncode


if __name__ == '__main__':
    sys.exit(main())
