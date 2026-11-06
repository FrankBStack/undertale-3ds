"""Decode ARM TLS GOT permutations without allowing opcode or target changes."""
from bisect import bisect_right
from collections import Counter
from pathlib import Path
import struct


class ElfBytes:
    def __init__(self, path: Path):
        self.raw = path.read_bytes()
        header = struct.unpack_from('<16sHHIIIIIHHHHHH', self.raw)
        if header[0][:6] != b'\x7fELF\x01\x01':
            raise ValueError('Expected little-endian ELF32')
        sections = [struct.unpack_from('<10I', self.raw, header[6]+i*header[11])
                    for i in range(header[12])]
        # Debug sections use address zero and can overlap valid VMAs numerically. Only loaded,
        # non-TLS sections describe bytes at a symbol's runtime address (TLS symbols are offsets).
        self.sections = [s for s in sections if s[2] & 2 and not s[2] & 0x400]

    def read(self, address: int, size: int) -> bytes:
        for section in self.sections:
            if section[3] <= address and address+size <= section[3]+section[5]:
                if section[1] == 8:
                    return bytes(size)
                offset = section[4]+address-section[3]
                return self.raw[offset:offset+size]
        raise ValueError(f'Unmapped bytes at {address:#x} + {size}')


class ArmMetadata:
    def __init__(self, memory):
        self.memory = memory
        raw = memory.raw
        header = struct.unpack_from('<16sHHIIIIIHHHHHH', raw)
        assert header[2] == 40, 'ARM ELF required'
        self.sections = [struct.unpack_from('<10I', raw, header[6]+i*header[11])
                         for i in range(header[12])]
        def string(section, offset):
            start = section[4]+offset
            return raw[start:raw.index(b'\0', start)].decode('utf-8')
        self.names = [string(self.sections[header[13]], s[0]) for s in self.sections]
        self.symbols = []
        self.maps = {}
        for section in self.sections:
            if section[1] != 2:  # SHT_SYMTAB
                continue
            strings = self.sections[section[6]]
            for offset in range(section[4], section[4]+section[5], section[9]):
                name, value, size, info, other, index = struct.unpack_from('<IIIBBH', raw, offset)
                name = string(strings, name)
                self.symbols.append((name, value, size, info, other, index))
                if name.startswith(('$a', '$d', '$t')) and index < len(self.sections):
                    self.maps.setdefault(index, []).append((value, name[:2]))
        for index in self.maps:
            self.maps[index] = sorted(set(self.maps[index]))

    def kind(self, address):
        for index, section in enumerate(self.sections):
            if section[2] & 4 and section[3] <= address < section[3]+section[5]:
                maps = self.maps.get(index, [])
                position = bisect_right(maps, (address, '\uffff'))-1
                return maps[position][1] if position >= 0 else None
        return None

    def arm_words(self):
        for index, section in enumerate(self.sections):
            if not section[2] & 4:
                continue
            maps = self.maps.get(index, [])
            for i, (start, kind) in enumerate(maps):
                end = maps[i+1][0] if i+1 < len(maps) else section[3]+section[5]
                # No Thumb code in these builds. Never silently miss an unsupported TLS consumer.
                assert kind != '$t', 'Thumb GOT audit is not implemented'
                if kind == '$a':
                    offset = section[4]+start-section[3]
                    for relative in range(0, end-start-3, 4):
                        yield start+relative, struct.unpack_from('<I', self.memory.raw, offset+relative)[0]

    def tls_definitions(self):
        return sorted((name, value, size, info, other, self.names[index],
                       self.sections[index][1:4], self.sections[index][5], self.sections[index][8],
                       (self.memory.raw[self.sections[index][4]:self.sections[index][4]+self.sections[index][5]].hex()
                        if self.sections[index][1] != 8 else None))
                      for name, value, size, info, other, index in self.symbols
                      if info & 15 == 6 and index < len(self.sections))


def literal_load(word, pc):
    """ARM LDR Rd,[pc,+/-imm12], pre-indexed, word, no writeback."""
    if word >> 28 == 15 or word & 0x0f7f0000 != 0x051f0000:
        return None
    displacement = (word & 0xfff) * (1 if word & 0x800000 else -1)
    return (word >> 12) & 15, (pc+8+displacement) & 0xffffffff


def got_load(word):
    """ARM LDR Rd,[pc,+/-Rm], no shift/writeback; return offset register and sign."""
    if word >> 28 == 15 or word & 0x0f7f0ff0 != 0x071f0000:
        return None
    return word & 15, 1 if word & 0x800000 else -1


