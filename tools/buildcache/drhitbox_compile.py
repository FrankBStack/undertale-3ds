"""Redirect two DR rectangle calls and append a retained-bbox bridge.

The source TUs and GCC's call graph are unchanged. Exactly two call operands
change in collision_compat.c; runner.c gains only a new late 4-byte branch.
Unknown call counts or bbox symbols fail closed. Full ELF layout is a separate
required gate. UNDERTALE's CMake target never installs this adapter.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--drhitbox-compiler'
SOURCE_NAMES = ('collision_compat.c', 'runner.c')
OLD = 'Collision_compatRectHitsInstance'
NEW = 'DrHitbox_rectHits'


def rewrite(text, source):
    before = text
    if source == 'collision_compat.c':
        pattern = re.compile(r'^(\s*bl\s+)' + OLD + r'(\(PLT\))?([ \t]*)$', re.M)
        matches = list(pattern.finditer(text))
        assert len(matches) == 2, ('rectangle call count', len(matches))
        # Each call must be inside its expected original builtin body.
        expected = {'builtin_collision_rectangle_compat', 'builtin_collision_rectangle_list_compat'}
        callers = set()
        for match in matches:
            starts = list(re.finditer(r'^([A-Za-z_][\w.]*)\:\s*$', text[:match.start()], re.M))
            assert starts, 'missing caller'
            callers.add(starts[-1][1])
        assert callers == expected, ('unexpected rectangle callers', callers)
        text = pattern.sub(lambda m: m[1] + NEW + (m[2] or '') + m[3], text)
        assert text.replace(NEW, OLD) == before, 'non-call text changed'
        info = dict(redirected_calls=2, callers=sorted(callers))
    else:
        assert source == 'runner.c', source
        assert len(re.findall(r'^Collision_computeBBox:\s*$', text, re.M)) == 1, 'missing retained bbox body'
        assert 'DrHitbox_sharedBBox' not in text, 'duplicate bridge'
        text += ('\n.pushsection .text.late.drhitbox_bridge,"ax",%progbits\n'
                 '.balign 4\n.global DrHitbox_sharedBBox\n'
                 '.type DrHitbox_sharedBBox, %function\n'
                 'DrHitbox_sharedBBox:\n b Collision_computeBBox\n'
                 '.size DrHitbox_sharedBBox, .-DrHitbox_sharedBBox\n.popsection\n')
        assert text.startswith(before), 'existing runner assembly changed'
        info = dict(bridge_bytes=4, target='Collision_computeBBox')
    info.update(before_sha256=hashlib.sha256(before.encode()).hexdigest(),
                after_sha256=hashlib.sha256(text.encode()).hexdigest())
    return text, info


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split + 1:]
    sources = [a for a in command if Path(a.replace('\\', '/')).name in SOURCE_NAMES]
    if len(sources) != 1 or '-DENABLE_WAD17' not in command or '-DENABLE_WAD16' in command:
        return run(delegate + command)
    source = sources[0]
    assert '-c' in command and command.count('-o') == 1
    output = Path(command[command.index('-o') + 1])
    # Both TUs share an object directory and can compile concurrently.
    tag = 'drhbr' if Path(source.replace('\\', '/')).name == 'runner.c' else 'drhbc'
    original, patched = output.with_name(tag+'0.s'), output.with_name(tag+'1.s')
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o') + 1] = str(original)
    status = run(delegate + emit)
    if status:
        return status
    text, receipt = rewrite(original.read_text(encoding='utf-8'), Path(source.replace('\\', '/')).name)
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
    assemble += ['-x', 'assembler', '-c', str(patched), '-o', str(output)]
    status = run(assemble)
    receipt.update(exit=status, source=source)
    output.with_name(tag+'.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('DR hitbox redirect: ' + json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
