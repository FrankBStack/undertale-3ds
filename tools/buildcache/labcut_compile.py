"""Retain stage75w's two cold exit slots; append unreachable zero bytes only.

The GCC Release extents are identical on all four targets. Instruction selection
comes entirely from the C sources. GAS rejects a growing slot as a fatal warning;
the independent full layout gate must still prove every frozen symbol unchanged.
"""
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--labcut-compiler'
SLOTS = {'ctr_exit_log.c': ('CtrExit_closeLog', 164),
         'ctr_exit_midfile.c': ('CtrExitFiles_shutdownDrained', 296)}


def retain(text, name, size):
    pattern = r'(?m)^[ \t]*\.size[ \t]+' + name + r',[ \t]*\.-' + name + r'[ \t]*$'
    replacement = f'\t.space {size} - (. - {name}), 0\n\t.size {name}, .-{name}'
    text, count = re.subn(pattern, lambda _: replacement, text)
    assert count == 1, ('Missing/duplicate labcut slot', name, count)
    return text


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split+1:]
    sources = [a for a in command if a.replace('\\', '/').rsplit('/', 1)[-1] in SLOTS]
    if not sources or '-DNDEBUG' not in command:
        return run(delegate + command)
    assert len(sources) == 1 and command.count('-o') == 1 and '-c' in command
    source = sources[0]
    name, size = SLOTS[source.replace('\\', '/').rsplit('/', 1)[-1]]
    output = Path(command[command.index('-o')+1])
    original, padded = output.with_suffix('.labcut0.s'), output.with_suffix('.labcut1.s')
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o')+1] = str(original)
    status = run(delegate + emit)
    if status:
        return status
    with padded.open('w', encoding='utf-8', newline='\n') as stream:  # write_text(newline=) needs Python 3.10
        stream.write(retain(original.read_text(encoding='utf-8'), name, size))
    assemble, index = [command[0]], 1
    while index < len(command):
        arg = command[index]
        if arg in ('-MF', '-MT', '-MQ', '-o'):
            index += 2
            continue
        if arg not in ('-MD', '-MMD', '-MP', '-c') and arg != source:
            assemble.append(arg)
        index += 1
    # .space is evaluated after literal/align relaxation. A negative extent
    # must fail the build rather than silently warning and shifting neighbors.
    return run(assemble + ['-Wa,--fatal-warnings', '-x', 'assembler', '-c', str(padded), '-o', str(output)])


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
