"""Prove the native collision traversal correction against an explicit base.

The collision dispatcher may shrink inside its retained slot. Its next symbol
does not move; its zero tail has no direct control-flow target or fallthrough.
Three named traversal helpers are appended after all base late text. Every
other existing text body is byte-identical. Numeric local renames require
identical storage, bytes and input-object ownership. The unchanged full layout
gate checks every other symbol and data section. The selected comparison base may omit the separate R409
motion adapter; its existing motion body must stay byte-identical like every
other body outside the named collision dispatcher. This is a layout proof, not a behavioural collision oracle.
"""
import argparse
from collections import Counter
import hashlib
import json
import re
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_layout
from check_benchfid_layout import prove
from check_bench_prewindow_layout import read_virtual

COLLISION = 'dispatchCollisionEvents'
ADDED = {'Utlife_nextCollision', 'Utlife_nextCompatCollision',
         'Utlife_collisionTargetsNeedSnapshot'}


def prove_retained_tail(instructions, start, tail, limit):
    """Mapping-aware disassembly excludes literals; alignment NOPs must be dead.

    Reject a direct target anywhere after the last terminating instruction,
    including its alignment NOP, numeric pool and the retained zero tail.
    This makes no claim about arbitrary computed indirect branch targets.
    """
    body = [(a, m, o) for a, m, o in instructions if start <= a < tail]
    returns = [a for a, m, o in body if (m.startswith(('pop', 'ldm')) and re.search(r'\bpc\b', o)) or
               (m.startswith('bx') and o.strip() == 'lr') or (m == 'mov' and o.strip() == 'pc, lr')]
    assert returns, 'No collision return before tail'
    live = [row for row in body if row[1] != 'nop']
    assert live, 'Empty collision body'
    terminal = live[-1]
    padding = [row for row in body if row[0] > terminal[0]]
    assert len(padding) <= 1 and all(m == 'nop' and a == terminal[0]+4 for a, m, _ in padding), ('Unexpected trailing instructions', padding)
    unconditional_return = ((terminal[1] in ('pop', 'ldm', 'ldmia', 'ldmfd') and re.search(r'\bpc\b', terminal[2])) or
                            (terminal[1] == 'mov' and terminal[2].strip() == 'pc, lr'))
    assert unconditional_return or terminal[1] in ('b', 'bx') or (terminal[1] == 'bl' and
           re.search(r'<(?:__wrap_abort|abort|exit|_exit)>', terminal[2])), ('Fallthrough into tail', terminal)
    dead_start = terminal[0]+4
    branch = re.compile(r'b(?:l|lx|x)?(?:eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?$')
    for address, mnemonic, operands in instructions:
        target = re.match(r'([0-9a-f]+)\s+<', operands)
        assert not (branch.fullmatch(mnemonic) and target and dead_start <= int(target[1], 16) < limit), ('Branch into dead suffix', hex(address))
    return dict(terminal_address=hex(terminal[0]), dead_suffix_start=hex(dead_start),
                alignment_nop_bytes=4*len(padding), no_direct_branch_into_dead_suffix=True)


def prove_collision(base, cand, before, after, candidate_path):
    def function(info, name):
        rows = [row for (label, kind), slots in info.symbols.items()
                if label == name and kind in ('t', 'T') for row in slots]
        assert len(rows) == 1, (name, rows)
        return rows[0]
    start, extent = function(base, COLLISION)
    new_start, size = function(cand, COLLISION)
    assert new_start == start and 0 < size < extent == 3112
    tail, limit = start+size, start+extent
    following = min((address, name) for (name, kind), slots in base.symbols.items()
                    if kind in ('t', 'T') for address, _ in slots if address >= limit)
    assert following[0] == limit and function(cand, following[1]) == function(base, following[1])
    assert after(tail, limit-tail) == bytes(limit-tail), 'Nonzero retained collision tail'
    command = [check_layout.tool('objdump', None), '-d', str(candidate_path)]
    listing = subprocess.run(command, stdin=subprocess.DEVNULL, capture_output=True,
                             text=True, check=True, timeout=60).stdout
    instructions = []
    for line in listing.splitlines():
        m = re.match(r'^\s*([0-9a-f]+):\s+[0-9a-f]+\s+([a-z][a-z0-9.]*)\s*(.*)$', line)
        if m:
            instructions.append((int(m[1], 16), m[2], m[3]))
    suffix = prove_retained_tail(instructions, start, tail, limit)
    added = {name for name,kind in cand.symbols if kind in ('t','T') and (name,kind) not in base.symbols}
    assert added == ADDED, ('Unexpected new text',added)
    late_start, late_end = base.plain['__late_text_end'], cand.plain['__late_text_end']
    helpers = {}
    for name in sorted(ADDED):
        address, count = function(cand,name)
        assert late_start <= address < address+count <= late_end
        assert cand.section_at(address,count).name == '.late.text'
        helpers[name] = dict(address=hex(address),bytes=count)
    return dict(start=hex(start),old_slot_bytes=extent,returning_body_and_pool_bytes=size,
                zero_tail_bytes=extent-size,no_direct_branch_into_tail=True,
                no_fallthrough=True,late_text_delta=late_end-late_start,helpers=helpers, suffix=suffix)



