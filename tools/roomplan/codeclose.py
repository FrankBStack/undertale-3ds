"""UNDERTALE's in-play code closure for the room plan: the bytecode a scene can run in play that neither its record nor
the room change stages (Old 3DS; codeclose, ruling H1v 2026-10-28).

Read-only. Numbers only leave this module. On the Old 3DS the bytecode sits in an SD cache file in 4 KB groups
(engine data_win.c DataWin_moveBytecodeToFile: blobs in file order, a new group when a blob would end more than
CODE_GROUP_BYTES past the group's start), read on first use into an arena that never frees. The room change reads a
scene's planned code (z_roomload.c rlReadCode, then z_utstall.c usReadCode) and the placed objects' events; code first
needed later blocks the game thread in play (about 8.5 ms a read plus 0.145 ms a KB on the o3ds). Most of that is code
of objects created in play: the cast roll's monster bodies, the Ruins' faded music and Flowey's stalker.

Rule H1v, per scene: seeds = what the room change has today (the placed objects' events but Destroy, CleanUp and
PreCreate; room and instance creation code; the plan scene's code; all the record's code; a battle group: its plan
code and record only). Breadth first from the seeds in index order, an instance_create / instance_create_depth /
instance_change whose object is a constant, or a variable the same object (or a parent) only ever stores constants
into, adds every event of that object and its parents. Script calls are not followed, and nothing is followed out of
the hub scripts (HUBS: dispatchers over every battle, text and save). Each group the closure reaches that the seeds'
groups do not cover adds its lowest code index to the scene's code, until the scene's extras reach CAP_BYTES (a later
smaller group still fits). What chains of Create events reach comes first (a monster's body, drawn every frame), then
what other events create on some branch (attacks): the cap and the room load's deadline (z_utstall.c usReadCode reads
the list in order) cut the latter first. Rooms with no record scene get a code-only scene (no tiles) when the closure
adds any. (Rev 2, argclosereview F4/F5: stores read in the VM's pop order, only plain variables' stores count; the
Create-first order.)

The placed art rule (placed_art_sprites; closure.py, whole sets) reads the same walk for two more things: the constants
stored in any kind of variable and the constants drawn. build_plan.placed_art decides which rooms take it. The portrait rule
(face_art_sprites) walks from every placed object for the portraits their dialogue opens with.

Any data.win this module can't read (not GameMaker 1.x bytecode 15+, a chunk missing) gives no closure: the plan is
built as before.
"""
import hashlib
import os
import struct
import sys
from collections import deque

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'aot'))
import gmlaot as g  # noqa: E402

CODE_GROUP_BYTES = 4096    # data_win.c CODE_GROUP_BYTES
CAP_BYTES = 256 * 1024     # a scene's extras at most (ruling 2026-10-28: a guard, the largest H1v scene is 268 KB)
EVENT_CREATE, EVENT_DESTROY, EVENT_CLEANUP, EVENT_PRECREATE = 0, 1, 12, 14
SKIP_CHANGE = (EVENT_DESTROY, EVENT_CLEANUP, EVENT_PRECREATE)   # z_roomload does not stage these
OBJT_EVENT_TYPE_COUNT = 15
SPAWN_ARG = {'instance_create': 2, 'instance_change': 0, 'instance_create_depth': 3}
DRAW_FUNCTIONS = frozenset(('draw_sprite', 'draw_sprite_ext', 'draw_sprite_part', 'draw_sprite_part_ext',
                            'draw_sprite_stretched', 'draw_sprite_stretched_ext', 'draw_sprite_tiled',
                            'draw_sprite_tiled_ext', 'draw_sprite_general', 'draw_sprite_pos'))  # the sprite: arg 0
# The calls that play a sound given as their first argument (the game's play script, the two caster calls, and
# GameMaker's own), by the SHA-1 of each name: battle_sounds.
SOUND_CALLS = frozenset(('e585d118da83dd04055f6dcadeb9c32788cf27db', '322c99a28de4caa381eda2028db3deece1253753',
                         'd7e2b3ef90de85761e2708dd6614959783e69350', 'c08da0c033a01133f51e28b55e58a1f9c023fc2b'))
HUBS = ('scr_battlegroup', 'textdata_en', 'textdata_ja', 'SCR_TEXT', 'scr_gettext', 'scr_papcall', 'scr_torcall',
        'scr_itemuseb', 'SCR_GAMESTART', 'scr_load', 'scr_save', 'scr_saveprocess', 'scr_namingscreen')
