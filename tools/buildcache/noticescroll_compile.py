"""Preserve legalui's call graph and slots; route its three clear calls to the late bulk clear.

UNDERTALE only. The original local clone takes PrintConsole* and preserves r1;
the replacement's bridge keeps that extra preservation. Unknown ABIs fail closed.
"""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

MARKER = '--noticescroll-compiler'
TARGET = 'CtrNoticescroll_clear'


def check_clone(body):
    """Accept only understood leaf instructions; r1 is read-only, r2/r3/ip are clobbered.

    Rejecting unknown instructions is deliberate: this is an ABI guard, not an ARM disassembler.
    In particular calls, multi-register loads/ranges and hidden writebacks must not evade the r1 check.
    """
    conditions = ('', 'eq', 'ne', 'cs', 'cc', 'hs', 'lo', 'mi', 'pl', 'vs', 'vc', 'hi', 'ls', 'ge', 'lt', 'gt', 'le', 'al')
    destinations = {'mov', 'mvn', 'add', 'sub', 'rsb', 'adc', 'sbc', 'rsc', 'and', 'orr', 'eor', 'bic',
                    'clz', 'lsl', 'lsr', 'asr', 'ror', 'rrx', 'mul', 'mla', 'ldr', 'ldrb', 'ldrh', 'ldrsb', 'ldrsh'}
    readonly = {'cmp', 'cmn', 'tst', 'teq', 'str', 'strb', 'strh', 'push', 'pop', 'b', 'bx', 'nop'}
    forms = {base + suffix + cond: base for base in destinations | readonly
             for cond in conditions for suffix in (('', 's') if base in destinations - {'ldr', 'ldrb', 'ldrh', 'ldrsb', 'ldrsh'} else ('',))}
    aliases = {'a1': 'r0', 'a2': 'r1', 'a3': 'r2', 'a4': 'r3', 'ip': 'r12'}
    labels = set(re.findall(r'(?m)^(\.L[\w.]+):', body))
    written = set()
    for line in body.splitlines():
        line = line.split('@', 1)[0].strip()
        if not line or line.startswith('.') or line.endswith(':'):
            continue
        parts = line.split(None, 1)
        op, operands = parts[0], parts[1] if len(parts) > 1 else ''
        assert op in forms, ('unknown clear instruction or call', line)
        base = forms[op]
        operands = re.sub(r'\b(a[1-4]|ip)\b', lambda m: aliases[m[0]], operands)
        # Only compares/tests may mention r1. This conservative rule covers destination operands,
        # register lists, post/pre-index writeback, shifts, multiplies and aliases without guessing.
        assert not re.search(r'\br1\b', operands) or base in {'cmp', 'cmn', 'tst', 'teq'}, \
            ('original no longer preserves r1', line)
        if base in {'push', 'pop'}:
            assert re.fullmatch(r'\{(?:r(?:[0-9]|1[0-2])|lr|pc)(?:,\s*(?:r(?:[0-9]|1[0-2])|lr|pc))*\}', operands), \
                ('unknown register list', line)
        if base == 'b':
            assert operands in labels, ('clear branches outside its body', line)
        if base == 'bx':
            assert operands == 'lr', ('unknown clear return', line)
        if base in destinations:
            dest = operands.split(',', 1)[0]
            assert re.fullmatch(r'r(?:[0-9]|1[0-2])|lr|pc|sp', dest), ('unknown destination', line)
            assert dest != 'pc', ('unknown clear control transfer', line)
            written.add(dest)
    # The bridge promises r1 only. The frozen clone already writes all three other AAPCS scratch registers;
    # if a compiler starts preserving one, callers may rely on it and need a new bridge/caller review.
    assert {'r2', 'r3', 'r12'} <= written, ('clear scratch-register contract changed', sorted(written))


def rewrite(text, allow_missing=False):
    before = text
    names = re.findall(r'(?m)^(luiClear\.isra\.\d+):$', text)
    if not names and allow_missing:
        return text, dict(calls=0, reason='unoptimized build without the private clone')
    assert len(names) == 1, ('clear clone ABI changed', names)
    name = names[0]
    start = text.index(name + ':')
    end = text.index('\n\t.size\t' + name + ',', start)
    body = text[start:end]
    # GCC replaced CtrMenu* with menu->console (PrintConsole*): offset 8 is its framebuffer.
    assert re.search(r'(?m)^\s*ldr\s+r0,\s*\[r0,\s*#8\]', body), 'clear first argument changed'
    check_clone(body)
    pattern = re.compile(r'(?m)^(\s*bl\s+)' + re.escape(name) + r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
    matches = list(pattern.finditer(text))
    assert len(matches) == 3, ('clear call count', len(matches))
    callers = []
    for match in matches:
        labels = re.findall(r'(?m)^([A-Za-z_][\w.]*)\:$', text[:match.start()])
        assert labels, 'missing clear caller'
        callers.append(labels[-1])
    expected = ('luiDrawHub', 'luiDrawDoc', 'luiDrawCredits')
    assert sorted(re.sub(r'\.isra\.\d+$', '', n) for n in callers) == sorted(expected), callers
    text = pattern.sub(lambda m: m[1] + TARGET + (m[2] or '') + m[3], text)
    reverse = re.compile(r'(?m)^(\s*bl\s+)' + TARGET + r'(\(PLT\))?([ \t]*(?:@[^\n]*)?)$')
    assert reverse.sub(lambda m: m[1] + name + (m[2] or '') + m[3], text) == before, 'non-call assembly changed'
    return text, dict(calls=3, callers=callers, old=name, new=TARGET,
                      before_sha256=hashlib.sha256(before.encode()).hexdigest(),
                      after_sha256=hashlib.sha256(text.encode()).hexdigest())


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split + 1:]
    sources = [a for a in command if a.replace('\\', '/').endswith('/ctr_legal.c')]
    if not sources or '-DENABLE_WAD16' not in command or '-DENABLE_WAD17' in command:
        return run(delegate + command)
    assert len(sources) == 1 and '-c' in command and command.count('-o') == 1
    source = sources[0]
    output = Path(command[command.index('-o') + 1])
    original, patched = output.with_name('noticescroll0.s'), output.with_name('noticescroll1.s')
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o') + 1] = str(original)
    result = run(delegate + emit)
    if result:
        return result
    optimization = next((a for a in reversed(command) if re.fullmatch(r'-O(?:[0-3sgz]|fast)', a)), None)
    text, receipt = rewrite(original.read_text(encoding='utf-8'), allow_missing=optimization in (None, '-O0', '-O1', '-Og'))
    if receipt['calls'] == 0:
        # Preserve the normal compiler's debug/object emission when there is no private ABI to replace.
        return run(delegate + command)
    with open(patched, 'w', encoding='utf-8', newline='\n') as handle:
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
    result = run(assemble)
    receipt.update(exit=result, source=source)
    output.with_name('noticescroll-routing.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Noticescroll clear calls: ' + json.dumps(receipt), flush=True)
    return result


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
