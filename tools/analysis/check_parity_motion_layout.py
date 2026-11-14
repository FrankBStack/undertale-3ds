"""Compare an explicit expected base with the retained forward-motion correction.

No existing text moves or grows. Every body except explicitly named call
rewrites and the forward helper is byte-identical. The helper keeps its 248 B slot,
returns before its numeric pool/padding, and has no branch into that tail.
Data/table rename proof and the unchanged full layout gate remain mandatory.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'buildcache'))
from parity_motion_verify import prove_motion, verify
import check_layout
from check_benchfid_layout import prove
from check_bench_prewindow_layout import read_virtual

MOTION = 'Instance_computeComponentsFromSpeed'


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
    parser.add_argument('--receipt-root', type=Path, required=True)
    parser.add_argument('--expected-base-sha256', help='Bind the explicitly selected composition base')
    parser.add_argument('--allow-call-rewrite', action='append', default=[], metavar='FUNCTION:OLD:NEW',
                        help='One reviewed ARM BL rewrite; no implicit restore exception')
    args = parser.parse_args()
    base_hash = hashlib.sha256(args.base.read_bytes()).hexdigest()
    if args.expected_base_sha256:
        assert base_hash == args.expected_base_sha256, 'Unexpected composition base'
    receipt_proof = verify(args.candidate, args.receipt_root)
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

    changed_calls, identical, motion = Counter(), 0, []
    for (name, kind), slots in base.symbols.items():
        if kind not in ('t', 'T'):
            continue
        assert cand.symbols.get((name, kind)) == slots, ('Existing text layout changed', name)
        for address, size in slots:
            a, b = before(address, size), after(address, size)
            if name == MOTION:
                motion.append(prove_motion(address, b, lambda name: entry(cand, name)))
                print('PROVEN retained motion body ' + json.dumps(motion[-1]), flush=True)
                continue
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
    assert changed_calls == Counter(rewrites) and len(motion) == 1, ('Unused/duplicate call allowances', changed_calls)
    print(f'PROVEN existing text: {identical} identical bodies; {sum(changed_calls.values())} explicit BL rewrites; retained motion body', flush=True)
    manifest = dict(base_sha256=base_hash,
                    candidate_sha256=hashlib.sha256(args.candidate.read_bytes()).hexdigest(),
                    receipt_proof=receipt_proof,
                    object_waivers=waivers)
    args.manifest.write_text(json.dumps(manifest, indent=2)+'\n', encoding='utf-8')
    command = [sys.executable, '-I', str(Path(__file__).with_name('check_layout.py')),
               str(args.base), str(args.candidate), '--full', '--object-waivers', str(args.manifest)]
    for name in sorted(allowed):
        command.extend(('--allow', name))
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=120).returncode


if __name__ == '__main__':
    raise SystemExit(main())