def branch_target(word, address):
    immediate = word & 0xffffff
    if immediate & 0x800000:
        immediate -= 0x1000000
    return address + 8 + immediate * 4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('base', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--expected-base-sha256', required=True, help='Bind the explicitly selected composition base')
    parser.add_argument('--allow-call-rewrite', action='append', default=[], metavar='FUNCTION:OLD:NEW',
                        help='One reviewed ARM BL rewrite; no implicit restore exception')
    args = parser.parse_args()
    base_hash = hashlib.sha256(args.base.read_bytes()).hexdigest()
    if args.expected_base_sha256:
        assert base_hash == args.expected_base_sha256, 'Unexpected composition base'
    rewrites = [tuple(rule.split(':')) for rule in args.allow_call_rewrite]
    assert all(len(rule) == 3 for rule in rewrites) and len(set(rewrites)) == len(rewrites), 'Invalid call rewrite rule'
    nm, readelf = check_layout.tool('nm', None), check_layout.tool('readelf', None)
    base, cand = [check_layout.load(path, nm, readelf) for path in (args.base, args.candidate)]
    before, after = read_virtual(args.base), read_virtual(args.candidate)
    waivers, allowed = [], set()
    for old, new, slots in prove(base, cand, before, after):
        objects = [obj for obj in base.objects if obj.name == old]
        assert sorted((obj.address, obj.size) for obj in objects) == sorted(slots)
        for obj in objects:
            matches = [other for other in cand.objects if other.name == new and
                       (other.address, other.size) == (obj.address, obj.size)]
            assert len(matches) == 1, ('Ambiguous numeric rename', obj)
            other = matches[0]
            assert (obj.owner, obj.section, obj.occurrence, obj.output, obj.file_origin, obj.local, obj.digest) == (
                    other.owner, other.section, other.occurrence, other.output, other.file_origin, other.local, other.digest)
            assert obj.file_origin and obj.local and obj.digest
            waivers.append(dict(object=obj.owner, section=obj.section, occurrence=obj.occurrence,
                                symbol=old, renamed_to=new))
            print(f'PROVEN numeric rename {old}->{new}: same object, slot and bytes {obj.digest}', flush=True)
        allowed.update((old, new))

    def entry(layout, name):
        hits = [address for (symbol, kind), slots in layout.symbols.items()
                if symbol == name and kind in ('t', 'T') for address, _ in slots]
        assert len(hits) == 1, (name, hits)
        return hits[0]

    collision = prove_collision(base, cand, before, after, args.candidate)
    allowed.add(COLLISION)
    print('PROVEN retained collision slot '+json.dumps(collision), flush=True)
    changed_calls, identical = Counter(), 0
    for (name, kind), slots in base.symbols.items():
        if kind not in ('t', 'T'):
            continue
        if name == COLLISION:
            continue
        assert cand.symbols.get((name, kind)) == slots, ('Existing text layout changed', name)
        for address, size in slots:
            a, b = before(address, size), after(address, size)
            if a == b:
                identical += 1
                continue
            rules = [rule for rule in rewrites if rule[0] == name]
            assert rules and size % 4 == 0, ('Unrelated text bytes changed', name)
            for offset in range(0, size, 4):
                x, y = struct.unpack_from('<I', a, offset)[0], struct.unpack_from('<I', b, offset)[0]
                if x == y:
                    continue
                assert x & 0xff000000 == y & 0xff000000 == 0xeb000000, ('Not an ARM BL', offset)
                matches = [rule for rule in rules if branch_target(x, address+offset) == entry(base, rule[1])
                           and branch_target(y, address+offset) == entry(cand, rule[2])]
                assert len(matches) == 1, ('Unreviewed call rewrite', name, offset)
                changed_calls[matches[0]] += 1
    assert changed_calls == Counter(rewrites), ('Unused/duplicate call allowances', changed_calls)
    print(f'PROVEN existing text: {identical} identical bodies; {sum(changed_calls.values())} explicit BL rewrites; retained collision slot', flush=True)
    manifest = dict(base_sha256=base_hash,
                    candidate_sha256=hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
                    base_math_policy='comparison-base motion body unchanged; separate forward patch not allowed here',
                    collision_proof=collision,
                    object_waivers=waivers)
    args.manifest.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    command = [sys.executable, '-I', str(Path(__file__).with_name('check_layout.py')),
               str(args.base), str(args.candidate), '--full', '--object-waivers', str(args.manifest)]
    for name in sorted(allowed):
        command.extend(('--allow', name))
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=120).returncode


if __name__ == '__main__':
    raise SystemExit(main())
