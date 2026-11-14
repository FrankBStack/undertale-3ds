"""Use tiny synthetic ARM objects to verify the actual relocation-only compiler adapter."""
import importlib.util
from pathlib import Path
import os
import re
import subprocess
import sys
import unittest
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('p51_compile', Path(__file__).with_name('public_benchfile_compile.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sys.path.insert(0, str(Path(__file__).parent))
from devkit_tools import arm_tools, REQUIRE
import devkit_tools


@pytest.fixture
def cc():
    return arm_tools('gcc')[0]


@pytest.mark.parametrize('flags,expected', [(['-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE'], '__wrap_bootHookStat'),
                                           (['-DENABLE_WAD16'], 'stat'),
                                           (['-DENABLE_WAD17', '-DCTRPORT_PUBLIC_BENCH_FILE'], 'stat')])
def test_actual_object_retains_all_allocated_bytes(tmp_path, flags, expected, cc):
    source = tmp_path / 'main.c'
    source.write_text('extern int stat(void*, void*);\n'
                      '__attribute__((section(".text.late.screens"))) int probe(void) { return stat(0, 0); }\n')
    before, after = tmp_path / 'before.o', tmp_path / 'after.o'
    common = [cc, '-O0', '-marm', *flags, '-c', str(source), '-o']
    subprocess.run([*common, str(before)], check=True, stdin=subprocess.DEVNULL, timeout=30)
    assert adapter.main([adapter.MARKER, *common, str(after)]) == 0
    a, ae = adapter.inventory(before.read_bytes())
    b, be = adapter.inventory(after.read_bytes())
    assert a == b
    assert len(ae) == len(be) == 1 and ae[0][3] == 'stat' and be[0][3] == expected
    assert ae[0][:3] == be[0][:3]


def test_unqualified_second_stat_edge_is_refused(tmp_path, cc):
    source = tmp_path / 'main.c'
    source.write_text('extern int stat(void*, void*);\n'
                      '__attribute__((section(".text.late.screens"))) int probe(void) { return stat(0, 0); }\n'
                      'int extra(void) { return stat(0, 0); }\n')
    with pytest.raises(AssertionError, match='unqualified screen probe relocation'):
        adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE',
                      '-c', str(source), '-o', str(tmp_path / 'out.o')])


def test_assembly_request_is_delegated_unchanged(tmp_path, cc):
    source = tmp_path / 'main.c'
    source.write_text('extern int stat(void*, void*);\nint probe(void) { return stat(0, 0); }\n')
    command = [cc, '-O0', '-marm', '-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE', '-S', str(source), '-o']
    before, after = tmp_path / 'before.s', tmp_path / 'after.s'
    subprocess.run([*command, str(before)], check=True, stdin=subprocess.DEVNULL, timeout=30)
    assert adapter.main([adapter.MARKER, *command, str(after)]) == 0
    assert before.read_bytes() == after.read_bytes()
    assert not after.with_suffix('.p51.json').exists()


LAUNCHER_SET = r'set_property\(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER\s+"([^"]+)"\)'
LAUNCHER_GET = r'get_target_property\(\w+ ctrport C_COMPILER_LAUNCHER\)'
DISPATCH = (r'set_property\(TARGET ctrport PROPERTY RULE_LAUNCH_COMPILE\s+"\\"\$\{CTRPORT_PYTHON_EXECUTABLE\}\\" -X utf8 -I -S '
            r'\\"\$\{CMAKE_CURRENT_SOURCE_DIR\}/\.\./\.\./tools/buildcache/launch_dispatch\.py\\""\)')
INCLUDE = r'include\("\$\{CMAKE_CURRENT_SOURCE_DIR\}/([\w./-]+\.cmake)"\)'


# Left to right, the first of: a quoted argument, a bracket comment, a bracket argument, a line comment, or a quote
# that never closes. Comments are dropped; arguments are kept as written.
CMAKE_TOKEN = re.compile(r'"(?:\\.|[^"\\])*"|#\[(=*)\[.*?\]\1\]|\[(=*)\[.*?\]\2\]|#[^\n]*|"', re.S)


