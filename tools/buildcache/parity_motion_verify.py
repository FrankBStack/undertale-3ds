"""Mandatory UT packaging check: current compiler receipt and linked motion bytes.

Uses ELF32 sections/symbols directly, so exported player builds need no frozen
lab image or Python dependencies. The separate layout gate compares an explicit
expected base; this check proves the linked body came from the qualified adapter.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import struct

SYMBOL = 'Instance_computeComponentsFromSpeed'
ROOT = Path(__file__).resolve().parents[2]
BODY = ROOT / 'engine/src/parity_motion_body.inc'
ADAPTER = Path(__file__).with_name('parity_motion_compile.py')
# Measured on both release targets; only external BL displacements are normalized.
QUALIFIED_BODY = 'c8c61686c1d32552b5d05dd94339480adc694df18667d6e44b9cf98a603767c6'


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Elf:
    def __init__(self, path):
        self.data = path.read_bytes()
        assert self.data[:7] == b'\x7fELF\x01\x01\x01', 'Expected little-endian ELF32'
        self.kind = struct.unpack_from('<H', self.data, 16)[0]
        assert struct.unpack_from('<H', self.data, 18)[0] == 40, 'Expected ARM ELF'
        offset = struct.unpack_from('<I', self.data, 32)[0]
        stride, count = struct.unpack_from('<HH', self.data, 46)
        self.sections = [struct.unpack_from('<10I', self.data, offset+i*stride) for i in range(count)]
        self.symbols = {}
        for section in self.sections:
            if section[1] != 2:  # SHT_SYMTAB
                continue
            strings = self.section_bytes(self.sections[section[6]])
            for pos in range(section[4], section[4]+section[5], section[9]):
                name, value, size, info, _, index = struct.unpack_from('<IIIBBH', self.data, pos)
                name = strings[name:strings.index(b'\0', name)].decode('utf-8')
                if index and index < len(self.sections) and info & 15 == 2:
                    self.symbols.setdefault(name, []).append((value, size, index))

    def section_bytes(self, section):
        return self.data[section[4]:section[4]+section[5]]

    def function(self, name):
        hits = self.symbols.get(name, [])
        assert len(hits) == 1, ('Missing/duplicate function', name, hits)
        value, size, index = hits[0]
        section = self.sections[index]
        start = section[4] + value - (section[3] if self.kind != 1 else 0)
        code = self.data[start:start+size]
        assert len(code) == size
        return value, code


def normalized_body(code):
    """Only external ARM BL displacement bits differ between object and link."""
    assert len(code) == 248, 'Motion slot must remain 248 B'
    result = bytearray(code)
    for offset in range(0, 248, 4):
        word = struct.unpack_from('<I', result, offset)[0]
        if word & 0xff000000 == 0xeb000000:
            struct.pack_into('<I', result, offset, word & 0xff000000)
    return digest(result)


def branch_target(word, address):
    immediate = word & 0xffffff
    if immediate & 0x800000:
        immediate -= 0x1000000
    return address + 8 + immediate*4


def prove_motion(address, code, entry):
    assert len(code) == 248, 'Frozen motion slot changed'
    assert normalized_body(code) == QUALIFIED_BODY, 'Unqualified motion instructions'
    returns = [offset for offset in range(0, len(code), 4)
               if struct.unpack_from('<I', code, offset)[0] == 0xe8bd8010]
    assert len(returns) == 1, ('Unqualified return', returns)
    end = returns[0]+4
    pool = struct.pack('<6I', 0x60000000, 0x400921fb, 0, 0x40668000, 0x38d1b717, 0)
    pool_offset = (end+7) & ~7
    assert code[end:pool_offset] == b'\0'*(pool_offset-end), 'Non-padding after return'
    assert code[pool_offset:pool_offset+len(pool)] == pool, 'Unexpected motion constants'
    assert code[pool_offset+len(pool):] == b'\0'*(len(code)-pool_offset-len(pool)), 'Nonzero retained tail'
    calls = Counter()
    targets = {entry(name): name for name in ('cos', 'sin', 'roundf')}
    for offset in range(0, end, 4):
        word = struct.unpack_from('<I', code, offset)[0]
        # No unqualified register branch, load-to-PC, or block-return form.
        assert word & 0x0ffffff0 not in (0x012fff10, 0x012fff30), ('Indirect branch', offset)
        assert not (word & 0x0c10f000 == 0x0410f000), ('Load to PC', offset)
        if word & 0x0e100000 == 0x08100000 and word & 0x8000:
            assert word == 0xe8bd8010 and offset == end-4, ('Unqualified block return', offset)
        if word & 0x0e000000 != 0x0a000000:
            continue
        target = branch_target(word, address+offset)
        if word & 0x01000000:
            assert target in targets, ('Unexpected component call', offset, hex(target))
            calls[targets[target]] += 1
        else:
            assert address <= target < address+end, ('Branch into retained tail/outside helper', offset)
    assert calls == Counter(cos=1, sin=1, roundf=2), ('Unqualified math call stages', calls)
    return dict(slot_bytes=len(code), returning_body_bytes=end, literal_pool_bytes=len(pool),
                zero_padding_bytes=len(code)-end-len(pool), calls=dict(calls),
                body_sha256=digest(code), normalized_body_sha256=normalized_body(code), no_branch_into_tail=True)


def verify(elf_path, receipt_root):
    receipts = list(receipt_root.rglob('pm.json')) if receipt_root.is_dir() else [receipt_root]
    assert len(receipts) == 1 and receipts[0].is_file(), ('One adapter receipt required', receipts)
    path = receipts[0]
    receipt = json.loads(path.read_text(encoding='utf-8'))
    assert receipt.get('schema') == 2 and receipt.get('exit') == 0, 'Missing successful current adapter receipt'
    assert receipt['adapter_sha256'] == digest(ADAPTER.read_bytes()), 'Stale adapter receipt'
    assert receipt['c_body_sha256'] == digest(BODY.read_bytes()), 'Stale motion source receipt'
    name = receipt['object_file']
    assert Path(name).name == name, 'Receipt object must be adjacent'
    obj = path.parent/name
    assert digest(obj.read_bytes()) == receipt['object_sha256'], 'Object differs from receipt'
    _, object_code = Elf(obj).function(SYMBOL)
    expected = normalized_body(object_code)
    assert expected == receipt['normalized_body_sha256'], 'Object body differs from receipt'
    linked = Elf(elf_path)
    address, code = linked.function(SYMBOL)
    assert normalized_body(code) == expected, 'Linked motion body differs from adapter output'
    proof = prove_motion(address, code, lambda name: linked.function(name)[0])
    return dict(elf_sha256=digest(linked.data), receipt_sha256=digest(path.read_bytes()), **proof)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--elf', type=Path, required=True)
    parser.add_argument('--receipt-root', type=Path, required=True)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    proof = verify(args.elf, args.receipt_root)
    if args.report:
        args.report.write_text(json.dumps(proof, indent=2)+'\n', encoding='utf-8')
    print('PARITY motion release verification: '+json.dumps(proof), flush=True)


if __name__ == '__main__':
    main()
