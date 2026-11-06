"""Use tiny synthetic ARM objects to verify the actual relocation-only compiler adapter."""
import importlib.util
from pathlib import Path
import os
import re
import subprocess
import sys
import unittest

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


def test_object_adapter_is_last_in_the_cmake_launcher_chain():
    cmake = (ROOT / 'platform/3ds/CMakeLists.txt').read_text()
    last_launcher = cmake.rindex('set_property(TARGET ctrport PROPERTY C_COMPILER_LAUNCHER')
    assert 'public_benchfile_compile.py' in cmake[last_launcher:]
    assert cmake.index('get_target_property(p51_delegate') > cmake.index('get_target_property(loadgame_delegate')
    block = re.search(r'if\(CTRPORT_GAME STREQUAL "undertale" AND CTRPORT_RELEASE_SOURCE_URL\)\s+'
                      r'# Preserve main.c.*?\nendif\(\)', cmake, re.S)[0]
    assert cmake[last_launcher:].strip() in block
    assert ';${p51_delegate};--p51-compiler"' in block
    assert re.search(r'set_property\(SOURCE "\$\{CMAKE_CURRENT_SOURCE_DIR\}/source/main.c" '
                     r'APPEND PROPERTY OBJECT_DEPENDS\s+'
                     r'"\$\{CMAKE_CURRENT_SOURCE_DIR\}/../../tools/buildcache/public_benchfile_compile.py"\)', block)


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
