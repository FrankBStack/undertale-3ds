"""UNDERTALE's text voices per scene, from the bytecode (change papvoice; read by build_sfxplan.py).

Read-only. Numbers only leave this module.

UNDERTALE's dialogue writer plays its voice sound at every letter as a stop and then a play of the same sound. The
3DS reads a sound that isn't in its cache on the audio loader thread, so a first play waits a few frames as a pending
voice; each next letter's stop dropped that voice, and a line's first blips were lost (Papyrus's "HUMAN." in the fog
room lost up to all six). The sound record lists a voice only in the room where our
tours first read it, so the census finds every scene's voices from the code itself:

- the voice of each typer: the text setup call (an 11-argument script_execute, the sound its argument 8) in each
  `typer == N` case of the typer script, after that script's own `typer = M` remaps; a sound the writer's Alarm
  tests in `txtsound == S` and then picks at random among others (Mettaton, Temmie, the wingdings) brings those;
- a scene's code: the room's placed objects' events, room and instance creation code and the room plan record's code
  for it (a battle group: the record's code for the group), what those create (codeclose.py's creation walk), and the
  scripts that code calls (transitively, but not into codeclose's hubs: a phone call or menu every room reaches);
  inside an `if (room == N)` body, what the code names or calls counts for room N only;
- its typers: every constant that code stores in `typer`; the `\\T` codes in the text that code names (a text map key
  or the text itself); and the msc cases of the text script for each constant that code stores in `msc` (and the
  cases those cases chain to): their text's `\\T` codes and their typer stores.

Left out on purpose: the typer script, the text maps and the text script as code (each is a table over every
character), and the writer's own `\\T` table (it would list every voice everywhere); a `\\T` code counts through the
text that holds it instead. A voice chosen another way (a typer read from a variable, text built at run time) is not
found; the 3DS reads such a voice on the game thread at its first play when it is small (the plan's voice scene,
build_sfxplan.VOICE_SUB). Any shape this module doesn't know gives no census: the plan is built as before.
"""
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, '..', 'aot'))
import gmlaot as g  # noqa: E402
import codeclose  # noqa: E402

TYPER, MSC, TXTSOUND, ROOM = 'typer', 'msc', 'txtsound', 'room'
TEXT_MAP_MIN = 1000      # ds_map_add calls that make a code entry a text map
TYPER_CASES_MIN = 20     # `typer == N` cases that make a code entry the typer script
T_TABLE_MIN = 5          # `\T` letters that make a code entry the writer's table
MSC_CASES_MIN = 100      # switch cases that make a code entry the text script
SETUP_ARGS, SETUP_SOUND = 11, 8   # the text setup call: script_execute(setup, ..., sound, ...) and its sound argument
CMP_EQUAL = 3


def instrs(blob, start, end):
    out, a = [], start
    while a + 4 <= end:
        try:
            ins = g.Instr(blob, a)
        except g.Reject:
            break
        out.append(ins)
        a = ins.next
    return out