def cmake_code(text):
    """text without CMake comments (# lines and #[[ ]] / #[=[ ]=] brackets); quoted and bracket arguments kept."""
    def keep(m):
        assert m[0] != '"', 'Unterminated CMake string'
        return '' if m[0].startswith('#') else m[0]
    return CMAKE_TOKEN.sub(keep, text)


def expanded_code(text, read, seen=()):
    """cmake_code(text) with every include() of a platform/3ds .cmake file inlined in place; other includes fail."""
    code = cmake_code(text)
    parts, last = [], 0
    for call in re.finditer(r'(?i)\binclude\s*\(', code):
        m = re.compile(INCLUDE).match(code, call.start())
        assert m, ('Unreviewed include form', code[call.start():call.start() + 120])
        assert m[1] not in seen, ('Include cycle', m[1])
        parts += [code[last:m.start()], expanded_code(read(m[1]), read, seen + (m[1],))]
        last = m.end()
    return ''.join(parts) + code[last:]


def launcher_inventory(code):
    """Every token that can set ctrport's compile launcher must sit in one of the reviewed spellings: the single-target
    C_COMPILER_LAUNCHER set, a delegate read, or the one launcher dispatcher. Any other write (APPEND, set_target_properties,
    several targets, another language, CMAKE_*_COMPILER_LAUNCHER, a variable-named target) fails closed (c26rev8 LPIN-1)."""
    allowed = [m.span() for pattern in (LAUNCHER_SET, LAUNCHER_GET, DISPATCH) for m in re.finditer(pattern, code)]
    for token in re.finditer(r'COMPILER_LAUNCHER|RULE_LAUNCH_COMPILE', code):
        assert any(a <= token.start() and token.end() <= b for a, b in allowed), (
            'Unreviewed launcher write form', code[max(0, token.start() - 80):token.end() + 40])
    assert len(re.findall(DISPATCH, code)) <= 1, 'More than one launcher dispatcher'


def read_platform(name):
    return (ROOT / 'platform/3ds' / name).read_text(encoding='utf-8')


def assert_reviewed_main_adapter_order(cmake, read=read_platform):
    assert cmake.index('get_target_property(p51_delegate') > cmake.index('get_target_property(loadgame_delegate')
    block = re.search(r'if\(CTRPORT_GAME STREQUAL "undertale" AND CTRPORT_RELEASE_SOURCE_URL\)\s+'
                      r'# Preserve main.c.*?\nendif\(\)', cmake, re.S)[0]
    launcher = re.search(r'set_property\(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER\s+"[^"]+"\)', block)[0]
    assert 'public_benchfile_compile.py' in launcher
    assert ';${p51_delegate};--p51-compiler"' in block
    assert re.search(r'set_property\(SOURCE "\$\{CMAKE_CURRENT_SOURCE_DIR\}/source/main.c" '
                     r'APPEND PROPERTY OBJECT_DEPENDS\s+'
                     r'"\$\{CMAKE_CURRENT_SOURCE_DIR\}/../../tools/buildcache/public_benchfile_compile.py"\)', block)
    # P5-1 runs inside five explicitly reviewed launchers. dlgflash, mexdlg_native
    # (mexdlg_native_m.cmake, included after dlgflash; it rewrites z_writerfront.c and
    # z_mexdlg_native.c only), fpsghost_return and parity_motion (C' parity #2; it
    # rewrites instance.c only) pass main.c through; sfxlate changes one ARM call
    # relocation after them. Unknown launchers, changed delegates and reordering fail
    # closed. Every launcher write in CMakeLists.txt and the platform .cmake files it
    # includes is inventoried first, comments removed, so no other spelling slips past.
    start = cmake.index(block)
    prefix, block_code = expanded_code(cmake[:start], read), cmake_code(block)
    suffix = expanded_code(cmake[start + len(block):], read)
    launcher_inventory(prefix + block_code + suffix)
    assert len(re.findall(LAUNCHER_SET, block_code)) == 1, 'P5-1 block sets one launcher'
    later = list(re.finditer(LAUNCHER_SET, suffix))
    names = ('dlgflash', 'mexdlg_native', 'fpsghost_return', 'parity_motion', 'sfxlate')
    markers = ('dlgflash', 'mexdlg-native', 'fpsghost-return', 'parity-motion', 'sfxlate')
    assert len(later) == len(names)
    previous = 0
    for entry, name, marker in zip(later, names, markers):
        expected = ('${CTRPORT_PYTHON_EXECUTABLE};-X;utf8;-I;${CMAKE_CURRENT_SOURCE_DIR}'
                    '/../../tools/buildcache/' + name + '_compile.py;${' + name + '_delegate};--' + marker + '-compiler')
        assert entry[1] == expected, ('Unreviewed outer launcher or order', name, entry[1])
        assert re.search(r'get_target_property\(' + name + r'_delegate ctrport C_COMPILER_LAUNCHER\)\s*$',
                         suffix[previous:entry.start()])
        previous = entry.end()


