"""Retain UT's original audio slots and position constants for audpar fixes.

Move only the two complete four-byte .rodata chunks, retaining every label,
expression and instruction. The frozen zq64 order is get-position then
set-position. Unexpected or ambiguous compiler output fails before assembly;
check_audpar_layout.py independently requires the linked original data and
every unchanged sized symbol to match byte for byte. The independent asset-offset
fix keeps unused copies of the original position tables and moves live tables late.
"""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys

MARKER = '--audpar-compiler'
NAMES = ('ctrGetTrackPosition', 'ctrSetTrackPosition')
SECTION = re.compile(r'(?=^[ \t]*\.section[ \t]+)', re.M)
TABLE = re.compile(r'[ \t]*\.section[ \t]+\.rodata\n'
                   r'(?:[ \t]*\.align[ \t]+0\n)*'
                   r'(?P<label>\.L(?P<number>\d+)):\n'
                   r'(?:[ \t]*\.byte[ \t]+\(\.L\d+-\.Lrtx(?P=number)-4\)/4\n){4}')


def restore_tables(text, names=NAMES):
    chunks = SECTION.split(text)
    original = list(chunks)
    ranges = {}
    for name in names:
        found = list(re.finditer(r'^'+name+r':\n.*?^[ \t]*\.size[ \t]+'+name+r',[^\n]*\n',
                                 text, re.M | re.S))
        assert len(found) == 1, ('missing/duplicate position function', name)
        ranges[name] = found[0].span()
    found = {name: [] for name in names}
    offset = 0
    for index, chunk in enumerate(chunks):
        if re.match(r'[ \t]*\.section[ \t]+\.rodata\n', chunk):
            if any(start <= offset < end for start, end in ranges.values()):
                match = TABLE.fullmatch(chunk)
                assert match, ('unqualified position table', chunk[:300])
                label = match['label']
                # A moved table can physically fall inside the other body's
                # assembly range. Ownership follows the literal reference,
                # never the table's current location or numeric label suffix.
                owners = [name for name, (start, end) in ranges.items() if re.search(
                    r'^[ \t]*\.word[ \t]+'+re.escape(label)+r'[ \t]*$', text[start:end], re.M)]
                assert len(owners) == 1, ('unqualified position table reference', label, owners)
                owner = owners[0]
                start, end = ranges[owner]
                labels = {'.Lrtx'+match['number'], *re.findall(r'\.byte[ \t]+\((\.L\d+)-', chunk)}
                assert all(re.search(r'^'+re.escape(target)+r':$', text[start:end], re.M)
                           for target in labels), ('position table target outside owner', owner, labels)
                found[owner].append((index, label))
        offset += len(chunk)
    assert all(len(entries) == 1 for entries in found.values()), ('missing/duplicate position table', found)
    assert found[names[0]][0][1] != found[names[1]][0][1], 'duplicate position table label'
    first, second = (found[name][0][0] for name in names)
    changed = first > second
    if changed:
        chunks[first], chunks[second] = chunks[second], chunks[first]
    assert Counter(original) == Counter(chunks), 'table movement changed a chunk'
    moved = {first, second}
    assert [c for i, c in enumerate(original) if i not in moved] == [
        c for i, c in enumerate(chunks) if i not in moved], 'non-table assembly changed'
    return ''.join(chunks), dict(changed=changed, tables={name: found[name][0][1] for name in names},
                                table_bytes=4)


