"""Synthetic ARM objects exercise the production sampler relocation adapter."""
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('touchquiz_compile', Path(__file__).with_name('touchquiz_compile.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)
sys.path.insert(0, str(Path(__file__).parent))
from devkit_tools import arm_tools

SOURCE = '''extern int __real_CtrInput_take(int);
__attribute__((weak,noinline)) int CtrTouchExt_sample(int n) { return n + 7; }
static __attribute__((noipa,section(".text_battletouchmenu"))) int btRawTake(int n) { return __real_CtrInput_take(n); }
__attribute__((noinline,section(".text_battletouch2")))
int Battletouch_take2(int n) { return btRawTake(n) + CtrTouchExt_sample(n); }
'''
# Before battletouch r2 (BT2-1) take2 made the real CtrInput_take call itself.
OLD_SOURCE = '''extern int __real_CtrInput_take(int);
__attribute__((weak,noinline)) int CtrTouchExt_sample(int n) { return n + 7; }
__attribute__((noinline,section(".text_battletouch2")))
int Battletouch_take2(int n) { return __real_CtrInput_take(n) + CtrTouchExt_sample(n); }
'''


@pytest.fixture
def cc():
    return arm_tools('gcc')[0]


@pytest.mark.parametrize('enabled', [True, False])
def test_two_routes_preserve_bytes_and_all_other_relocations(tmp_path, cc, enabled):
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE)
    before, after = tmp_path / 'before.o', tmp_path / 'after.o'
    command = [cc, '-O0', '-marm', *(['-DENABLE_WAD16'] if enabled else []), '-c', str(source), '-o']
    subprocess.run([*command, str(before)], check=True, stdin=subprocess.DEVNULL, timeout=30)
    assert adapter.main([adapter.MARKER, *command, str(after)]) == 0
    a, ae, ab = adapter.inventory(before.read_bytes())
    b, be, bb = adapter.inventory(after.read_bytes())
    assert a == b and ab == bb
    assert be == (sorted((*e[:3], adapter.ROUTES.get(e[3], e[3])) for e in ae) if enabled else ae)
    assert after.with_suffix('.touchquiz.json').exists() == enabled


@pytest.mark.parametrize('extra', [
    'int other(int n) { return CtrTouchExt_sample(n); }',
    'int other(int n) { return __real_CtrInput_take(n); }'])
def test_additional_reader_fails_closed(tmp_path, cc, extra):
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE + extra)
    with pytest.raises(AssertionError, match='unqualified sampler edges'):
        adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-c', str(source),
                      '-o', str(tmp_path / 'out.o')])


@pytest.mark.parametrize('section', ['.text_battletouch2', '.text_battletouchmenu'])
def test_wrong_caller_fails_closed(tmp_path, cc, section):
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE.replace(section, '.text_wrong'))
    with pytest.raises(AssertionError, match='unqualified sampler'):
        adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-c', str(source),
                      '-o', str(tmp_path / 'out.o')])


def test_real_take_edge_routed_from_btRawTake_only(tmp_path, cc):
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE)
    out = tmp_path / 'out.o'
    assert adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-c', str(source), '-o', str(out)]) == 0
    _, edges, bounds = adapter.inventory(out.read_bytes())
    found = {b[0]: b[1:] for b in bounds}
    def inside(edge, fn):
        section, start, end = found[fn]
        return edge[0] == section and start <= edge[1] < end
    routed = {e[3]: e for e in edges if e[3] in adapter.ROUTES.values()}
    assert inside(routed['CtrTouchQuiz_buttons'], 'btRawTake') and inside(routed['CtrTouchQuiz_claim'], 'Battletouch_take2')
    assert not any(e[3] in adapter.ROUTES for e in edges)


def test_take2_direct_real_take_fails_closed(tmp_path, cc):
    # The pre-r2 shape: a real CtrInput_take call made from take2 is no longer a qualified edge.
    source = tmp_path / 'z_battletouch.c'
    source.write_text(OLD_SOURCE)
    with pytest.raises(AssertionError, match='unqualified sampler'):
        adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-c', str(source),
                      '-o', str(tmp_path / 'out.o')])


def test_take2_only_routing_fails_against_r2(tmp_path, cc, monkeypatch):
    # The pre-r2 binding (both edges inside take2) rejects the r2 object: the BUILD TURN brelo failure.
    monkeypatch.setattr(adapter, 'CALLERS', {s: ('Battletouch_take2', '.text_battletouch2') for s in adapter.ROUTES})
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE)
    with pytest.raises(AssertionError, match="unqualified sampler edge.*__real_CtrInput_take.*text_battletouchmenu"):
        adapter.main([adapter.MARKER, cc, '-O0', '-marm', '-DENABLE_WAD16', '-c', str(source),
                      '-o', str(tmp_path / 'out.o')])


def test_assembly_request_unchanged(tmp_path, cc):
    source = tmp_path / 'z_battletouch.c'
    source.write_text(SOURCE)
    before, after = tmp_path / 'before.s', tmp_path / 'after.s'
    command = [cc, '-O0', '-marm', '-DENABLE_WAD16', '-S', str(source), '-o']
    subprocess.run([*command, str(before)], check=True, stdin=subprocess.DEVNULL, timeout=30)
    assert adapter.main([adapter.MARKER, *command, str(after)]) == 0
    assert before.read_bytes() == after.read_bytes()


def test_launcher_precedes_last_public_adapter():
    text = (ROOT / 'platform/3ds/CMakeLists.txt').read_text()
    assert text.index('get_target_property(touchquiz_delegate') < text.index('get_target_property(p51_delegate')
