"""Route UNDERTALE's final picture calls after compilation, preserving the complete warm body.

The helper has the original blitter's ABI and memory effects; it never retains the rectangle pointer.
Scope and exact call count fail closed. The independent ELF verifier checks every other allocated byte.
"""
from pathlib import Path
import json
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import vine_extract


def route(text, development=False, size_optimized=False):
    name = 'CtrRenderer_endFrame.part.0'
    if development and not re.search(r'^' + re.escape(name) + ':$', text, re.M):
        # Freewins and unoptimized builds retain the public frame body.
        name = 'CtrRenderer_endFrame'
    if development and re.search(r'^present:$', text, re.M):
        # At -O0 present is not inlined. Its five source calls are the
        # application picture; presentBottom's magnifier remains separate.
        name = 'present'
    scopes = list(re.finditer(r'(?ms)^' + re.escape(name) + r':\r?\n.*?^\s*\.size\s+' +
                             re.escape(name) + r',\s*\.-' + re.escape(name) + r'\s*$', text))
    assert len(scopes) == 1, ('Unknown renderer frame body', len(scopes))
    scope = scopes[0]
    pattern = r'(?m)^([ \t]+bl[ \t]+)blitApp(\(PLT\))?([ \t]*(?:@[^\n]*)?)$'
    body, count = re.subn(pattern, lambda m: m[1] + 'CtrUtWindow_blitApp' + (m[2] or '') + m[3], scope[0])
    expected = 5 if name == 'present' else 4 if size_optimized else 6
    assert count == expected, ('Unknown final picture caller count', count, expected)
    return text[:scope.start()] + body + text[scope.end():], count


def route_solid(text):
    scopes = list(re.finditer(r'(?ms)^emitQuad:\r?\n.*?^\s*\.size\s+emitQuad,\s*\.-emitQuad\s*$', text))
    assert len(scopes) == 1, ('Unknown emitQuad body', len(scopes))
    scope = scopes[0]
    body, count = re.subn(r'(?m)^([ \t]+bl[ \t]+)solidDrawIsNoop(\(PLT\))?([ \t]*(?:@[^\n]*)?)$',
                         lambda m: m[1]+'CtrDlgwhite_solidDrawIsNoop'+(m[2] or '')+m[3], scope[0])
    assert count == 1, ('Unknown emitQuad no-op calls', count)
    return text[:scope.start()]+body+text[scope.end():]


def run(command):
    return subprocess.run(command, stdin=subprocess.DEVNULL, timeout=1800).returncode


def main(args):
    split = args.index('--')
    delegate, command = [a for a in args[:split] if a], args[split + 1:]
    sources = [a for a in command if a.replace('\\', '/').endswith('/ctr_renderer.c')]
    if not sources or '-DENABLE_WAD16' not in command:
        return run(delegate + command)
    assert len(sources) == 1 and '-c' in command and command.count('-o') == 1
    output = Path(command[command.index('-o') + 1])
    # Side files next to the object, with names no longer than ctr_renderer.c.o: CMake keeps object paths within
    # Windows' path limit and devkitARM's assembler cannot open a longer one (colexact_compile's lesson, integrate21
    # stage73: a 92-character builder work folder).
    original_file = output.with_name('utwindow0.s')
    routed_file = output.with_name('utwindow1.s')
    original = list(command)
    original[original.index('-c')] = '-S'
    original[original.index('-o') + 1] = str(original_file)
    rc = run(delegate + original)
    if rc:
        return rc
    development = '-DCTRPORT_FREEWINS' in command or not any(a in ('-O2', '-O3') for a in command)
    text, count = route(original_file.read_text(encoding='utf-8'), development=development,
                        size_optimized=any(flag in command for flag in ('-Os', '-Oz')))
    text = route_solid(text)
    # Helper-only pass retains no ordinary body or data, preserving GCC's
    # pre-existing compiler-local tables and all original slot identities.
    helper_file = output.with_name('dlgwhite2.s')
    helper = list(original)
    helper[helper.index('-o') + 1] = str(helper_file)
    for option in ('-MF', '-MT', '-MQ'):
        while option in helper:
            at = helper.index(option)
            del helper[at:at+2]
    helper = [a for a in helper if a not in ('-MD', '-MMD', '-MP')]
    helper += ['-DCTRPORT_DLGWHITE_HELPER', '-fno-section-anchors']
    rc = run(helper)
    if rc: return rc
    extra, sections = vine_extract.late_sections(helper_file.read_text(encoding='utf-8'), 'dlgwhite')
    text += '\n'+extra
    with open(routed_file, 'w', encoding='utf-8', newline='\n') as handle:  # write_text(newline=) needs Python 3.10
        handle.write(text)
    assemble, i = [command[0]], 1
    while i < len(command):
        arg = command[i]
        if arg in ('-MF', '-MT', '-MQ', '-o'):
            i += 2
            continue
        if arg not in ('-MD', '-MMD', '-MP', '-c') and arg not in sources:
            assemble.append(arg)
        i += 1
    rc = run(assemble + ['-x', 'assembler', '-c', str(routed_file), '-o', str(output)])
    output.with_name('utwindow.json').write_text(json.dumps(dict(
        caller='CtrRenderer_endFrame.part.0', old='blitApp', new='CtrUtWindow_blitApp',
        count=count, exit=rc, original=str(original_file), routed=str(routed_file)), indent=2) + '\n', encoding='utf-8')
    print(f'Window motion: {count} final picture call operands routed; warm instructions retained', flush=True)
    return rc