def test_reviewed_main_adapter_order_in_the_cmake_launcher_chain(monkeypatch):
    cmake = (ROOT / 'platform/3ds/CMakeLists.txt').read_text()
    assert_reviewed_main_adapter_order(cmake)
    for mutant in (cmake.replace('${fpsghost_return_delegate};--fpsghost-return-compiler',
                                 '${wrong_delegate};--fpsghost-return-compiler'),
                   cmake.replace('/fpsghost_return_compile.py;', '/unknown_compile.py;'),
                   cmake.replace('get_target_property(p51_delegate', 'get_target_property(missing_delegate')):
        with pytest.raises((AssertionError, ValueError)):
            assert_reviewed_main_adapter_order(mutant)
    spec = importlib.util.spec_from_file_location('dlgflash_p51_chain', Path(__file__).with_name('dlgflash_compile.py'))
    outer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outer)
    delegated = []
    monkeypatch.setattr(outer, 'run', lambda command: delegated.append(command) or 73)
    command = ['arm-none-eabi-gcc', '-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE',
               '-c', '/fixture/main.c', '-o', '/fixture/main.o']
    previous = ['python', 'public_benchfile_compile.py', '--p51-compiler']
    assert outer.main([*previous, outer.MARKER, *command]) == 73
    assert delegated == [previous + command]


def test_outer_teardown_adapter_keeps_main_requests_exact():
    spec = importlib.util.spec_from_file_location('p51_outer_teardown', Path(__file__).with_name('fpsghost_return_compile.py'))
    outer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outer)
    delegate = ['python', 'public_benchfile_compile.py', '--p51-compiler']
    for source in ('fixture/main.c', r'fixture\main.c'):
        for mode in ('-c', '-S'):
            for flags in (['-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE'], ['-DENABLE_WAD17']):
                command = ['compiler', *flags, mode, source, '-o', 'main.o']
                for status in (0, 7):
                    with patch.object(outer, 'run', return_value=status) as run:
                        assert outer.main([*delegate, outer.MARKER, *command]) == status
                        run.assert_called_once_with(delegate+command)


def test_parity_motion_adapter_passes_main_requests_through_exactly():
    """C' parity #2's launcher sits between fpsghost_return and sfxlate: it may rewrite instance.c only."""
    spec = importlib.util.spec_from_file_location('p51_parity_motion', Path(__file__).with_name('parity_motion_compile.py'))
    outer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outer)
    delegate = ['python', 'fpsghost_return_compile.py', '--fpsghost-return-compiler']
    for source in ('fixture/main.c', r'fixture\main.c'):
        for mode in ('-c', '-S'):
            for flags in (['-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE', '-O2', '-DNDEBUG', '-DPLATFORM_3DS'],
                          ['-DENABLE_WAD17']):
                command = ['compiler', *flags, mode, source, '-o', 'main.o']
                for status in (0, 7):
                    with patch.object(outer, 'run', return_value=status) as run:
                        assert outer.main([*delegate, outer.MARKER, *command]) == status
                        run.assert_called_once_with(delegate + command)