FACE_CHOOSER, FACE_CHOICE, FACE_POSES, FACE_CREATES = 'scr_facechoice', 'facechoice', 'u', 'instance_create'  # a dialogue's portrait: placed_art_sprites
CMP_EQUAL = 3              # the compare kind in a cmp instruction's second byte
VARTYPE_ARRAY, VARTYPE_STACKTOP, VARTYPE_NORMAL = 0x00, 0x80, 0xA0   # vm.h
WALK_VISITS = 8            # an address walked more often than this is left (loops converge well before)


class CodeClosure:
    face_objects = {}      # {facechoice value: the objects the chooser creates for it}
    face_note = None       # why face_objects is empty: build_plan prints it

    def __init__(self, path):
        self.ok = False
        try:
            self._parse(path)
            self.ok = True
        except (SystemExit, ValueError, KeyError, IndexError, struct.error, UnicodeError, g.Reject):
            pass

    # --- data.win
    def _parse(self, path):
        dw = g.DataWin(path)
        dw.patch_operands()
        self.d = d = dw.data

        def plist(at):
            n = struct.unpack_from('<I', d, at)[0]
            return struct.unpack_from('<%dI' % n, d, at + 4)

        def chunk(name):
            return plist(dw.chunks[name][0])

        def i32(p):
            return struct.unpack_from('<i', d, p)[0]

        self.parent_by_obj, self.events_by_obj, self.event_type, self.sprite_by_obj = [], [], {}, []
        for p in chunk('OBJT'):
            self.sprite_by_obj.append(i32(p + 4))
            self.parent_by_obj.append(i32(p + 24))
            nverts = i32(p + 64)
            ev = {}
            for t, tp in enumerate(plist(p + 64 + 4 + 12 + max(nverts, 0) * 8)[:OBJT_EVENT_TYPE_COUNT]):
                for ep in plist(tp):
                    for ap in plist(ep + 4):
                        cid = i32(ap + 32)
                        if cid >= 0:
                            ev.setdefault(t, []).append(cid)
                            self.event_type.setdefault(cid, t)
            self.events_by_obj.append(ev)
        self.cc_by_room, self.insts_by_room = [], []
        for p in chunk('ROOM'):
            self.cc_by_room.append(i32(p + 32))
            self.insts_by_room.append([(i32(q + 8), i32(q + 16)) for q in plist(struct.unpack_from('<I', d, p + 48)[0])])
        scripts = {}
        for p in chunk('SCPT'):
            if p:
                scripts[dw.string(struct.unpack_from('<I', d, p)[0])] = i32(p + 4)
        self.hubs = {scripts[n] for n in HUBS if scripts.get(n, -1) >= 0}
        # The engine's groups (data_win.c): distinct blobs by offset (the longest length), in file order.
        code = dw.code
        size = {}
        for c in code:
            if c is not None and c['length']:
                size[c['abs']] = max(size.get(c['abs'], 0), c['length'])
        blobs = sorted(size.items())
        group, start, self.group_size, blob_group = 0, {}, {}, {}
        for i, (a, n) in enumerate(blobs):
            if a + n - blobs[group][0] > CODE_GROUP_BYTES:
                group = i
            blob_group[a] = group
            start.setdefault(group, a)
            self.group_size[group] = max(self.group_size.get(group, 0), a + n - start[group])
        # An empty entry (length 0, an event with no code) sits at the start of another entry's blob, and the engine
        # still reads that blob's group the first time it runs (DataWin_loadCodeBytes checks only `present`): it gets
        # that group (UT 1.08: 120 entries; a cast-roll step event was read in play, uthunt 10-31).
        self.code_group = [blob_group.get(c['abs']) if c is not None else None for c in code]
        self.group_rep = {}  # a group's lowest entry with bytes: what a plan lists
        for c, grp in enumerate(self.code_group):
            if grp is not None and grp not in self.group_rep and code[c]['length']:
                self.group_rep[grp] = c
        # Each entry's spawn targets and constant stores; the object that owns it.
        funcs = [f['name'] for f in dw.funcs]
        vars_ = [v['name'] for v in dw.vars]
        self.spawns, self.var_spawns, self.stores, self.any_stores, self.draws = [], [], [], [], []
        self.sounds, self.var_sounds = [], []
        sound_calls = frozenset(f for f in funcs if hashlib.sha1(f.encode('utf-8')).hexdigest() in SOUND_CALLS)
        for c in code:
            if c is None or not c['length']:
                r = {'spawns': set(), 'var_spawns': set(), 'stores': {}, 'any_stores': {}, 'draws': set(),
                     'sounds': set(), 'var_sounds': set()}
            else:
                r = walk(d, c['abs'], c['length'], funcs, vars_, sound_calls)
            self.spawns.append(r['spawns'])
            self.var_spawns.append(r['var_spawns'])
            self.stores.append(r['stores'])
            self.any_stores.append(r['any_stores'])
            self.draws.append(r['draws'])
            self.sounds.append(r['sounds'])
            self.var_sounds.append(r['var_sounds'])
        chooser = scripts.get(FACE_CHOOSER, -1)
        if 0 <= chooser < len(code) and code[chooser] and code[chooser]['length']:
            self.face_objects, self.face_note = read_chooser(d, code[chooser]['abs'], code[chooser]['length'], funcs, vars_)
        else:
            self.face_note = 'no chooser script'
        self.owner = {}
        for o in range(len(self.events_by_obj)):
            for cc in self.object_codes(o, parents=False):
                self.owner[cc] = o

    def object_codes(self, obj, skip=(), parents=True):
        """Every event code entry of obj and its parents (event types in skip aside), in data.win order."""
        out, seen = [], set()
        while 0 <= obj < len(self.events_by_obj) and obj not in seen and len(seen) < 32:
            seen.add(obj)
            for t, codes in self.events_by_obj[obj].items():
                if t not in skip:
                    out += codes
            if not parents:
                break
            obj = self.parent_by_obj[obj]
        return out

    # --- the closure
    def change_codes(self, room):
        """What the room change stages for a room whatever the plan says: its placed objects' events as z_roomload
        takes them, room and instance creation code."""
        out = set()
        if not 0 <= room < len(self.insts_by_room):
            return out
        for o in sorted({o for o, _cc in self.insts_by_room[room] if o >= 0}):
            out.update(self.object_codes(o, skip=SKIP_CHANGE))
        if self.cc_by_room[room] >= 0:
            out.add(self.cc_by_room[room])
        out.update(cc for _o, cc in self.insts_by_room[room] if cc >= 0)
        return out

    def _targets(self, c):
        targets = set(self.spawns[c])
        if self.var_spawns[c]:
            o = self.owner.get(c)
            family = self.object_codes(o) if o is not None else [c]
            for name in self.var_spawns[c]:
                for cc in family:
                    targets.update(x for x in self.stores[cc].get(name, ()) if 0 <= x < len(self.events_by_obj))
        return targets

    def ordered(self, seeds):
        """The code the seeds reach (seeds aside): first what chains of Create events reach (an object created in a
        Create is there whenever its creator is: a monster's body), then the rest (what Step, Alarm or other events
        create on some branch: attacks), each in breadth-first order."""
        every = self._reach(seeds, False)
        sure = set(self._reach(seeds, True))
        return [c for c in every if c in sure] + [c for c in every if c not in sure]

    def _reach(self, seeds, creates_only):
        seen, order, objs = set(seeds), [], set()
        q = deque(sorted(seeds))
        while q:
            c = q.popleft()
            if not 0 <= c < len(self.spawns) or c in self.hubs:
                continue
            if creates_only and c not in seeds and self.event_type.get(c, EVENT_CREATE) != EVENT_CREATE:
                continue
            for o in sorted(self._targets(c)):
                if o in objs or not 0 <= o < len(self.events_by_obj):
                    continue
                objs.add(o)
                for cc in self.object_codes(o):
                    if cc not in seen:
                        seen.add(cc)
                        order.append(cc)
                        q.append(cc)
        return order

    def placed_art_sprites(self, room):
        """The sprites the room's own objects can draw in play, whether or not a record saw them: for the objects
        placed in this room and no other, and what they can create (the same creation walk as _targets, nothing
        followed out of a hub script), the default sprite and every constant a code entry passes to a draw_sprite
        function or stores in a variable named *sprite* (an array element or another instance's variable counts:
        the quiz sets its screen through another instance). An object placed in other rooms too is common machinery,
        whose art belongs to no one room: it is no seed and adds no art, though what it creates is followed when one
        of these creates it. A constant such an object stores in facechoice names the portrait its dialogue opens with
        (the chooser script creates it, out of this walk's sight): that object counts as created, and its poses array
        counts as art too. Sprite numbers only; the caller checks the range."""
        if not 0 <= room < len(self.insts_by_room):
            return set()
        if not hasattr(self, '_placed_rooms'):
            self._placed_rooms = {}
            for insts in self.insts_by_room:
                for o in {o for o, _cc in insts if o >= 0}:
                    self._placed_rooms[o] = self._placed_rooms.get(o, 0) + 1
        placed = self._placed_rooms
        seen = {o for o, _cc in self.insts_by_room[room] if o >= 0 and placed[o] == 1}
        q = deque(sorted(seen))
        out = set()
        faces = {t for objects in self.face_objects.values() for t in objects}
        while q:
            o = q.popleft()
            codes = [c for c in self.object_codes(o) if 0 <= c < len(self.spawns) and c not in self.hubs]
            for c in codes:
                for t in sorted(self._targets(c)):
                    if 0 <= t < len(self.events_by_obj) and t not in seen:
                        seen.add(t)
                        q.append(t)
            if placed.get(o, 0) > 1:
                continue
            if 0 <= o < len(self.sprite_by_obj):
                out.add(self.sprite_by_obj[o])
            for c in codes:
                out.update(self.draws[c])
                for name, values in self.any_stores[c].items():
                    if 'sprite' in name or (name == FACE_POSES and o in faces):
                        out.update(values)
                    if name == FACE_CHOICE:
                        for value in sorted(values):
                            for t in sorted(self.face_objects.get(value, ())):
                                if t not in seen:
                                    seen.add(t)
                                    q.append(t)
        return out

    def face_art_sprites(self, room):
        """The portraits a room's dialogue can open with, whoever places the object that opens it: from every object
        placed in this room, common machinery too, and what they create (the creation walk of placed_art_sprites,
        nothing followed out of a hub script), each constant stored in facechoice names a portrait (face_objects, the
        chooser's cases), which counts as created. Each portrait's default sprite, its draws and *sprite* stores and its
        poses array are the art; no other object's art is (placed_art_sprites keeps a common object's own art out).
        Toriel's chair object is placed in two houses and its talk opens her portrait: a dialogue's first frame
        read the portrait's tiles from the SD card in play (change tilemiss, the playtest o3DS 11-07, Azahar Old: three
        page-21 reads at the talk). A sign reader placed in many rooms brings every portrait its code names, not just
        the one its room shows: a few tiles more than needed. Sprite numbers only; the caller checks the range."""
        if not 0 <= room < len(self.insts_by_room) or not self.face_objects:
            return set()
        faces = {t for objects in self.face_objects.values() for t in objects}
        seen = {o for o, _cc in self.insts_by_room[room] if o >= 0}
        q = deque(sorted(seen))
        out = set()
        while q:
            o = q.popleft()
            codes = [c for c in self.object_codes(o) if 0 <= c < len(self.spawns) and c not in self.hubs]
            for c in codes:
                targets = set(self._targets(c))
                for value in self.any_stores[c].get(FACE_CHOICE, ()):
                    targets.update(self.face_objects.get(value, ()))
                for t in sorted(targets):
                    if 0 <= t < len(self.events_by_obj) and t not in seen:
                        seen.add(t)
                        q.append(t)
            if o not in faces:
                continue
            if 0 <= o < len(self.sprite_by_obj):
                out.add(self.sprite_by_obj[o])
            for c in codes:
                out.update(self.draws[c])
                for name, values in self.any_stores[c].items():
                    if 'sprite' in name or name == FACE_POSES:
                        out.update(values)
        return out

    def battle_objects(self, seeds):
        """The objects whose code battle_sounds would read for these seeds (the seeds' owners and what they create)."""
        return {self.owner[c] for c in sorted(seeds) + self.ordered(seeds) if c in self.owner}

    def battle_sounds(self, seeds, machinery=frozenset()):
        """The sounds a battle group's code can play, whether or not a recording heard them (change tilemiss, an Old 3DS
        playthrough 11-08: the sound record stopped 697 frames into Mettaton EX's fight, so the bombs, the heart's hits
        and its explosion were read or decoded in play): the seeds (the group's recorded code) and what they create (the
        creation walk of ordered, nothing followed out of a hub script), each constant passed as a SOUND_CALLS call's
        first argument, or stored by the object or its parents to the plain variable passed there instead. An object in
        machinery (the caller's: what most groups reach, such as the dialogue writer with every voice) is followed but
        adds no sounds, as placed_art_sprites treats common objects. In the seeds' order, then the walk's (Create chains
        first). Sound numbers only; the caller checks the range."""
        out, seen = [], set()
        for c in sorted(seeds) + self.ordered(seeds):
            if not 0 <= c < len(self.sounds) or c in self.hubs or self.owner.get(c) in machinery:
                continue
            found = set(self.sounds[c])
            if self.var_sounds[c]:
                o = self.owner.get(c)
                for cc in (self.object_codes(o) if o is not None else [c]):
                    if 0 <= cc < len(self.stores):
                        for name in self.var_sounds[c]:
                            found.update(self.stores[cc].get(name, ()))
            for k in sorted(found):
                if k not in seen:
                    seen.add(k)
                    out.append(k)
        return out

    def groups(self, codes):
        cg = self.code_group
        return {cg[c] for c in codes if 0 <= c < len(cg) and cg[c] is not None}

    def extras(self, room, plan_code, record_code, battle=False, cap=None):
        """The code indices to add to a scene (one for each group, in the closure's order) and their bytes. plan_code: the scene's
        planned code (dframe >= 0); record_code: every code the record saw (the room change's too); battle: a battle
        group's scene (its seeds are its own code, not the battle room's placed objects)."""
        have = self.change_codes(room) | set(plan_code) | set(record_code)
        staged = self.groups(have)
        seeds = set(plan_code) | set(record_code) if battle else have
        added, total, cap = [], 0, CAP_BYTES if cap is None else cap
        for c in self.ordered(seeds):
            grp = self.code_group[c] if 0 <= c < len(self.code_group) else None
            if grp is None or grp in staged:
                continue
            staged.add(grp)
            if total + self.group_size[grp] > cap:
                continue
            added.append(grp)
            total += self.group_size[grp]
        return [self.group_rep[grp] for grp in added], total


