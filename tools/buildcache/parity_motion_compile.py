"""Compile the qualified UT forward-motion body inside its original 248 B slot.

Compile the ordinary instance TU unchanged, then graft a separately compiled C
body into exactly one function. No per-frame late call, TU graph change, or data
movement. Overflow fails at assembly; the independent whole-ELF verifier checks
all existing functions, data and the retained tail against an explicit base.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from parity_motion_verify import Elf, normalized_body

MARKER = '--parity-motion-compiler'
SYMBOL = 'Instance_computeComponentsFromSpeed'
SLOT = 248
BODY = Path(__file__).resolve().parents[2] / 'engine/src/parity_motion_body.inc'


def function(text):
    hits = list(re.finditer(r'(?ms)^' + SYMBOL + r':\n.*?^[ \t]*\.size[ \t]+' +
                           SYMBOL + r',[^\n]*$', text))
    assert len(hits) == 1, ('Missing/duplicate motion body', len(hits))
    body = hits[0][0]
    assert not re.search(r'(?m)^\s*\.(?:pushsection|section)\b', body), 'Nested motion section'
    return hits[0]


def rewrite(original, compiled):
    old, new = function(original), function(compiled)
    # An old relocation in a discarded pool could change linker reachability.
    # The frozen forward helper has numeric pool words only; fail closed.
    words = re.findall(r'(?m)^\s*\.word\s+([^\n@]+)', old[0])
    assert words and all(re.fullmatch(r'[+-]?\d+\s*', word) for word in words), 'Non-numeric old pool'
    labels = re.findall(r'(?m)^(\.L[\w.]+):[^\n]*$', old[0])
    assert len(labels) == len(set(labels)), 'Duplicate old motion labels'
    views = sorted(set(re.findall(r'\bview\s+(\.LVU\w+)', old[0])))
    # Do not borrow this tiny TU's DWARF file table. Its code/local labels are
    # namespaced; original debug-only labels remain in the unreachable tail.
    lines = [line for line in new[0].splitlines()[1:]
             if not re.match(r'\s*\.(?:loc|file|size)\b', line)]
    body = re.sub(r'\.L([\w.]+)', r'.LPM_\1', '\n'.join(lines)) + '\n'
    replacement = SYMBOL + ':\n' + body
    replacement += ''.join(label + ':\n' for label in labels)
    replacement += ''.join('.set ' + view + ', 0\n' for view in views)
    # Unlike negative .space (which GAS can merely warn about), moving .org
    # backwards is an assembly error if the replacement outgrows this slot.
    replacement += '\t.org ' + SYMBOL + '+' + str(SLOT) + ', 0\n'
    replacement += '\t.size ' + SYMBOL + ', .-' + SYMBOL
    patched = original[:old.start()] + replacement + original[old.end():]
    receipt = dict(symbol=SYMBOL, slot_bytes=SLOT,
                   original_body_sha256=hashlib.sha256(old[0].encode()).hexdigest(),
                   replacement_body_sha256=hashlib.sha256(new[0].encode()).hexdigest(),
                   original_debug_labels_retained=len(labels), no_late_call=True)
    return patched, receipt


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [arg for arg in args[:split] if arg], args[split+1:]
    sources = [arg for arg in command if arg.replace('\\', '/').split('/')[-1] == 'instance.c']
    required = ('-DENABLE_WAD16', '-DPLATFORM_3DS', '-O2', '-DNDEBUG')
    if not sources:
        return run(delegate + command)
    assert len(sources) == 1, 'Motion adapter requires exactly one instance.c input'
    if command.count('-o') == 1:
        Path(command[command.index('-o')+1]).with_name('pm.json').unlink(missing_ok=True)
    missing = [arg for arg in required if arg not in command]
    assert not missing, ('Unsupported UT instance.c flags; refusing old motion arithmetic', missing)
    assert [arg for arg in command if re.fullmatch(r'-O(?:[0-3sgz]|fast)', arg)] == ['-O2'], 'Motion adapter requires only -O2'
    assert not set(command) & {'-UENABLE_WAD16', '-UPLATFORM_3DS', '-UNDEBUG', '-DENABLE_WAD17'}, 'Conflicting UT motion flags'
    assert '-c' in command and command.count('-o') == 1 and '-DUSE_FLOAT_REALS' not in command
    source = sources[0]
    output = Path(command[command.index('-o')+1])
    original, compiled, patched = [output.with_name(name) for name in ('pm0.s', 'pmb.s', 'pm1.s')]
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o')+1] = str(original)
    status = run(delegate + emit)
    if status:
        return status
    common, index = [command[0]], 1
    while index < len(command):
        arg = command[index]
        if arg in ('-MF', '-MT', '-MQ', '-o'):
            index += 2
            continue
        if arg not in ('-MD', '-MMD', '-MP', '-c') and arg != source:
            common.append(arg)
        index += 1
    status = run(common + ['-g0', '-x', 'c', '-S', str(BODY), '-o', str(compiled)])
    if status:
        return status
    before = original.read_text(encoding='utf-8')
    text, receipt = rewrite(before, compiled.read_text(encoding='utf-8'))
    with patched.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    status = run(common + ['-x', 'assembler', '-c', str(patched), '-o', str(output)])
    if status:
        return status
    _, object_code = Elf(output).function(SYMBOL)
    receipt.update(schema=2, exit=status, source=source, c_body_sha256=hashlib.sha256(BODY.read_bytes()).hexdigest(),
                   adapter_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                   object_file=output.name, object_sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                   normalized_body_sha256=normalized_body(object_code),
                   original_sha256=hashlib.sha256(before.encode()).hexdigest(),
                   patched_sha256=hashlib.sha256(text.encode()).hexdigest())
    output.with_name('pm.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print('PARITY retained motion body: ' + json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    raise SystemExit(main(sys.argv[1:]))