def test_mexdlg_native_adapter_passes_main_requests_through_exactly():
    """mexdlg_native's launcher (set in mexdlg_native_m.cmake) sits between dlgflash and fpsghost_return: it may
    rewrite z_writerfront.c and z_mexdlg_native.c only, even with the UT o3ds flags that enable it."""
    spec = importlib.util.spec_from_file_location('p51_mexdlg_native', Path(__file__).with_name('mexdlg_native_compile.py'))
    outer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outer)
    delegate = ['python', 'dlgflash_compile.py', '--dlgflash-compiler']
    for source in ('fixture/main.c', r'fixture\main.c'):
        for mode in ('-c', '-S'):
            for flags in (['-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE', '-DCTRPORT_TARGET_O3DS', '-Os',
                           '-fno-tree-switch-conversion', '-fno-jump-tables'], ['-DENABLE_WAD17']):
                command = ['compiler', *flags, mode, source, '-o', 'main.o']
                for status in (0, 7):
                    with patch.object(outer, 'run', return_value=status) as run:
                        assert outer.main([*delegate, outer.MARKER, *command]) == status
                        run.assert_called_once_with(delegate + command)


def test_compiler_discovery_missing_required_and_relocated(tmp_path, monkeypatch):
    monkeypatch.delenv('DEVKITARM', raising=False)
    monkeypatch.delenv('DEVKITPRO', raising=False)
    monkeypatch.delenv(REQUIRE, raising=False)
    monkeypatch.setattr(devkit_tools.toolchain, 'candidate_roots', lambda: [])
    monkeypatch.setattr(devkit_tools.shutil, 'which', lambda p: None)
    with pytest.raises(unittest.SkipTest):
        arm_tools('gcc')
    monkeypatch.setenv(REQUIRE, '1')
    with pytest.raises(AssertionError, match='not available'):
        arm_tools('gcc')
    monkeypatch.delenv(REQUIRE)
    suffix = '.exe' if os.name == 'nt' else ''
    compiler = tmp_path / 'relocated tools/bin' / ('arm-none-eabi-gcc' + suffix)
    compiler.parent.mkdir(parents=True)
    compiler.touch()
    monkeypatch.setenv('DEVKITARM', str(compiler.parent.parent))
    assert arm_tools('gcc') == [str(compiler)]


def test_unknown_and_reordered_outer_launchers_are_rejected():
    cmake = (ROOT / 'platform/3ds/CMakeLists.txt').read_text()
    assert_reviewed_main_adapter_order(cmake)
    for name in ('dlgflash', 'fpsghost_return', 'parity_motion', 'sfxlate'):
        with pytest.raises(AssertionError):
            assert_reviewed_main_adapter_order(cmake.replace('/' + name + '_compile.py;', '/unknown_compile.py;'))
    import itertools
    launchers = re.findall(r'set_property\(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER\s+"([^"]+)"\)', cmake)[-4:]
    assert len(launchers) == 4
    for order in itertools.permutations(range(4)):
        if order == (0, 1, 2, 3):
            continue
        changed = cmake
        for index, launcher in enumerate(launchers):
            changed = changed.replace(launcher, 'ORDERED_LAUNCHER_' + str(index))
        for index, replacement in enumerate(order):
            changed = changed.replace('ORDERED_LAUNCHER_' + str(index), launchers[replacement])
        with pytest.raises(AssertionError):
            assert_reviewed_main_adapter_order(changed)
    extra = cmake + '\nset_property(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER "unknown.py")\n'
    with pytest.raises(AssertionError):
        assert_reviewed_main_adapter_order(extra)
    # mexdlg_native is set in an included file: an unknown name there, a dropped include, or the include moved after
    # sfxlate all fail.
    with pytest.raises(AssertionError):
        assert_reviewed_main_adapter_order(cmake, lambda n: read_platform(n).replace(
            '/mexdlg_native_compile.py;', '/unknown_compile.py;'))
    include = 'include("${CMAKE_CURRENT_SOURCE_DIR}/mexdlg_native_m.cmake")\n'
    assert cmake.count(include) == 1
    for changed in (cmake.replace(include, ''), cmake.replace(include, '') + '\n' + include):
        with pytest.raises(AssertionError):
            assert_reviewed_main_adapter_order(changed)