# Every instruction form the chooser may hold, as (op, t1, t2, variable kind, comparison): what Steam, GOG and Mac's
# scr_facechoice use, and nothing else. The walk below treats forms it doesn't model as no-ops, so the chooser read refuses
# them instead. Conversions: int to variable keeps the value; variable to int only as the very next instruction's
# instance (STACKTOP), so it never reaches a created object.
CHOOSER_FORMS = frozenset([
    (g.OP_ADD, g.T_INT32, g.T_VAR, None, None), (g.OP_SUB, g.T_INT32, g.T_VAR, None, None),
    (g.OP_B, 0, 0, None, None), (g.OP_BF, 0, 0, None, None), (g.OP_CALL, g.T_INT32, 0, None, None),
    (g.OP_CMP, g.T_INT32, g.T_VAR, None, CMP_EQUAL), (g.OP_CMP, g.T_STRING, g.T_VAR, None, CMP_EQUAL),
    (g.OP_CONV, g.T_INT32, g.T_VAR, None, None), (g.OP_CONV, g.T_VAR, g.T_INT32, None, None),
    (g.OP_POP, g.T_VAR, g.T_INT32, VARTYPE_STACKTOP, None), (g.OP_POP, g.T_VAR, g.T_VAR, VARTYPE_NORMAL, None),
    (g.OP_POPZ, g.T_VAR, 0, None, None), (g.OP_PUSH, g.T_STRING, 0, None, None),
    (g.OP_PUSH, g.T_VAR, 0, VARTYPE_STACKTOP, None), (g.OP_PUSH, g.T_VAR, 0, VARTYPE_NORMAL, None),
    (g.OP_PUSHGLB, g.T_VAR, 0, VARTYPE_NORMAL, None), (g.OP_PUSHLOC, g.T_VAR, 0, VARTYPE_NORMAL, None),
    (g.OP_PUSHI, g.T_INT16, 0, None, None)])