def restore_offset_emission(text):
    """Restore shared-section emission order without changing instructions/data.

    New calls alter GCC's top-level order. Keep the four decoder/channel helpers,
    the deferred play body and its chain, and the init/play string pools where
    zq64 emitted them. Fail on an unfamiliar grouping instead of moving a guess.
    """
    before = Counter(text.splitlines())
    chunks = SECTION.split(text)
    def find(section, needle):
        hits = [i for i,c in enumerate(chunks) if
                re.match(r'[ \t]*\.section[ \t]+'+re.escape(section)+r'(?:,|\n)', c)
                and needle in c]
        assert len(hits) == 1, ('unqualified offset emission group', section, needle, hits)
        return hits[0]
    def take(name):
        index = find('.text.late.utaudio2', name+':\n')
        pattern = (r'\t.align\t2\n\t.syntax unified\n\t.arm\n\t.type\t'
                   +re.escape(name)+r', %function\n.*?^\t.size\t'+re.escape(name)+r',[^\n]*\n')
        matches = list(re.finditer(pattern, chunks[index], re.M | re.S))
        assert len(matches) == 1, ('unqualified offset helper', name)
        m = matches[0]
        assert re.findall(r'^([A-Za-z]\w*):',m[0],re.M) == [name]
        chunks[index] = chunks[index][:m.start()]+chunks[index][m.end():]
        return m[0]
    def before_function(block, name):
        index = find('.text.late.utaudio2', name+':\n')
        match = re.search(r'\t.align\t2\n\t.syntax unified\n\t.arm\n\t.type\t'
                          +re.escape(name)+r', %function\n', chunks[index])
        assert match, ('unqualified offset insertion', name)
        chunks[index] = chunks[index][:match.start()]+block+chunks[index][match.start():]
    names = ('utaDecOpenMemory', 'utaChnReset', 'utaChnSetInterp', 'utaChnSetFormat')
    src = find('.text.late.utaudio2', names[0]+':\n')
    dst = find('.text.late.utaudio2', 'utaSetCallback:\n')
    pattern = (r'\t.align\t2\n\t.syntax unified\n\t.arm\n\t.type\t'
               +names[0]+r', %function\n.*?^\t.size\t'+names[-1]+r',[^\n]*\n')
    matches = list(re.finditer(pattern, chunks[src], re.M | re.S))
    assert len(matches) == 1, ('unqualified offset helper block', len(matches))
    m = matches[0]; block = m[0]
    actual = re.findall(r'^([A-Za-z]\w*):',block,re.M)
    if actual == [names[0], 'utaBuildSeam', *names[1:]]:
        # New's frozen order has sample-position then seam-building before
        # utaFeed. New calls move those two independently of the decoder group.
        seam = take('utaBuildSeam')
        sample = take('utaChnGetSamplePos')
        before_function(seam, 'utaFeed')
        before_function(sample, 'utaBuildSeam')
        matches = list(re.finditer(pattern, chunks[src], re.M | re.S))
        assert len(matches) == 1, 'New decoder block did not become contiguous'
        m = matches[0]; block = m[0]
    assert re.findall(r'^([A-Za-z]\w*):',block,re.M) == list(names), actual
    assert 'utaQueue:\n' in chunks[src][m.end():]
    chunks[src] = chunks[src][:m.start()]+chunks[src][m.end():]
    pos = chunks[dst].index('\t.align\t2\n')
    chunks[dst] = chunks[dst][:pos]+block+chunks[dst][pos:]
    play = find('.text.flowburst_late', 'flowendPlaySound:\n')
    chain = find('.text.flowburst_late', 'CtrAudioSystem_chainFlowburst:\n')
    assert chain < play, 'unexpected offset deferred-play order'
    chunks[play], chunks[chain] = chunks[chain], chunks[play]
    fatal = find('.rodata.str1.4', '\t.ascii\t"FATAL: malloc(')
    init = find('.rodata.str1.4', '\t.ascii\t"opener thread below it')
    header = '\t.section\t.rodata.str1.4\n'
    assert chunks[fatal].startswith(header)
    payload = chunks[fatal][len(header):]
    assert len(re.findall(r'^\.LC\d+:',payload,re.M)) == 1
    match = re.search(r'\t.align\t2\n\.LC\d+:\n\t.ascii\t"Audio: NDSP failed', chunks[init])
    assert match, 'unqualified offset init strings'
    chunks[init] = chunks[init][:match.start()]+payload+chunks[init][match.start():]
    chunks[fatal] = header
    init = find('.rodata.str1.4', '\t.ascii\t"opener thread below it')
    group = find('.rodata.str1.4', '\t.ascii\t"Audio: wanted to load audio group')
    assert group < init, 'unexpected offset init string order'
    block = chunks.pop(init); chunks.insert(group,block)
    play = find('.rodata.str1.4', '\t.ascii\t"Audio: invalid stream index')
    update = find('.rodata.str1.4', '\t.ascii\t"Audio: read \'%s\' (%lu bytes) in the background')
    assert update < play, 'unexpected offset play string order'
    block = chunks.pop(play); chunks.insert(update,block)
    result = ''.join(chunks)
    assert Counter(result.splitlines()) == before, 'offset emission changed an assembly line'
    return result