def preserves_offset(word, register):
    """Conservative straight-line dataflow: no use/clobber of the unconsumed offset."""
    if word >> 28 != 14:
        return False
    rd, rn, rm = (word >> 12) & 15, (word >> 16) & 15, word & 15
    if word & 0x0f8f00f0 == 0x068f0070:  # SXTB/SXTH/UXTB/UXTH (Rn = 15: no accumulate), any rotation
        return rd not in (register, 15) and rm != register
    if word & 0x0c000000 == 0x04000000:  # immediate load/store, preindexed, no writeback
        return (not word & 0x02000000 and bool(word & 0x01000000)
                and not word & 0x00200000 and rn != register and rd not in (register, 15))
    if word & 0x0e000090 == 0x00000090 and word & 0x60:  # STRH/LDRH/LDRSB/LDRSH/LDRD/STRD
        # Pre-indexed, no writeback; never based on, loaded into or (register form) indexed by the offset
        # register, and never writing the PC. LDRD/STRD (L=0, SH=1x) also name Rd+1.
        load, dual = bool(word & 0x00100000), not word & 0x00100000 and bool(word & 0x40)
        if not word & 0x01000000 or word & 0x00200000 or rn == register or rd == 15:
            return False
        if dual and (rd & 1 or rd+1 in (register, 15)):
            return False
        if (load or dual) and rd == register:
            return False
        return bool(word & 0x00400000) or rm != register
    if word & 0x0d900000 == 0x01100000:  # TST/TEQ/CMP/CMN: flags only, no register write
        return rn != register and (bool(word & 0x02000000) or (not word & 0x10 and rm != register))
    if word & 0x0c000000 == 0:  # ordinary MOV/ADD/SUB only; no multiply/misc/flag mutation
        opcode = (word >> 21) & 15
        return (opcode in (2, 4, 13) and not word & 0x00100000 and rd not in (register, 15)
                and (opcode == 13 or rn != register)
                and (bool(word & 0x02000000) or (not word & 0x10 and rm != register)))
    return False


def branch_target(pc, word):
    """Target of an ARM B/BL (any condition but 15), else None."""
    if word >> 28 == 15 or word & 0x0e000000 != 0x0a000000:
        return None
    return (pc+8+(((word & 0xffffff) ^ 0x800000)-0x800000)*4) & 0xffffffff


def read_tp_entries(meta):
    """Addresses of __aeabi_read_tp, checked to write only r0: MRC TPIDRURO-class into r0, then
    LDR r0,[r0,#imm] words, then BX LR. The assembler symbol has size 0, so read up to its BX LR."""
    entries = set()
    for name, value, size, info, other, index in meta.symbols:
        if name != '__aeabi_read_tp' or info & 15 != 2:
            continue
        words = [int.from_bytes(meta.memory.read(value+4*i, 4), 'little') for i in range(4)]
        assert 0xe12fff1e in words, ('__aeabi_read_tp body not recognised', [hex(w) for w in words])
        words = words[:words.index(0xe12fff1e)+1]
        assert words[0] == 0xee1d0f70, ('__aeabi_read_tp must start with mrc p15,0,r0,c13,c0,3', hex(words[0]))
        only_r0 = all(w & 0xffff0000 == 0xe5900000 and (w >> 12) & 15 == 0 for w in words[1:-1])
        assert only_r0, ('__aeabi_read_tp may only load into r0 from r0', [hex(w) for w in words])
        entries.add(value)
    return entries


def trace_offset(meta, consumer, register, read_tp=frozenset()):
    """Find a literal load in the same basic block, with every intervening instruction proven safe.
    A conditional B may leave the block (the fallthrough keeps the register); a BL is allowed only to a
    verified __aeabi_read_tp, which writes r0 alone (LR is the BL's own). Callers must also check that
    no branch lands inside the traced span."""
    memory = meta.memory
    for distance in range(4, 36, 4):
        address = consumer-distance
        if meta.kind(address) != '$a':
            return None
        word = int.from_bytes(memory.read(address, 4), 'little')
        load = literal_load(word, address)
        if load and load[0] == register:
            assert meta.kind(load[1]) == '$d', 'Offset is not a mapped data literal'
            return address, load[1], word >> 28
        if word >> 28 not in (14, 15) and word & 0x0f000000 == 0x0a000000:
            continue
        if word & 0xff000000 == 0xeb000000:
            if branch_target(address, word) in read_tp and register not in (0, 12, 14):
                continue
            return None
        if not preserves_offset(word, register):
            return None
    return None


def same_target(old_slot, new_slot, old_slots, new_slots):
    assert old_slot in old_slots and new_slot in new_slots, 'Unmapped GOT slot'
    assert old_slots[old_slot] == new_slots[new_slot], 'GOT load resolves to a different symbol'
    return old_slots[old_slot]


