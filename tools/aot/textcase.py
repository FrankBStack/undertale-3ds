"""Write romfs/textcase.bin: the case table of UNDERTALE's dialogue script's switch, for its jump straight to the case.

platform/3ds/source/z_textcase.c reads it (UNDERTALE Old 3DS only). The game's dialogue script (the one every text
box runs to fill in its lines, 146 KB of bytecode in UNDERTALE 1.08) is one switch on its argument0: it pushes the
argument, then compares it with each case's constant in turn (Dup.v 0, PushI.e K, Cmp.i.v EQ, Bt case), about 480 of
them, and ends the chain with B (no case: past the switch). The interpreter walks that chain from the top on every
call, about 2,000 instructions before it reaches a late case. This file lists the cases sorted by constant, so the
runtime finds the case with a binary search and starts the interpreter there with the switch value on the stack,
exactly where the chain's Bt would have sent it (codeclose's results, "CAUSE", lever 1).

The script is found by the first 16 hex digits of the SHA-256 of its code entry's name (as offkill.py names objects),
so this file names no game identifiers, then checked to have exactly that shape: PushBltn.v self.argument0 (8 bytes),
then at least MIN_CASES cases of those four instructions with a 16-bit constant and a forward branch, then the chain's
B. A constant that appears twice keeps its first case (the chain's Bt takes the first match).

Output (little-endian): a 20-byte header, then one 4-byte entry per distinct constant, sorted by constant.
    u32 code index        the code entry's index in the data.win's CODE chunk
    u32 length            the code entry's bytecode length
    u32 span              the bytes from the entry's offset through the chain's B (the runtime checks their digest)
    u32 digest            FNV-1a 32 of those bytes with the variable and function operands resolved to indices, as
                          the VM patches them at load (gmlaot.py's patch_operands)
    u32 count             the number of entries
    entry: i16 constant, u16 case address / 4 (relative to the code entry's bytecode, as the interpreter's ip)
The runtime starts the switch at offset + 8 (the chain) and treats offset + span - 4 (the chain's B) as "no case".
Any other shape, no data or no such entry: no file, and the runtime walks the chain as before.

       py -3 -I tools/aot/textcase.py --game <undertale|deltarune> --romfs <build>/romfs [--data <game folder>]
       py -3 -I tools/aot/textcase.py --hash NAME
       py -3 -I tools/aot/textcase.py --report <data.win>
"""
import argparse
import hashlib
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

HASH_DIGITS = 16
# The dialogue script's code entry name (UNDERTALE Steam and GOG 1.08).
SCRIPT_KEY = '7bdd3a9a920c289e'
MIN_CASES = 16
MAX_CASES = 512  # z_textcase.c's TC_MAX (the runtime reads the table whole into bss)

OP_CMP, OP_DUP, OP_PUSHI, OP_B, OP_BT = 0x15, 0x86, 0x84, 0xB6, 0xB7
DUP_V0 = 0x86050000      # Dup.v 0
PUSHI_E = 0x840F0000     # PushI.e (16-bit constant in the low half)
CMP_IV_EQ = 0x15520300   # Cmp.i.v EQ
# The front runs the switch value's push itself, as the interpreter runs PushBltn.v self.argument0 (z_textcase.c):
# that instruction word (self, variable type) with a normal (not array) reference to argument0.
FIRST_WORD = 0xC305FFFF
VARTYPE_NORMAL = 0xA0
SWITCH_VAR = 'argument0'


def name_hash(name):
    return hashlib.sha256(name.encode('utf-8')).hexdigest()[:HASH_DIGITS]


def fnv1a32(data):
    h = 0x811C9DC5
    for b in data:
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def branch_target(addr, word):
    off = word & 0x7FFFFF
    if off & 0x400000:
        off -= 0x800000
    return addr + off * 4


def chain(blob, start):
    """(cases [(constant, target)], address of the chain's B) for the switch chain at start in blob, or a reason
    string. Only the shape above; every target must lie past the chain and inside the code."""
    def word(a):
        return struct.unpack_from('<I', blob, a)[0]
    cases = []
    a = start
    while a + 16 <= len(blob) and word(a) == DUP_V0 and word(a + 4) & 0xFFFF0000 == PUSHI_E \
            and word(a + 8) == CMP_IV_EQ and word(a + 12) >> 24 == OP_BT:
        k = word(a + 4) & 0xFFFF
        cases.append((k - 0x10000 if k & 0x8000 else k, branch_target(a + 12, word(a + 12))))
        a += 16
    if len(cases) < MIN_CASES:
        return 'chain of %d cases' % len(cases)
    if len(cases) > MAX_CASES:
        return 'chain of %d cases (more than %d)' % (len(cases), MAX_CASES)
    if a + 4 > len(blob) or word(a) >> 24 != OP_B:
        return 'chain does not end in B'
    for _, t in cases:
        if not a + 4 <= t < len(blob) or t % 4:
            return 'case address %#x outside the code after the chain' % t
    return cases, a


