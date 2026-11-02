"""Restore the UT pack callback's section order without changing assembly bytes.

Retargeting its conversion call removes a local call-graph dependency, so GCC
emits packRow before startThread. Move that complete section back immediately
after CtrPack_convertTile. The full linked layout gate remains mandatory.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--redpix-compiler'


def restore(text):
    def block(name):
        starts = list(re.finditer(r'(?m)^[ \t]*\.section[ \t]+\.text\.' + name + r',.*\n', text))
        ends = list(re.finditer(r'(?m)^[ \t]*\.size[ \t]+' + name + r',[ \t]*\.-' + name + r'[ \t]*\n', text))
        assert len(starts) == len(ends) == 1, ('missing/duplicate callback-order anchor', name)
        start, end = starts[0].start(), ends[0].end()
        assert start < end
        chunk = text[start:end]
        assert len(re.findall(r'(?m)^[ \t]*\.section\b', chunk)) == 1, ('nested section', name)
        assert len(re.findall(r'(?m)^' + name + r':$', chunk)) == 1, ('missing function label', name)
        return start, end, chunk

    start, end, row = block('packRow')
    anchor_start, anchor_end, _ = block('CtrPack_convertTile')
    assert len(re.findall(r'(?m)^[ \t]*bl[ \t]+CtrPack_convertTileRedpix(?:\(PLT\))?[ \t]*$', row)) == 1, 'unexpected conversion call'
    if start >= anchor_end:
        between = text[anchor_end:start]
        assert not re.search(r'(?m)^[ \t]*\.section[ \t]+\.text\.', between), 'unexpected callback order'
        return text, dict(changed=False, callback_sha256=hashlib.sha256(row.encode()).hexdigest())
    assert end <= anchor_start, 'overlapping callback-order anchors'
    # Reorder complete byte strings only: no instruction, literal, label or directive is rewritten.
    chunks = [text[:start], row, text[end:anchor_end], text[anchor_end:]]
    reordered = [chunks[0], chunks[2], chunks[1], chunks[3]]
    assert Counter(chunks) == Counter(reordered)
    result = ''.join(reordered)
    assert result.count(row) == text.count(row) == 1
    return result, dict(changed=True, callback_sha256=hashlib.sha256(row.encode()).hexdigest())


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index(MARKER)
    delegate, command = [a for a in args[:split] if a], args[split+1:]
    sources = [a for a in command if a.replace('\\', '/').endswith('/ctr_texture_pack.c')]
    if not sources or '-DENABLE_WAD16' not in command or '-DENABLE_WAD17' in command or '-DNDEBUG' not in command:
        return run(delegate + command)
    assert len(sources) == 1 and command.count('-o') == 1 and '-c' in command
    source = sources[0]
    output = Path(command[command.index('-o')+1])
    original, restored = output.with_name('redpix0.s'), output.with_name('redpix1.s')
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o')+1] = str(original)
    status = run(delegate + emit)
    if status:
        return status
    text, receipt = restore(original.read_text(encoding='utf-8'))
    with restored.open('w', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
    assemble, index = [command[0]], 1
    while index < len(command):
        arg = command[index]
        if arg in ('-MF', '-MT', '-MQ', '-o'):
            index += 2
            continue
        if arg not in ('-MD', '-MMD', '-MP', '-c') and arg != source:
            assemble.append(arg)
        index += 1
    status = run(assemble + ['-Wa,--fatal-warnings', '-x', 'assembler', '-c', str(restored), '-o', str(output)])
    receipt.update(exit=status)
    output.with_name('redpix-order.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
    print('redpix callback order: '+json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