def chooser_form(ins):
    if ins.op in (g.OP_B, g.OP_BT, g.OP_BF):
        return (ins.op, 0, 0, None, None)   # a branch's offset fills the type bits
    named = ins.op in (g.OP_POP, g.OP_PUSH, g.OP_PUSHLOC, g.OP_PUSHGLB, g.OP_PUSHBLTN) and ins.t1 == g.T_VAR
    return (ins.op, ins.t1, ins.t2, (ins.extra >> 24) & 0xF8 if named and ins.extra is not None else None,
            (ins.word >> 8) & 0xFF if ins.op == g.OP_CMP else None)


CHOOSER_DEPTH = WALK_VISITS - 2   # each stack slot can merge to unknown once, so the walk never hits its visit cap


def chooser_stack(ins):
    """(pops, pushes) of a CHOOSER_FORMS instruction, as vm.c runs it."""
    vt = chooser_form(ins)[3]
    if ins.op in (g.OP_PUSHI, g.OP_PUSH, g.OP_PUSHGLB, g.OP_PUSHLOC):
        return (1, 1) if vt == VARTYPE_STACKTOP else (0, 1)
    if ins.op == g.OP_POP:
        return (2, 0) if vt == VARTYPE_STACKTOP else (1, 0)
    if ins.op == g.OP_CALL:
        return (ins.word & 0xFFFF, 1)
    return {g.OP_CONV: (1, 1), g.OP_ADD: (2, 1), g.OP_SUB: (2, 1), g.OP_CMP: (2, 1), g.OP_POPZ: (1, 0),
            g.OP_BF: (1, 0), g.OP_B: (0, 0)}[ins.op]