def test_every_other_launcher_write_form_is_rejected():
    """c26rev8 LPIN-1: launcher writes outside the reviewed spelling fail closed, before or after the P5-1 block and in
    included platform .cmake files; comments never count."""
    cmake = (ROOT / 'platform/3ds/CMakeLists.txt').read_text()
    assert_reviewed_main_adapter_order(cmake)
    forms = {
        'append': 'set_property(TARGET ctrport APPEND PROPERTY C_COMPILER_LAUNCHER "unknown.py")',
        'set_target_properties': 'set_target_properties(ctrport PROPERTIES C_COMPILER_LAUNCHER "unknown.py")',
        'several targets': 'set_property(TARGET ctrport other PROPERTY C_COMPILER_LAUNCHER "unknown.py")',
        'append string': 'set_property(TARGET ctrport APPEND_STRING PROPERTY C_COMPILER_LAUNCHER ";unknown.py")',
        'upper-case command': 'SET_PROPERTY(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER "unknown.py")',
        'variable target': 'set_property(TARGET ${ctrport_target} PROPERTY C_COMPILER_LAUNCHER "unknown.py")',
        'directory default': 'set(CMAKE_C_COMPILER_LAUNCHER "unknown.py")',
        'other language': 'set_property(TARGET ctrport PROPERTY ASM_COMPILER_LAUNCHER "unknown.py")',
        'other rule launcher': 'set_property(TARGET ctrport PROPERTY RULE_LAUNCH_COMPILE "unknown.py")',
        'second dispatcher': re.search(DISPATCH, read_platform('launch_dispatch.cmake'))[0],
        'unreviewed include': 'include(${extra_launchers})',
    }
    block = cmake.rindex('if(CTRPORT_GAME STREQUAL "undertale" AND CTRPORT_RELEASE_SOURCE_URL)', 0,
                         cmake.index('    # Preserve main.c'))
    for name, line in forms.items():
        for where, changed in (('after', cmake + '\n' + line + '\n'),
                               ('before', cmake[:block] + line + '\n' + cmake[block:])):
            with pytest.raises(AssertionError, match='Unreviewed|More than one'):
                assert_reviewed_main_adapter_order(changed)
    included = cmake + '\ninclude("${CMAKE_CURRENT_SOURCE_DIR}/late_launcher.cmake")\n'
    with pytest.raises(AssertionError):
        assert_reviewed_main_adapter_order(included, lambda n: forms['append'] if n == 'late_launcher.cmake'
                                           else read_platform(n))
    with pytest.raises(AssertionError):  # a recognized launcher hidden in an included file still joins the order pin
        assert_reviewed_main_adapter_order(included, lambda n: (
            'get_target_property(x_delegate ctrport C_COMPILER_LAUNCHER)\n'
            'set_property(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER "${x_delegate}")')
            if n == 'late_launcher.cmake' else read_platform(n))
    for comment in ('# set_property(TARGET ctrport APPEND PROPERTY C_COMPILER_LAUNCHER "unknown.py")',
                    '#[[ set_target_properties(ctrport PROPERTIES C_COMPILER_LAUNCHER "unknown.py") ]]',
                    'message(STATUS "#") # set(CMAKE_C_COMPILER_LAUNCHER "unknown.py")'):
        assert_reviewed_main_adapter_order(cmake + '\n' + comment + '\n')
    assert_reviewed_main_adapter_order(cmake, lambda n: read_platform(n) + '\n# C_COMPILER_LAUNCHER note\n')