def restore_offsets(text, diagnostic=False):
    """Keep zq64's anonymous constants as unused placeholders, new tables late.

    The linked-data verifier independently compares the complete original sections.
    These are the frozen UT Old AND New object's four-byte get/set table contents;
    their new instruction-relative expressions must remain with the new bodies.
    No table is patched in use, and no instruction is changed here.
    """
    names = ('audparGetTrackPosition', 'audparSetTrackPosition')
    text, receipt = restore_tables(text, names)
    values = ((56, 21, 6, 0), (43, 20, 41, 0))
    for name, data in zip(names, values):
        label = receipt['tables'][name]
        chunks = SECTION.split(text)
        found = [i for i, chunk in enumerate(chunks)
                 if (m := TABLE.fullmatch(chunk)) and m['label'] == label]
        assert len(found) == 1, ('offset table disappeared', name)
        index = found[0]
        table = chunks[index].replace('.rodata\n', '.rodata.late.audpar\n', 1)
        chunks[index] = '\t.section\t.rodata\n\t.byte\t'+','.join(map(str, data))+'\n'+table
        text = ''.join(chunks)
    if not diagnostic:
        # The C change replaces a clear with a snapshot helper and moves ctx's
        # sentinel into it; initialization also delegates its enlarged allocation.
        # Never permit growth: a negative .space is a fatal assembler warning.
        for name, extent in (('ctrInit', 1652), ('ctrPlaySound', 1372), ('flowendPlaySound', 560)):
            pattern = r'(^[ \t]*\.size[ \t]+'+name+r',[^\n]*\n)'
            text, count = re.subn(pattern, lambda m: m[0]+f'\t.space {extent}-(.-{name}), 0\n', text, flags=re.M)
            assert count == 1, ('missing/duplicate retained offset slot', name)
    receipt.update(offset_placeholders=[list(x) for x in values], retained_slots=not diagnostic)
    return text, receipt


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def selected(command):
    sources = [arg for arg in command if arg.replace('\\', '/').endswith('/ctr_audio_system.c')]
    return len(sources) == 1 and all(arg in command for arg in (
        '-DENABLE_WAD16', '-D__3DS__', '-DNDEBUG', '-O2'))


def main(args):
    split = args.index(MARKER)
    delegate, command = [arg for arg in args[:split] if arg], args[split+1:]
    if not selected(command):
        return run(delegate+command)
    assert '-c' in command and command.count('-o') == 1
    source = next(arg for arg in command if arg.replace('\\', '/').endswith('/ctr_audio_system.c'))
    output = Path(command[command.index('-o')+1])
    original, restored = output.with_name('audpar0.s'), output.with_name('audpar1.s')
    emit = list(command)
    emit[emit.index('-c')] = '-S'
    emit[emit.index('-o')+1] = str(original)
    status = run(delegate+emit)
    if status:
        return status
    raw = original.read_text(encoding='utf-8')
    if re.search(r'^audparGetTrackPosition:', raw, re.M):
        diagnostic = any(arg.startswith('-DCTR_AUDIO_PCM_HASH') or
                         arg.replace('\\', '/').endswith('/ctr_audio_capture_wrap.h') for arg in command)
        if not diagnostic:
            raw = restore_offset_emission(raw)
        text, receipt = restore_offsets(raw, diagnostic)
    else:
        text, receipt = restore_tables(raw)
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
    status = run(assemble+['-Wa,--fatal-warnings', '-x', 'assembler', '-c', str(restored), '-o', str(output)])
    receipt.update(exit=status)
    output.with_name('audpar.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('audpar retained position tables: '+json.dumps(receipt), flush=True)
    return status


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