def prove(base, candidate, old_memory, new_memory, pinned):
    """Return exact word-address exceptions plus a proof for every GOT consumer, including unchanged words."""
    old_got = next((s for s in base.sections if s.name == '.got'), None)
    new_got = next((s for s in candidate.sections if s.name == '.got'), None)
    if old_got is None and new_got is None:
        return {}, {}
    assert old_got and new_got and (old_got.addr, old_got.size) == (new_got.addr, new_got.size)
    old = old_memory.read(old_got.addr, old_got.size)
    new = new_memory.read(new_got.addr, new_got.size)
    if old == new:
        return {}, {}
    assert old_got.size % 4 == 0
    values = lambda data: struct.unpack('<'+'I'*(len(data)//4), data)
    assert Counter(values(old)) == Counter(values(new)), 'GOT values are not a permutation'
    before, after = ArmMetadata(old_memory), ArmMetadata(new_memory)
    read_tp = read_tp_entries(before)
    assert read_tp == read_tp_entries(after), '__aeabi_read_tp moved'
    # Every direct branch target in either image; none may land inside a traced span (it would skip the
    # literal load, or enter after it with another value in the offset register).
    targets = {t for meta in (before, after) for pc, word in meta.arm_words()
               for t in [branch_target(pc, word)] if t is not None}
    tls = before.tls_definitions()
    assert tls == after.tls_definitions(), 'TLS definition, size, section or offset changed'
    assert all(s[8] <= 8 for s in before.sections if s[2] & 0x400), 'Unsupported TLS alignment/TCB bias'
    def slots(data):
        result = {}
        for i, value in enumerate(values(data)):
            # ARM EABI's TCB has two 32-bit words; TLS IE GOT entries include that 8-byte bias.
            names = [name for name, offset, size, info, _, _ in before.symbols
                     if info & 15 == 6 and size and not name.startswith(('$', '.')) and offset+8 == value]
            assert len(names) == 1, ('GOT entry must identify exactly one defined TLS variable', value, names)
            result[old_got.addr+4*i] = names[0]
        return result
    old_slots, new_slots = slots(old), slots(new)
    exceptions, consumers, reached = {}, [], set()
    def owner(address):
        found = [(name, start) for (name, kind), entries in base.symbols.items() if kind in ('T', 't')
                 for start, size in entries if start <= address < start+size]
        assert len(found) == 1, ('GOT consumer needs one owning function', address, found)
        return found[0]
    def audit(meta, other, is_old):
        for pc, word in meta.arm_words():
            load = got_load(word)
            if load is None:
                continue
            traced = trace_offset(meta, pc, load[0], read_tp)
            if traced is None:
                # PC-indexed loads without this supported literal dataflow are not silently skipped.
                raise AssertionError(('Unsupported PC-indexed GOT consumer', hex(pc)))
            producer, literal, condition = traced
            assert not any(producer < t <= pc for t in targets), ('Branch into traced span', hex(pc))
            value = int.from_bytes(meta.memory.read(literal, 4), 'little')
            slot = (pc+8+load[1]*value) & 0xffffffff
            if not old_got.addr <= slot < old_got.end:
                continue
            assert meta.memory.read(pc, 4) == other.memory.read(pc, 4), 'GOT load opcode changed'
            assert meta.memory.read(producer, 4) == other.memory.read(producer, 4), 'Literal load opcode changed'
            assert word >> 28 == condition, 'Literal and consumer conditions differ'
            for address in range(producer+4, pc, 4):
                assert meta.memory.read(address, 4) == other.memory.read(address, 4), 'Offset dataflow changed'
            assert other.kind(literal) == '$d', 'Literal kind changed'
            other_value = int.from_bytes(other.memory.read(literal, 4), 'little')
            other_slot = (pc+8+load[1]*other_value) & 0xffffffff
            old_slot, new_slot = (slot, other_slot) if is_old else (other_slot, slot)
            name = same_target(old_slot, new_slot, old_slots, new_slots)
            if is_old:
                reached.add(pc)
                function, start = owner(literal)
                proof = dict(kind='GOT/literal permutation (decoded same-target)', function=function,
                    offset=hex(literal-start), address=hex(literal),
                    old=hex(value), new=hex(other_value), old_slot=hex(old_slot), new_slot=hex(new_slot),
                    symbol=name, producer=hex(producer), consumer=hex(pc),
                    literal_load=hex(int.from_bytes(meta.memory.read(producer, 4), 'little')),
                    got_load=hex(word), condition=condition)
                consumers.append(proof)
                if value != other_value:
                    assert function not in pinned, 'GOT permutation changes a hot-pinned function'
                    exceptions[literal] = proof
            else:
                assert pc in reached, 'Candidate introduces another GOT consumer'
    audit(before, after, True)
    audit(after, before, False)
    assert consumers, 'Changed GOT has no decoded consumers'
    # GOT contents are data. Each value is a TLS identity, and every consumer has been audited above.
    for i, (a, b) in enumerate(zip(values(old), values(new))):
        if a != b:
            address = old_got.addr+4*i
            relocated_slots = [hex(slot) for slot, name in new_slots.items() if name == old_slots[address]]
            exceptions[address] = dict(kind='GOT/literal permutation (decoded same-target)',
                function='.got', offset=hex(4*i), address=hex(address), old=hex(a), new=hex(b),
                old_slot=hex(address), same_target_new_slots=relocated_slots, symbol=old_slots[address],
                candidate_symbol_at_old_slot=new_slots[address],
                consumer_coverage='all ARM GOT loads audited')
    return exceptions, dict(tls_definitions_unchanged=len(tls), consumers=consumers,
                            slot_values_unchanged_multiset=True, got_address=hex(old_got.addr),
                            got_bytes=old_got.size)
