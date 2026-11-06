"""Exercise the retained-slot assembler adapter and fail-closed cases."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import fpsbox_compile

# Same discovery as test_loadgame_compile.py (kept here: that test ships with UNDERTALE only, this one with both games).
# The release-day gate sets this: there a missing devkitARM fails instead of skipping.
REQUIRE = 'REQUIRE_DEVKITARM'
# The standard install folders, searched after DEVKITARM and DEVKITPRO, as the builder and test_compile_cache.py do.
STANDARD_ROOTS = [Path('C:/devkitPro/devkitARM/bin'), Path('/opt/devkitpro/devkitARM/bin')]


def arm_tools():
    """Discover one assembler/objcopy pair: DEVKITARM, DEVKITPRO, the standard install folders, then PATH.

    A plain pytest run on a machine with no devkitARM skips; with REQUIRE_DEVKITARM=1 it fails."""
    suffix = '.exe' if os.name == 'nt' else ''
    roots = [Path(os.environ['DEVKITARM']) / 'bin'] if os.environ.get('DEVKITARM') else []
    if os.environ.get('DEVKITPRO'):
        roots.append(Path(os.environ['DEVKITPRO']) / 'devkitARM/bin')
    roots += STANDARD_ROOTS
    for folder in roots:
        tools = [folder / ('arm-none-eabi-' + tool + suffix) for tool in ('as', 'objcopy')]
        if all(tool.is_file() for tool in tools):
            return list(map(str, tools))
    assembler = shutil.which('arm-none-eabi-as')
    if assembler:
        objcopy = Path(assembler).with_name('arm-none-eabi-objcopy' + suffix)
        if objcopy.is_file():
            return [assembler, str(objcopy)]
    message = ('devkitARM assembler and objcopy are not available through DEVKITARM, DEVKITPRO, '
               'C:/devkitPro/devkitARM, /opt/devkitpro/devkitARM or PATH')
    if os.environ.get(REQUIRE):
        raise AssertionError(message)
    raise unittest.SkipTest(message)


def check_slots(out):
    assembler, objcopy = arm_tools()
    source = '.syntax unified\n.arm\n.section .text,"ax",%progbits\n'
    for name in fpsbox_compile.SLOTS:
        source += f'.global {name}\n.type {name},%function\n{name}:\n\tbx lr\n\t.size {name}, .-{name}\n'
    padded = fpsbox_compile.retain(source)
    path, obj, raw = out/'slots.s', out/'slots.o', out/'slots.bin'
    path.write_text(padded, encoding='utf-8')
    subprocess.run([assembler, str(path), '-o', str(obj)], check=True,
                   stdin=subprocess.DEVNULL, timeout=10)
    subprocess.run([objcopy, '-O', 'binary', str(obj), str(raw)], check=True,
                   stdin=subprocess.DEVNULL, timeout=10)
    assert raw.read_bytes() == bytes.fromhex('1eff2fe1')+bytes(668)+bytes.fromhex('1eff2fe1')+bytes(712)
    path.write_text(padded.replace('arguiPaintScreen:\n\tbx lr',
                                  'arguiPaintScreen:\n\t.space 676'), encoding='utf-8')
    failure = subprocess.run([assembler, '--fatal-warnings', str(path), '-o', str(obj)], capture_output=True,
                             stdin=subprocess.DEVNULL, text=True, timeout=10)
    assert failure.returncode != 0 and '.space' in failure.stderr and 'negative' in failure.stderr
    for bad in (source.replace('arguiDrawText, .-arguiDrawText', 'other, .-other'), source+source):
        try:
            fpsbox_compile.retain(bad)
        except AssertionError:
            pass
        else:
            raise AssertionError('Missing/duplicate function accepted')
    print('PASS: exact 672/716 B slots and zero tails; overflow/missing/duplicate rejected')


class FpsboxCompileTests(unittest.TestCase):
    def test_missing_tools_skip_and_relocated_tools_are_discovered(self):
        module = sys.modules[__name__]
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(shutil, 'which', return_value=None), \
                mock.patch.object(module, 'STANDARD_ROOTS', []):
            with self.assertRaises(unittest.SkipTest):
                arm_tools()
        with mock.patch.dict(os.environ, {REQUIRE: '1'}, clear=True), \
                mock.patch.object(shutil, 'which', return_value=None), mock.patch.object(module, 'STANDARD_ROOTS', []):
            with self.assertRaises(AssertionError):
                arm_tools()
        with tempfile.TemporaryDirectory(prefix='relocated compiler ') as directory:
            folder = Path(directory) / 'bin'
            folder.mkdir()
            suffix = '.exe' if os.name == 'nt' else ''
            expected = [folder / ('arm-none-eabi-' + name + suffix) for name in ('as', 'objcopy')]
            for path in expected:
                path.write_bytes(b'fixture')
            with mock.patch.dict(os.environ, {'DEVKITARM': directory}, clear=True):
                self.assertEqual(arm_tools(), list(map(str, expected)))
            # A standard install with no DEVKITARM/DEVKITPRO and nothing on PATH is still found (R219-01).
            with mock.patch.dict(os.environ, {REQUIRE: '1'}, clear=True), \
                    mock.patch.object(shutil, 'which', return_value=None), \
                    mock.patch.object(module, 'STANDARD_ROOTS', [folder]):
                self.assertEqual(arm_tools(), list(map(str, expected)))

    def test_retained_slots(self):
        with tempfile.TemporaryDirectory(prefix='fpsbox-slots-') as directory:
            check_slots(Path(directory))


if __name__ == '__main__':
    unittest.main()
