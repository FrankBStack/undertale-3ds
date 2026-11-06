"""Assembler checks for frozen loader slots and restored constant targets."""
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'release/builder'))
import toolchain

from devkit_tools import arm_tools, REQUIRE


def rejected(action):
    try:
        action()
    except AssertionError:
        return
    raise AssertionError('Invalid assembly accepted')


def check_slots(out):
    import loadgame_compile as adapter
    assembler, objcopy = arm_tools()
    source = '.syntax unified\n.arm\n.section .text.test,"ax",%progbits\n'
    for name in ('CtrBootlog_hide', 'CtrScreens_moveConsoles'):
        source += f'.global {name}\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    for game, model, size in (('undertale','o3ds',496), ('undertale','n3ds',592),
                             ('deltarune','o3ds',592), ('deltarune','n3ds',592)):
        path, obj, raw = out/'slots.s', out/'slots.o', out/'slots.bin'
        path.write_text(adapter.main_slots(source,game,model),encoding='utf-8')
        subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],
                       check=True,stdin=subprocess.DEVNULL,timeout=10)
        subprocess.run([objcopy,'-O','binary',str(obj),str(raw)],
                       check=True,stdin=subprocess.DEVNULL,timeout=10)
        expected = bytes.fromhex('1eff2fe1')+bytes(244)
        expected += bytes.fromhex('1eff2fe1')+bytes(size-252)
        assert raw.read_bytes() == expected, (game,model)
    rejected(lambda: adapter.main_slots(source.replace('CtrBootlog_hide, .-CtrBootlog_hide',
                                                       'other, .-other'),'undertale','o3ds'))
    rejected(lambda: adapter.main_slots(source+source,'undertale','o3ds'))
    path.write_text(adapter.main_slots(source.replace(' bx lr',' .space 252',1),
                                       'undertale','o3ds'),encoding='utf-8')
    bad = subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],
                         capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    # Main's new cold callee may move the console function after other late
    # functions. The adapter restores whole chunks to the frozen input order.
    order=('CtrScreens_moveConsoles','CtrScreens_flushConsoles','CtrScreens_benchLaunched',
           'CtrScreens_screenshotNotice','__wrap_CtrLog_emergencyKeepLink')
    # Use a fresh owner so no duplicate names can satisfy the order test.
    shuffled='.syntax unified\n.arm\n.section .vidfix,"ax",%progbits\n.type CtrBootlog_hide,%function\nCtrBootlog_hide:\n bx lr\n.size CtrBootlog_hide, .-CtrBootlog_hide\n'
    for name in (*order[1:],order[0]):
        shuffled+=f'.section .text.late.screens,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    restored=adapter.main_slots(shuffled,'undertale','o3ds')
    assert [restored.index(name+':') for name in order]==sorted(restored.index(name+':') for name in order)
    constants = '.section .rodata.test,"a",%progbits\n.align 1\n.set .LANCHOR0, . + 0\n'
    constants += '.type second, %object\n.size second, 4\nsecond:\n.ascii "bbb\\000"\n'
    constants += '.type first, %object\n.size first, 2\nfirst:\n.ascii "a\\000"\n'
    constants += '.section .text\n.word .LANCHOR0+4\n.word .LANCHOR0+1\n'
    sections = {'.rodata.test': [dict(name='first',size=2,offset=0),
                                dict(name='second',size=4,offset=2)]}
    restored = adapter.constants(constants,sections)
    assert restored.index('first:') < restored.index('second:')
    assert '.word first\n.word second+1' in restored and '.LANCHOR' not in restored
    rejected(lambda: adapter.constants(constants.replace('.word .LANCHOR0+4',
                                                          'ldr r0, .LANCHOR0+4'),sections))
    rejected(lambda: adapter.constants(constants.replace('.size first, 2','.size first, 3'),sections))
    rejected(lambda: adapter.constants(constants.replace('second:', 'unknown:'),sections))
    # A whole helper may fill a retained cold slot only after its returning
    # original entry; assembly must reject even a 4 B overflow.
    owners = {'lsDrawDog':['Loadgame_packFallback'],
              'lsDrawText':['Loadgame_layout','Loadgame_framebuffer'],
              'lsBegin':['Loadgame_consoleBack'], 'psSaveShot':['Loadgame_prepare','Loadgame_format','Loadgame_present','Loadgame_saveShot','Loadgame_swap']}
    source='.syntax unified\n.arm\n.section .rodata\n.byte 1,1\n';entries=[]
    for i,name in enumerate(owners):
        source += f'.section .text.test,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
        entries.append(dict(name=name,size=128 if name=='psSaveShot' else 16,offset=i*16))
    for names in owners.values():
        for name in names:
            source+=f'.section .text.late.loadgame,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    packed=adapter.retain(source,{'.text.test':entries},True,'undertale')
    path.write_text(packed,encoding='utf-8')
    subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],check=True,stdin=subprocess.DEVNULL,timeout=10)
    overflow=source.replace('Loadgame_packFallback:\n bx lr','Loadgame_packFallback:\n .space 16\n bx lr')
    path.write_text(adapter.retain(overflow,{'.text.test':entries},True,'undertale'),encoding='utf-8')
    bad=subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    overflow=source.replace('Loadgame_present:\n bx lr','Loadgame_present:\n .space 100\n bx lr')
    path.write_text(adapter.retain(overflow,{'.text.test':entries},True,'undertale'),encoding='utf-8')
    bad=subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    # R270 hardens the player helpers by branching into appended cold bodies.
    # Their reviewed slots retain both their PC and extent on Old and New.
    guarded=shuffled
    for name in ('Loadgame_carryCopy','Loadgame_restoreMenu','Loadgame_guardedCarry'):
        guarded+=f'.section .text.dlgtopfix_late,"ax",%progbits\n.type {name},%function\n{name}:\n bx lr\n.size {name}, .-{name}\n'
    for model,restore_size in (('o3ds',36),('n3ds',44)):
        retained=adapter.main_slots(guarded,'undertale',model)
        assert '.org Loadgame_carryCopy + 112, 0' in retained
        assert f'.org Loadgame_restoreMenu + {restore_size}, 0' in retained
        path.write_text(retained,encoding='utf-8')
        subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],check=True,stdin=subprocess.DEVNULL,timeout=10)
    rejected(lambda: adapter.main_slots(guarded.replace('Loadgame_restoreMenu, .-Loadgame_restoreMenu','missing, .-missing'),'undertale','o3ds'))
    overflow=guarded.replace('Loadgame_carryCopy:\n bx lr','Loadgame_carryCopy:\n .space 116\n bx lr')
    path.write_text(adapter.main_slots(overflow,'undertale','o3ds'),encoding='utf-8')
    bad=subprocess.run([assembler,'--fatal-warnings',str(path),'-o',str(obj)],capture_output=True,text=True,stdin=subprocess.DEVNULL,timeout=10)
    assert bad.returncode and 'backwards' in bad.stderr
    print('PASS: four target slots and R270 player slots, zero tails, overflow and malformed input rejection; named constant targets restored')