def chooser_case_paths(code, start, end, value):
    """Every way through one case lands on a decoded instruction or the case's end, only forward (no loops), with one
    stack depth wherever paths meet, never below the case's own start or above CHOOSER_DEPTH. Then the walk reads
    every reachable word as the instruction it is, merges paths slot by slot and stays under its visit cap."""
    starts = {ins.addr for ins in code if start <= ins.addr < end}
    into = {start: 0}
    for ins in code:
        if not start <= ins.addr < end or ins.addr not in into:
            continue   # not reached from the case's start: the walk doesn't read it either
        if ins.op in (g.OP_B, g.OP_BT, g.OP_BF):
            if not (ins.target() in starts or ins.target() == end) or ins.target() <= ins.addr:
                raise ValueError('the branch at %#x does not go forward to an instruction of case %d' % (ins.addr, value))
        pops, pushes = chooser_stack(ins)
        depth = into[ins.addr] - pops
        if depth < 0:
            raise ValueError('the stack runs out at %#x' % ins.addr)
        depth += pushes
        if depth > CHOOSER_DEPTH:
            raise ValueError('the stack is too deep at %#x' % ins.addr)
        arrivals = ([ins.target()] if ins.op in (g.OP_B, g.OP_BF) else []) + ([] if ins.op == g.OP_B else [ins.next])
        for at in arrivals:
            if at < end and into.setdefault(at, depth) != depth:   # the case's end is the next walk's start, at 0
                raise ValueError('paths meet at %#x with different stacks' % at)


