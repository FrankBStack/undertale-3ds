"""Route legacy background dispatch without changing frozen compiler bodies.

The builtin pass composes after the RNG/canonical-pool adapters. Only call
operands change; runner gains two new late branch bridges. Unknown call
counts and callers fail closed. Full ELF layout is a separate required gate.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--gmlstubs-compiler'
CONDITION = r'(?:eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le|al)?'


def rewrite(text, source, release=True):
    before = text
    if source == 'vm_builtins.c':
        routes = [('bsearch', 'Gmlstubs_varSearch', 2),
                  ('VMBuiltins_getVariable', '__wrap_VMBuiltins_getVariable', 2),
                  ('VMBuiltins_setVariable', '__wrap_VMBuiltins_setVariable', 1)]
    else:
        assert source == 'runner.c'
        routes = [('drawGMS1Backgrounds', 'Gmlstubs_drawLegacy', 4),
                  ('initRoom', 'Gmlstubs_initRoom', 3)]
    counts = {}
    for old, new, expected in routes:
        pattern = re.compile(r'^([ \t]+b(?:l)?' + CONDITION + r'[ \t]+)'
            + old + r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$', re.M)
        matches = list(pattern.finditer(text))
        if old == 'bsearch' and not release:
            assert len(matches) in (1, 2), ('unexpected non-release lookup count', len(matches))
        elif source == 'runner.c' and not release:
            # The Release-only legacy room renderer contributes two draws
            # and one room initializer; development builds use the main path.
            allowed = (2, 4) if old == 'drawGMS1Backgrounds' else (2, 3)
            assert len(matches) in allowed, ('unexpected development caller count', old, len(matches))
        else:
            assert len(matches) == expected, ('unexpected caller count', source, old, len(matches), expected)
        if old == 'bsearch':
            callers = {list(re.finditer(r'^([A-Za-z_][\w.]*):$', text[:m.start()], re.M))[-1][1]
                       for m in matches}
            wanted = {'resolveNamedVar', 'VMBuiltins_resolveBuiltinVarId'}
            assert callers == wanted or (not release and callers == {'VMBuiltins_resolveBuiltinVarId'}), callers
        text = pattern.sub(lambda m: m[1] + new + (m[2] or '') + m[3], text)
        counts[old] = len(matches)
    restored = text
    for old, new, _ in routes:
        restored = restored.replace(new, old)
    assert restored == before, 'non-call assembly changed'
    if source == 'runner.c':
        for target, bridge in [('drawBackground', 'Gmlstubs_drawBackgroundOriginal'),
                               ('initRoom', 'Gmlstubs_initRoomOriginal')]:
            assert len(re.findall(r'^' + target + r':$', before, re.M)) == 1, target
            assert bridge not in before, 'duplicate bridge'
            text += ('\n.pushsection .gmlstubs_bridge,"ax",%progbits\n.balign 4\n'
                     '.global ' + bridge + '\n.type ' + bridge + ', %function\n'
                     + bridge + ':\n b ' + target + '\n.size ' + bridge + ', .-' + bridge + '\n.popsection\n')
        # All former callers now use the tint-aware helper. A relocation in
        # the live bridge section retains the original warm body under GC.
        assert len(re.findall(r'^drawGMS1Backgrounds:$', before, re.M)) == 1
        text += ('\n.pushsection .gmlstubs_bridge,"ax",%progbits\n.balign 4\n'
                 '.word drawGMS1Backgrounds\n.popsection\n')
    return text, dict(calls=counts, before_sha256=hashlib.sha256(before.encode()).hexdigest(),
                      after_sha256=hashlib.sha256(text.encode()).hexdigest())


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split+1:]
    sources = [a for a in command if Path(a.replace('\\', '/')).name in ('runner.c', 'vm_builtins.c')]
    if len(sources) != 1 or '-DENABLE_WAD16' not in command:
        return run(delegate + command)
    assert '-c' in command and command.count('-o') == 1
    source = sources[0]
    output = Path(command[command.index('-o') + 1])
    name = Path(source.replace('\\', '/')).name
    release = '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT' in command
    if name == 'vm_builtins.c' and release:
        # Preserve every existing canonical-pool and retained-RNG operation.
        original = output.with_name('rng1.s')
        original.unlink(missing_ok=True)
        status = run(delegate + command)
        if status:
            return status
        assert original.is_file(), 'RNG delegate did not emit final assembly'
    else:
        original = output.with_name(output.stem + '_gml0.s')
        emit = list(command)
        emit[emit.index('-c')] = '-S'
        emit[emit.index('-o') + 1] = str(original)
        status = run(delegate + emit)
        if status:
            return status
    text, receipt = rewrite(original.read_text(encoding='utf-8'), name, release=release)
    patched = output.with_name(output.stem + '_gml1.s')
    with patched.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(text)
    assemble, index = [command[0]], 1
    while index < len(command):
        arg = command[index]
        if arg in ('-MF', '-MT', '-MQ', '-o'):
            index += 2
            continue
        if arg not in ('-MD', '-MMD', '-MP', '-c') and arg != source:
            assemble.append(arg)
        index += 1
    status = run(assemble + ['-Wa,--fatal-warnings', '-x', 'assembler', '-c', str(patched), '-o', str(output)])
    receipt.update(exit=status, source=source)
    output.with_name(output.stem + '_gmlstubs.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('Legacy background dispatch: ' + json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