def test_p51_then_cooler_changes_only_the_two_reviewed_main_edges(tmp_path, cc):
    spec = importlib.util.spec_from_file_location('sfxlate_main_chain', Path(__file__).with_name('sfxlate_compile.py'))
    cooler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cooler)
    source = tmp_path / 'main.c'
    source.write_text('extern int stat(void*, void*);\nextern void CtrRenderer_skipPresent(void);\n'
        '__attribute__((section(".text.late.screens"))) int probe(void) { return stat(0, 0); }\n'
        'int main(void) { CtrRenderer_skipPresent(); return probe(); }\n')
    before, after = tmp_path / 'before.o', tmp_path / 'after.o'
    command = [cc, '-O0', '-marm', '-DENABLE_WAD16', '-DCTRPORT_PUBLIC_BENCH_FILE',
               '-DCTRPORT_TARGET_O3DS', '-DCTRPORT_HAVE_TREMOR', '-c', str(source), '-o']
    subprocess.run([*command, str(before)], check=True, stdin=subprocess.DEVNULL, timeout=30)
    # The same nesting as CMake: cooler -> parity_motion -> fpsghost_return -> mexdlg_native -> dlgflash -> P5-1 ->
    # compiler. The command carries the UT o3ds flags that turn mexdlg_native on.
    delegate = [sys.executable, '-I', str(Path(__file__).with_name('parity_motion_compile.py')),
                sys.executable, '-I', str(Path(__file__).with_name('fpsghost_return_compile.py')),
                sys.executable, '-I', str(Path(__file__).with_name('mexdlg_native_compile.py')),
                sys.executable, '-I', str(Path(__file__).with_name('dlgflash_compile.py')),
                sys.executable, '-I', str(Path(__file__).with_name('public_benchfile_compile.py')),
                '--p51-compiler', '--dlgflash-compiler', '--mexdlg-native-compiler', '--fpsghost-return-compiler',
                '--parity-motion-compiler']
    assert cooler.main([*delegate, cooler.MARKER, *command, str(after)]) == 0
    full_a, full_b = cooler.inventory(before.read_bytes()), cooler.inventory(after.read_bytes())
    assert full_a[6] == full_b[6]
    edges_a, edges_b = full_a[7], full_b[7]
    # File offsets of non-allocated relocation tables may differ with the output
    # filename's string-table length; section-relative call locations may not.
    assert [(e[1:4], e[5:]) for e in edges_a] == [(e[1:4], e[5:]) for e in edges_b]
    mapped = {'stat': '__wrap_bootHookStat', 'CtrRenderer_skipPresent': 'sfcSkip'}
    assert [mapped.get(e[4], e[4]) for e in edges_a] == [e[4] for e in edges_b]
    assert set(mapped) <= {e[4] for e in edges_a}


def test_cooler_delegates_assembly_and_errors_without_edits():
    spec = importlib.util.spec_from_file_location('sfxlate_delegate_contract', Path(__file__).with_name('sfxlate_compile.py'))
    cooler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cooler)
    from types import SimpleNamespace
    delegate = ['reviewed-previous-launchers']
    for mode, status in (('-S', 0), ('-c', 7)):
        command = ['compiler', mode, 'fixture/main.c', '-o', 'main.o']
        with patch.object(cooler.subprocess, 'run', return_value=SimpleNamespace(returncode=status)) as run:
            with patch.object(cooler, 'route_main', side_effect=AssertionError('must not edit')):
                assert cooler.main([*delegate, cooler.MARKER, *command]) == status
                run.assert_called_once_with(delegate + command, stdin=subprocess.DEVNULL, timeout=1800)


def test_cooler_target_contract_rejects_other_game_and_target():
    spec = importlib.util.spec_from_file_location('sfxlate_target_contract', Path(__file__).with_name('sfxlate_compile.py'))
    cooler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cooler)
    from types import SimpleNamespace
    required = ['-DENABLE_WAD16', '-DCTRPORT_TARGET_O3DS', '-DCTRPORT_HAVE_TREMOR']
    for flags in (required + ['-DENABLE_WAD17'], required[1:], [required[0], required[2]], required[:2]):
        with patch.object(cooler.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            with pytest.raises(AssertionError, match='CMake cooler target contract'):
                cooler.main([cooler.MARKER, 'compiler', *flags, '-c', 'fixture/main.c', '-o', 'main.o'])