def read_chooser(d, base, length, funcs, vars_):
    """(face_choices, None), or ({}, why) on anything at all going wrong: the build goes on without portraits."""
    try:
        return face_choices(d, base, length, funcs, vars_), None
    except Exception as e:
        return {}, 'the chooser script differs: %s' % e


def face_choices(d, base, length, funcs, vars_):
    """The chooser script as {value: objects}, or ValueError when it isn't exactly the shape this builder knows: the
    script is nothing but `if (facechoice == value)` cases, in instruction forms listed in CHOOSER_FORMS, with positive values, none seen twice, from its first byte
    to its last; each false branch goes to the next case (the last one's to the script's end) and no branch leaves its
    case; it calls only instance_create, and each case creates only constant objects, at least one. So each case is its
    own run of bytes, walked alone. A chooser that differs brings no portraits, not wrong ones."""
    blob = bytes(d[base:base + length])
    code, addr = [], 0
    while addr < length:
        try:
            ins = g.Instr(blob, addr)
        except g.Reject as e:
            raise ValueError(str(e))
        if ins.op == g.OP_CALL and not (ins.extra is not None and 0 <= ins.extra < len(funcs)
                                        and funcs[ins.extra] == FACE_CREATES):
            raise ValueError('it calls something other than %s at %#x' % (FACE_CREATES, addr))
        code.append(ins)
        addr = ins.next
    tests = []
    for i, ins in enumerate(code):
        named = ins.op == g.OP_POP or (ins.op in (g.OP_PUSH, g.OP_PUSHLOC, g.OP_PUSHGLB, g.OP_PUSHBLTN) and ins.t1 == g.T_VAR)
        if not named:
            continue
        if ins.extra is None:
            raise ValueError('the variable operation at %#x has no variable' % ins.addr)
        if not 0 <= ins.var_index() < len(vars_) or vars_[ins.var_index()] != FACE_CHOICE:
            continue
        rest = code[i + 1:i + 4]
        if (ins.op != g.OP_PUSHGLB or len(rest) < 3 or rest[0].op != g.OP_PUSHI or rest[1].op != g.OP_CMP
                or (rest[1].word >> 8) & 0xFF != CMP_EQUAL or rest[2].op != g.OP_BF or rest[0].inst <= 0):
            raise ValueError('a use of %s at %#x is not an equality test with its false branch' % (FACE_CHOICE, ins.addr))
        tests.append((ins.addr, rest[0].inst, rest[2]))
    if not tests:
        raise ValueError('it tests no %s' % FACE_CHOICE)
    if tests[0][0] != 0:
        raise ValueError('code runs before the first case')
    for i, ins in enumerate(code):
        if chooser_form(ins) not in CHOOSER_FORMS:
            raise ValueError('the instruction at %#x is a form this builder does not model' % ins.addr)
        if (ins.op, ins.t1, ins.t2) == (g.OP_CONV, g.T_VAR, g.T_INT32):
            following = code[i + 1] if i + 1 < len(code) else None
            if following is None or chooser_form(following)[3] != VARTYPE_STACKTOP:
                raise ValueError('the conversion at %#x is not an instance for the next instruction' % ins.addr)
    out = {}
    for i, (start, value, branch) in enumerate(tests):
        end = length if i + 1 == len(tests) else tests[i + 1][0]
        if branch.target() != end:
            raise ValueError('the false branch of case %d does not go to the next case' % value)
        if value in out:
            raise ValueError('case %d comes twice' % value)
        for ins in code:
            if start <= ins.addr < end and ins.op in (g.OP_B, g.OP_BT, g.OP_BF) and not start <= ins.target() <= end:
                raise ValueError('a branch at %#x leaves case %d' % (ins.addr, value))
        chooser_case_paths(code, start, end, value)
        got = walk(d, base + start, end - start, funcs, vars_)
        if not got['spawns'] or got['var_spawns'] or got['computed_spawns']:
            raise ValueError('case %d does not create only constant objects' % value)
        if not all(0 <= o <= 0x7FFFFFFF for o in got['spawns']):
            # The walk adds without int32 wrapping (vm_fastpath.h wraps), and a negative number would index from the end.
            raise ValueError('case %d creates an object number outside 0 to int32' % value)
        out[value] = got['spawns']
    return out