def check_file_hoist(out):
    import loadgame_compile as adapter
    assembler, _ = arm_tools()
    source = ('.syntax unified\n.arm\n.file 1 "a.c"\n.section .text_x,"ax",%progbits\n'
              '.global first\n.type first,%function\nfirst:\n.file 2 "b.h"\n.loc 2 1 1\n bx lr\n.size first, .-first\n'
              '.global second\n.type second,%function\nsecond:\n.loc 2 2 1\n bx lr\n.size second, .-second\n')
    order = {'.text_x': [dict(name='second', offset=0, size=4), dict(name='first', offset=4, size=4)]}
    text = adapter.retain(source, order, None)
    assert text.index('second:') < text.index('first:')
    assert text.index('.file 2') < text.index('.section .text_x')
    assert text.count('.file 2') == 1
    path = out/'hoist.s'
    path.write_text(text, encoding='utf-8')
    subprocess.run([assembler, '--fatal-warnings', str(path), '-o', str(out/'hoist.o')],
                   check=True, stdin=subprocess.DEVNULL, timeout=10)


class LoadgameCompileTests(unittest.TestCase):
    def test_missing_tools_skip_and_relocated_tools_are_discovered(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(shutil, 'which', return_value=None), \
                mock.patch.object(toolchain, 'candidate_roots', return_value=[]):
            with self.assertRaises(unittest.SkipTest):
                arm_tools()
        with mock.patch.dict(os.environ, {REQUIRE: '1'}, clear=True), \
                mock.patch.object(shutil, 'which', return_value=None), \
                mock.patch.object(toolchain, 'candidate_roots', return_value=[]):
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

    def test_frozen_slots_and_constant_targets(self):
        with tempfile.TemporaryDirectory(prefix='loadgame-slots-') as directory:
            check_slots(Path(directory))

    def test_reordered_chunk_keeps_numbered_file_before_its_first_loc(self):
        with tempfile.TemporaryDirectory(prefix='loadgame-hoist-') as directory:
            check_file_hoist(Path(directory))

    def test_standard_install_is_found_without_environment_variables_or_path(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory) / 'devkitARM/bin'
            folder.mkdir(parents=True)
            suffix = '.exe' if os.name == 'nt' else ''
            expected = [folder / ('arm-none-eabi-' + name + suffix) for name in ('as', 'objcopy')]
            for path in expected:
                path.write_bytes(b'fixture')
            with mock.patch.dict(os.environ, {}, clear=True), \
                    mock.patch.object(toolchain, 'candidate_roots', return_value=[directory]), \
                    mock.patch.object(shutil, 'which', return_value=None):
                self.assertEqual(arm_tools(), list(map(str, expected)))


if __name__ == '__main__':
    unittest.main()