class VoiceCensus:
    def __init__(self, path, cc=None):
        self.ok = False
        self.note = None
        try:
            self.cc = cc if cc is not None else codeclose.CodeClosure(path)
            if not self.cc.ok:
                raise ValueError('no code closure')
            self._parse(path)
            self.ok = True
        except (SystemExit, ValueError, KeyError, IndexError, struct.error, UnicodeError, g.Reject) as e:
            self.note = str(e) or e.__class__.__name__

    def _parse(self, path):
        dw = g.DataWin(path)
        dw.patch_operands()
        self.dw = dw
        blob = dw.data
        funcs = [f['name'] for f in dw.funcs]
        vars_ = [v['name'] for v in dw.vars]
        self.funcs, self.vars = funcs, vars_
        code = dw.code
        self.code = code
        scripts = {}
        for i, c in enumerate(code):
            if c is not None and c['name'].startswith('gml_Script_'):
                scripts[c['name'][len('gml_Script_'):]] = i
        self.script_of_func = [scripts.get(n, -1) for n in funcs]

        def var_is(ins, name):
            return ins.extra is not None and 0 <= ins.var_index() < len(vars_) and vars_[ins.var_index()] == name

        def func_is(ins, name):
            return ins.op == g.OP_CALL and ins.extra is not None and 0 <= ins.extra < len(funcs) and funcs[ins.extra] == name

        def is_const(ins):
            return ins.op == g.OP_PUSHI or (ins.op == g.OP_PUSH and ins.t1 in (g.T_INT16, g.T_INT32))

        def const(ins):
            if ins.op == g.OP_PUSHI or ins.t1 == g.T_INT16:
                return ins.inst
            return ins.extra - (1 << 32) if ins.extra >= 1 << 31 else ins.extra

        def strg(ins):
            return dw.strg(ins.extra) if ins.op == g.OP_PUSH and ins.t1 == g.T_STRING and ins.extra is not None else None

        self.items, self.regions, self.calls = [], [], []
        text_maps, typer_script, t_table, msc_script = [], (0, -1), (0, -1, {}), (0, -1, [])
        self.text = {}
        writer_alarm = []
        for ci, c in enumerate(code):
            items, regions, calls = [], [], []
            if c is None or not c['length'] or c['offset'] != 0:
                self.items.append(items)
                self.regions.append(regions)
                self.calls.append(calls)
                continue
            ins_list = instrs(blob, c['abs'], c['abs'] + c['length'])
            adds = 0
            typer_tests = 0
            table = {}
            cases = []
            txt_tests = 0
            for k, ins in enumerate(ins_list):
                s = strg(ins)
                if s is not None:
                    items.append((ins.addr, 'str', s))
                if ins.op == g.OP_POP and k > 0 and is_const(ins_list[k - 1]):
                    if var_is(ins, TYPER):
                        items.append((ins.addr, TYPER, const(ins_list[k - 1])))
                    elif var_is(ins, MSC):
                        items.append((ins.addr, MSC, const(ins_list[k - 1])))
                # `if (room == N)`: what its body names counts for room N only.
                if ins.op in (g.OP_PUSH, g.OP_PUSHBLTN, g.OP_PUSHGLB) and ins.t1 == g.T_VAR and var_is(ins, ROOM) \
                        and k + 3 < len(ins_list) and is_const(ins_list[k + 1]) and ins_list[k + 2].op == g.OP_CMP \
                        and (ins_list[k + 2].word >> 8) & 0xFF == CMP_EQUAL and ins_list[k + 3].op == g.OP_BF:
                    regions.append((ins_list[k + 3].next, ins_list[k + 3].target(), const(ins_list[k + 1])))
                if ins.op == g.OP_CALL and ins.extra is not None:
                    calls.append((ins.addr, ins.extra))
                    if func_is(ins, 'ds_map_add') and (ins.word & 0xFFFF) == 3:
                        adds += 1
                if ins.op == g.OP_PUSHGLB and var_is(ins, TYPER) and k + 3 < len(ins_list) and is_const(ins_list[k + 1]) \
                        and ins_list[k + 2].op == g.OP_CMP and ins_list[k + 3].op == g.OP_BF:
                    typer_tests += 1
                if s is not None and len(s) == 1 and k + 4 < len(ins_list) and ins_list[k + 1].op == g.OP_CMP \
                        and ins_list[k + 2].op == g.OP_BF and is_const(ins_list[k + 3]) and ins_list[k + 4].op == g.OP_POP \
                        and var_is(ins_list[k + 4], TYPER):
                    table[s.decode('latin-1')] = const(ins_list[k + 3])
                if ins.op == g.OP_DUP and k + 3 < len(ins_list) and is_const(ins_list[k + 1]) \
                        and ins_list[k + 2].op == g.OP_CMP and (ins_list[k + 2].word >> 8) & 0xFF == CMP_EQUAL \
                        and ins_list[k + 3].op == g.OP_BT:
                    cases.append((const(ins_list[k + 1]), ins_list[k + 3].target() - c['abs']))
                if ins.op in (g.OP_PUSH,) and ins.t1 == g.T_VAR and var_is(ins, TXTSOUND):
                    txt_tests += 1
            self.items.append(items)
            self.regions.append(regions)
            self.calls.append(calls)
            if adds >= TEXT_MAP_MIN:
                text_maps.append((ci, ins_list))
            if typer_tests > typer_script[0]:
                typer_script = (typer_tests, ci)
            if len(table) > t_table[0]:
                t_table = (len(table), ci, table)
            if len(cases) > msc_script[0]:
                msc_script = (len(cases), ci, cases)
            if txt_tests >= 3:
                writer_alarm.append((ci, ins_list))
        if not text_maps:
            raise ValueError('no text map')
        if typer_script[0] < TYPER_CASES_MIN:
            raise ValueError('no typer script')
        if t_table[0] < T_TABLE_MIN:
            raise ValueError('no writer \\T table')
        if msc_script[0] < MSC_CASES_MIN:
            raise ValueError('no text script')
        # The text maps: text then key pushed, then the map, then ds_map_add.
        for _ci, ins_list in text_maps:
            last = []
            for ins in ins_list:
                s = strg(ins)
                if s is not None:
                    last = (last + [s])[-2:]
                elif func_is(ins, 'ds_map_add'):
                    if len(last) == 2:
                        self.text.setdefault(last[1], set()).add(last[0])
                    last = []
        # The typer script: sequential `typer == N` cases.
        ci = typer_script[1]
        c = code[ci]
        ins_list = instrs(blob, c['abs'], c['abs'] + c['length'])
        sound_of, remap, cur, stack = {}, {}, None, []
        for k, ins in enumerate(ins_list):
            if ins.op == g.OP_PUSHGLB and var_is(ins, TYPER) and k + 3 < len(ins_list) and is_const(ins_list[k + 1]) \
                    and ins_list[k + 2].op == g.OP_CMP and ins_list[k + 3].op == g.OP_BF:
                cur, stack = const(ins_list[k + 1]), []
                continue
            if cur is None:
                continue
            if is_const(ins):
                stack.append(const(ins))
            elif ins.op == g.OP_POP and var_is(ins, TYPER):
                if stack and stack[-1] is not None:
                    remap.setdefault(cur, stack[-1])
                stack = []
            elif ins.op == g.OP_CALL:
                argc = ins.word & 0xFFFF
                args = [stack[-(j + 1)] if len(stack) > j else None for j in range(argc)]
                del stack[max(0, len(stack) - argc):]
                stack.append(None)
                if func_is(ins, 'script_execute') and argc == SETUP_ARGS and args[SETUP_SOUND] is not None:
                    sound_of.setdefault(cur, args[SETUP_SOUND])
            elif ins.op in (g.OP_PUSH, g.OP_PUSHLOC, g.OP_PUSHGLB, g.OP_PUSHBLTN):
                if ins.t1 == g.T_VAR and ((ins.extra >> 24) & 0xF8) == 0x00:
                    del stack[-2:]
                stack.append(None)
            elif ins.op in (g.OP_MUL, g.OP_DIV, g.OP_REM, g.OP_MOD, g.OP_ADD, g.OP_SUB, g.OP_AND, g.OP_OR, g.OP_XOR,
                            g.OP_SHL, g.OP_SHR, g.OP_CMP):
                del stack[-2:]
                stack.append(None)
            elif ins.op in (g.OP_POPZ, g.OP_BF, g.OP_BT):
                del stack[-1:]
        if not sound_of:
            raise ValueError('the typer script names no sound')
        self.sound_of, self.remap = sound_of, remap
        self.t_table = t_table[2]
        # Random variants: in the writer's Alarm, `txtsound == S` and the sounds its case plays.
        variants = {}
        for _ci, ins_list in writer_alarm:
            for k, ins in enumerate(ins_list):
                if ins.op == g.OP_PUSH and ins.t1 == g.T_VAR and var_is(ins, TXTSOUND) and k + 3 < len(ins_list) \
                        and is_const(ins_list[k + 1]) and ins_list[k + 2].op == g.OP_CMP and ins_list[k + 3].op == g.OP_BF:
                    s, end = const(ins_list[k + 1]), ins_list[k + 3].target()
                    byfunc = {}
                    for j in range(k + 4, len(ins_list) - 1):
                        if ins_list[j].addr >= end:
                            break
                        call = ins_list[j + 1]
                        if call.op == g.OP_CONV and j + 2 < len(ins_list):
                            call = ins_list[j + 2]
                        if is_const(ins_list[j]) and call.op == g.OP_CALL and (call.word & 0xFFFF) == 1:
                            byfunc.setdefault(call.extra, set()).add(const(ins_list[j]))
                    # The case stops every variant (S first) and then plays one of them: what both calls name.
                    sets = [v for v in byfunc.values() if s in v]
                    played = set.intersection(*sets) if len(sets) >= 2 else set()
                    if len(played) > 1:
                        variants.setdefault(s, set()).update(played)
        self.variants = variants
        # The text script's cases: each case's text, typer stores and msc stores (chains).
        ci, cases = msc_script[1], msc_script[2]
        c = code[ci]
        targets = sorted({t for _n, t in cases if 0 <= t < c['length']})
        bounds = {t: (targets[i + 1] if i + 1 < len(targets) else c['length']) for i, t in enumerate(targets)}
        self.msc_case = {}
        for n, t in cases:
            if t not in bounds or n in self.msc_case:
                continue
            body = instrs(blob, c['abs'] + t, c['abs'] + bounds[t])
            keys, typers, mscs = set(), set(), set()
            for k, ins in enumerate(body):
                s = strg(ins)
                if s is not None:
                    keys.add(s)
                if ins.op == g.OP_POP and k > 0 and is_const(body[k - 1]):
                    if var_is(ins, TYPER):
                        typers.add(const(body[k - 1]))
                    elif var_is(ins, MSC):
                        mscs.add(const(body[k - 1]))
            self.msc_case[n] = (keys, typers, mscs)
        self.skip = {typer_script[1], t_table[1], msc_script[1]} | {ci for ci, _ in text_maps}

    # --- per scene
    def voices_of_typer(self, typer):
        t, seen = typer, set()
        while t not in self.sound_of and t in self.remap and t not in seen:
            seen.add(t)
            t = self.remap[t]
        s = self.sound_of.get(t)
        if s is None:
            return []
        return sorted(self.variants.get(s, {s}))

    def _text_typers(self, strings):
        out = set()
        for s in strings:
            for text in self.text.get(s, set()) | {s}:
                i = text.find(b'\\T')
                while i >= 0 and i + 2 < len(text) + 1:
                    ch = text[i + 2:i + 3].decode('latin-1')
                    if ch in self.t_table:
                        out.add(self.t_table[ch])
                    i = text.find(b'\\T', i + 2)
        return out

    def _other_rooms(self, c, room, battle):
        """Code c's `if (room == N)` bodies for rooms other than room (none in a battle: its room is the battle room)."""
        return [(a, b) for a, b, n in self.regions[c] if n != room] if not battle else []

    def scene_codes(self, room, record_code, battle=False):
        cc = self.cc
        seeds = set(c for c in record_code if 0 <= c < len(self.code))
        if not battle:
            seeds |= cc.change_codes(room)
        codes = (set(seeds) | set(cc.ordered(seeds))) - self.skip - cc.hubs
        # The scripts that code calls, transitively, the tables and codeclose's hubs aside (a phone call or menu reached
        # from everywhere is left to the 3DS's read at the play).
        todo = list(codes)
        while todo:
            c = todo.pop()
            other = self._other_rooms(c, room, battle)
            for addr, f in self.calls[c] if 0 <= c < len(self.calls) else ():
                if any(a <= addr < b for a, b in other):
                    continue
                s = self.script_of_func[f] if 0 <= f < len(self.script_of_func) else -1
                if s >= 0 and s not in codes and s not in self.skip and s not in cc.hubs:
                    codes.add(s)
                    todo.append(s)
        return codes

    def scene_voices(self, room, record_code, battle=False):
        """The sound indices of the scene's text voices, sorted."""
        codes = self.scene_codes(room, record_code, battle)
        typers, strings, mscs = set(), set(), set()
        for c in codes:
            other = self._other_rooms(c, room, battle)
            for addr, kind, value in self.items[c]:
                if any(a <= addr < b for a, b in other):
                    continue
                (typers if kind == TYPER else mscs if kind == MSC else strings).add(value)
        todo, done = sorted(mscs), set()
        while todo:
            n = todo.pop()
            if n in done or n not in self.msc_case:
                continue
            done.add(n)
            keys, ts, ms = self.msc_case[n]
            strings.update(keys)
            typers.update(ts)
            todo.extend(m for m in ms if m not in done)
        typers |= self._text_typers(strings)
        out = set()
        for t in typers:
            out.update(self.voices_of_typer(t))
        return sorted(out)

    def all_voices(self):
        out = set()
        for t in set(self.sound_of) | set(self.remap):
            out.update(self.voices_of_typer(t))
        return sorted(out)