def walk(d, base, length, funcs, vars_, sound_calls=frozenset()):
    """Abstract stack walk over one code entry: the objects its instance_create / instance_create_depth /
    instance_change calls name as constants (spawns), the variables they name instead (var_spawns), whether any names
    neither (computed_spawns), the constants each plain variable is assigned (stores), the same for a variable of any kind (any_stores) and the constants passed
    as a draw_sprite function's sprite (draws), and the constants (sounds) or plain variables (var_sounds) passed as a
    sound_calls call's sound. A stack slot is ('c', frozenset of ints), ('v', name), ('a', k) or None."""
    blob = bytes(d[base:base + length])
    states = {0: ()}
    work = [0]
    out = {'spawns': set(), 'var_spawns': set(), 'computed_spawns': False, 'stores': {}, 'any_stores': {}, 'draws': set(),
           'sounds': set(), 'var_sounds': set()}
    visits = {}

    def pops(n, stack):
        for _ in range(n):
            if stack:
                stack.pop()

    while work:
        addr = work.pop()
        stack = list(states[addr])
        visits[addr] = visits.get(addr, 0) + 1
        if visits[addr] > WALK_VISITS:
            continue
        while addr + 4 <= length:
            try:
                ins = g.Instr(blob, addr)
            except g.Reject:
                break
            op, branch, stop = ins.op, None, False
            if op in (g.OP_NEG, g.OP_NOT):
                if stack:
                    top = stack.pop()
                    stack.append(('c', frozenset(-x for x in top[1])) if op == g.OP_NEG and top and top[0] == 'c'
                                 else None)
            elif op in (g.OP_MUL, g.OP_DIV, g.OP_REM, g.OP_MOD, g.OP_ADD, g.OP_SUB, g.OP_AND, g.OP_OR, g.OP_XOR,
                        g.OP_SHL, g.OP_SHR, g.OP_CMP):
                b = stack.pop() if stack else None
                a = stack.pop() if stack else None
                v = None
                if a and b and a[0] == 'c' and b[0] == 'c' and len(a[1]) * len(b[1]) <= 16 and op in (g.OP_ADD, g.OP_SUB):
                    v = ('c', frozenset((x + y) if op == g.OP_ADD else (x - y) for x in a[1] for y in b[1]))
                stack.append(v)
            elif op == g.OP_POP:
                # vm.c handlePop: a simple (pop.v.v) array or stacktop store has its value deepest, the index and
                # instance on top; a compound one has the value on top.
                vt = (ins.extra >> 24) & 0xF8 if ins.extra is not None else VARTYPE_NORMAL
                under = 2 if vt == VARTYPE_ARRAY else 1 if vt == VARTYPE_STACKTOP else 0
                if under and ins.t1 == g.T_VAR:
                    pops(under, stack)
                    val = stack.pop() if stack else None
                else:
                    val = stack.pop() if stack else None
                    pops(under, stack)
                if ins.extra is not None:
                    vi = ins.var_index()
                    name = vars_[vi] if 0 <= vi < len(vars_) else None
                    if name is not None and val and val[0] == 'c':
                        out['any_stores'].setdefault(name, set()).update(val[1])
                        # Only a plain variable's stores are its constants (not an array element's, not another
                        # instance's): what the creation walk may read back as an object.
                        if vt == VARTYPE_NORMAL:
                            out['stores'].setdefault(name, set()).update(val[1])
            elif op == g.OP_PUSHI:
                stack.append(('c', frozenset([ins.inst])))
            elif op == g.OP_DUP:
                n = (ins.word & 0xFF) + 1
                stack.extend(stack[-n:] if len(stack) >= n else [None] * n)
            elif op == g.OP_RET:
                pops(1, stack)
                stop = True
            elif op == g.OP_EXIT:
                stop = True
            elif op == g.OP_POPZ:
                pops(1, stack)
            elif op == g.OP_B:
                branch, stop = ins.target(), True
            elif op in (g.OP_BT, g.OP_BF):
                pops(1, stack)
                branch = ins.target()
            elif op == g.OP_PUSHENV:
                pops(1, stack)   # its operand jumps to the popenv of an empty with: fall through
            elif op in (g.OP_PUSH, g.OP_PUSHLOC, g.OP_PUSHGLB, g.OP_PUSHBLTN):
                if ins.t1 == g.T_VAR:
                    vt = (ins.extra >> 24) & 0xF8
                    pops(2 if vt == 0x00 else 1 if vt == 0x80 else 0, stack)
                    vi = ins.var_index()
                    name = vars_[vi] if 0 <= vi < len(vars_) else None
                    if vt == 0x00:
                        stack.append(None)
                    elif name and name.startswith('argument') and name[8:].isdigit():
                        stack.append(('a', int(name[8:])))
                    else:
                        stack.append(('v', name))
                elif ins.t1 == g.T_INT16:
                    stack.append(('c', frozenset([ins.inst])))
                elif ins.t1 == g.T_INT32 and ins.extra is not None:
                    stack.append(('c', frozenset([ins.extra - (1 << 32) if ins.extra >= 1 << 31 else ins.extra])))
                elif ins.t1 == g.T_DOUBLE:
                    dv = struct.unpack_from('<d', blob, addr + 4)[0]
                    stack.append(('c', frozenset([int(dv)])) if dv == int(dv) and abs(dv) < 1e9 else None)
                else:
                    stack.append(None)
            elif op == g.OP_CALL:
                argc = ins.word & 0xFFFF
                fi = ins.extra
                name = funcs[fi] if fi is not None and 0 <= fi < len(funcs) else None
                args = [stack[-(k + 1)] if len(stack) > k else None for k in range(argc)]
                del stack[max(0, len(stack) - argc):]
                stack.append(None)
                if name in DRAW_FUNCTIONS and argc > 0 and args[0] and args[0][0] == 'c':
                    out['draws'].update(args[0][1])
                if name in sound_calls and argc > 0 and args[0]:
                    if args[0][0] == 'c':
                        out['sounds'].update(args[0][1])
                    elif args[0][0] == 'v':
                        out['var_sounds'].add(args[0][1])
                k = SPAWN_ARG.get(name)
                if k is not None:
                    kind = args[k][0] if argc > k and args[k] else None
                    if kind == 'c':
                        out['spawns'].update(args[k][1])
                    elif kind == 'v':
                        out['var_spawns'].add(args[k][1])
                    else:
                        out['computed_spawns'] = True
            if branch is not None and 0 <= branch < length:
                st = tuple(stack)
                prev = states.get(branch)
                if prev is None:
                    states[branch] = st
                    work.append(branch)
                elif prev != st and len(prev) == len(st):
                    merged = tuple(p if p == s else None for p, s in zip(prev, st))
                    if merged != prev:
                        states[branch] = merged
                        work.append(branch)
            if stop:
                break
            addr = ins.next
            st = tuple(stack)
            prev = states.get(addr)
            if prev is not None:
                if prev == st or len(prev) != len(st):
                    break
                merged = tuple(p if p == s else None for p, s in zip(prev, st))
                if merged == prev:
                    break
                states[addr] = merged
                stack = list(merged)
            else:
                states[addr] = st
    return out