def table(dw, entry):
    """romfs/textcase.bin's bytes for the code entry (gmlaot.DataWin, operands patched), or a reason string."""
    blob = bytes(dw.data[entry['abs']:entry['abs'] + entry['length']])
    off = entry['offset']
    if off + 8 > len(blob):
        return 'entry too short'
    first, ref = struct.unpack_from('<2I', blob, off)
    var = ref & 0x07FFFFFF
    if first != FIRST_WORD or ref >> 24 & 0xF8 != VARTYPE_NORMAL or var >= len(dw.vars)             or dw.vars[var]['name'] != SWITCH_VAR:
        return 'entry does not start with PushBltn.v self.%s' % SWITCH_VAR
    got = chain(blob, off + 8)
    if isinstance(got, str):
        return got
    cases, end = got
    if (end + 4) // 4 > 0xFFFF or max(t for _, t in cases) // 4 > 0xFFFF:
        return 'code too long for 16-bit case addresses'
    first_case = {}
    for k, t in cases:
        first_case.setdefault(k, t)
    span = end + 4 - off
    head = struct.pack('<5I', entry['index'], entry['length'], span, fnv1a32(blob[off:end + 4]), len(first_case))
    return head + b''.join(struct.pack('<hH', k, first_case[k] // 4) for k in sorted(first_case))


def find(dw):
    """The code entry whose name hashes to SCRIPT_KEY (exactly one), or a reason string."""
    found = [e for e in dw.code if e is not None and e['name'] is not None and name_hash(e['name']) == SCRIPT_KEY]
    if len(found) != 1:
        return 'script not found' if not found else 'script name not unique'
    return found[0]


def from_data_win(path):
    """(bytes or b'', report line) for one data.win."""
    import gmlaot
    dw = gmlaot.DataWin(path)
    if dw.wad != 16:
        return b'', 'textcase: bytecode version %d; no case table' % dw.wad
    entry = find(dw)
    if isinstance(entry, str):
        return b'', 'textcase: %s; no case table' % entry
    dw.patch_operands()
    blob = table(dw, entry)
    if isinstance(blob, str):
        return b'', 'textcase: %s; no case table' % blob
    count = struct.unpack_from('<I', blob, 16)[0]
    return blob, 'textcase: code %d, %d cases, %d B' % (entry['index'], count, len(blob))


def build(game, data_dir):
    """(bytes, report lines) for the game; b'' means no file."""
    if game != 'undertale':
        return b'', []
    import corpus
    import prepare
    found = prepare.find_data(game, data_dir)
    parts = [p for _, p, _ in corpus.parts(game, found)] if found else []
    if not parts:
        return b'', ['textcase: no UNDERTALE data; no case table in this build']
    blob, line = from_data_win(parts[0])
    return blob, [line]


def write(romfs, blob):
    """Write (or remove, for none) romfs/textcase.bin; True when the file changed."""
    path = os.path.join(romfs, 'textcase.bin')
    try:
        with open(path, 'rb') as f:
            old = f.read()
    except OSError:
        old = None
    if not blob:
        if old is not None:
            os.remove(path)
        return old is not None
    if old == blob:
        return False
    os.makedirs(romfs, exist_ok=True)
    with open(path + '.tmp', 'wb') as f:
        f.write(blob)
    os.replace(path + '.tmp', path)
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', choices=('undertale', 'deltarune'))
    ap.add_argument('--romfs')
    ap.add_argument('--data')
    ap.add_argument('--hash', metavar='NAME', help="print the key for a code entry name")
    ap.add_argument('--report', metavar='DATA_WIN', help="print what the table for a data.win would be")
    a = ap.parse_args(argv)
    if a.hash:
        print(name_hash(a.hash))
        return 0
    if a.report:
        print(from_data_win(a.report)[1])
        return 0
    if not a.game or not a.romfs:
        ap.error('--game and --romfs are required')
    blob, lines = build(a.game, a.data)
    for line in lines:
        print(line)
    write(a.romfs, blob)
    return 0


if __name__ == '__main__':
    sys.exit(main())
