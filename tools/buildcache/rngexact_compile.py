"""Retain four original RNG entry slots while branching to the late correction.

Compile the original release bodies unchanged so GCC's graph, canonical string
pool and section ordering stay frozen. UT reuses the canonical assembly from
the existing colexact pass. DR does the same when auditfixg's DR pool adapter
(colexact_compile.py) is in the chain, since it accepts only the -c compile
(sonrev3 R227-1); without one, DR emits assembly through the ordinary delegate.
Only the four bounded bodies change. Labels and reference words are retained
in their unreachable padding. The whole-image layout gate remains mandatory.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--rngexact-compiler'
SLOTS = dict(random=244, random_range=292, irandom=244, irandom_range=300)


def rewrite(text):
    receipt = {}
    for name, size in SLOTS.items():
        symbol = 'builtin_' + name
        pattern = re.compile(r'(?ms)^' + symbol + r':\n.*?^[ \t]*\.size[ \t]+' + symbol + r',[ \t]*\.-' + symbol + r'[ \t]*$')
        matches = list(pattern.finditer(text))
        assert len(matches) == 1, ('missing/duplicate RNG entry', symbol)
        match = matches[0]
        body = match[0]
        assert not re.search(r'(?m)^\s*\.(?:pushsection|section)\b', body), ('nested RNG section', symbol)
        labels = re.findall(r'(?m)^(\.L[\w.]+):[^\n]*$', body)
        assert len(labels) == len(set(labels)), ('duplicate local label', symbol)
        views = sorted(set(re.findall(r'\bview\s+(\.LVU\w+)', body)))
        words = re.findall(r'(?m)^\s*\.word\s+([^\n@]+)', body)
        # Keep relocation edges from the former literal pool. All references
        # into this tail are DWARF or the removed body, never live instructions.
        replacement = symbol + ':\n\tb RNGExact_' + name + '\n'
        replacement += ''.join(label + ':\n' for label in labels)
        replacement += ''.join('.set ' + view + ', 0\n' for view in views)
        replacement += ''.join('\t.word ' + word.strip() + '\n' for word in words)
        replacement += '\t.space ' + str(size) + '-(.-' + symbol + '), 0\n'
        replacement += '\t.size ' + symbol + ', .-' + symbol
        text = text[:match.start()] + replacement + text[match.end():]
        receipt[symbol] = dict(bytes=size, branch='RNGExact_' + name,
            original_sha256=hashlib.sha256(body.encode()).hexdigest(),
            retained_labels=len(labels), retained_words=len(words))
    return text, receipt


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split+1:]
    sources = [a for a in command if a.replace('\\', '/').endswith('/vm_builtins.c')]
    release = '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT' in command
    if len(sources) != 1 or not release:
        # Target-wide launcher: only a builtin compile can lose the RNG fix.
        if sources:
            print('RNG entry adapter: delegated without rewrite '
                  '(release_define=%s, vm_builtins_sources=%d)' % (release, len(sources)),
                  file=sys.stderr, flush=True)
        return run(delegate + command)
    assert '-c' in command and command.count('-o') == 1
    source = sources[0]
    output = Path(command[command.index('-o') + 1])
    colexact = sum(a.endswith('/colexact_compile.py') for a in delegate)
    if '-DENABLE_WAD16' in command:
        assert colexact == 1
    else:
        assert '-DENABLE_WAD17' in command and colexact <= 1
    if colexact:
        # The pool adapter compiles -c itself and leaves its restored assembly beside the object.
        original = output.with_name('colexact1.s')
        original.unlink(missing_ok=True)
        status = run(delegate + command)
        if status:
            return status
        assert original.is_file(), 'colexact did not emit canonical assembly'
    else:
        original = output.with_name('rng0.s')
        emit = list(command)
        emit[emit.index('-c')] = '-S'
        emit[emit.index('-o') + 1] = str(original)
        status = run(delegate + emit)
        if status:
            return status
    before = original.read_text(encoding='utf-8')
    text, entries = rewrite(before)
    patched = output.with_name('rng1.s')
    with open(patched, 'w', encoding='utf-8', newline='\n') as handle:  # write_text(newline=) needs Python 3.10
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
    receipt = dict(exit=status, entries=entries, source=source,
        original_sha256=hashlib.sha256(before.encode()).hexdigest(),
        patched_sha256=hashlib.sha256(text.encode()).hexdigest())
    output.with_name('rngexact.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('RNG retained entries: ' + json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
