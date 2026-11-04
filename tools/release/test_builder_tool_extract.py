"""SCOURSOL4-003: a CIA tool cut short while unpacking is never called installed. Invented ZIPs and files only;
nothing is downloaded, installed or run."""
import errno
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
import zipfile

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'builder'), str(HERE)]
import gui
from test_builder import fake_exe
import toolchain


PROGRAM = fake_exe()
PACKAGES = '\n'.join(name + ' 1.0' for name in (*toolchain.REQUIRED_PACKAGES, *toolchain.RECOMMENDED_PACKAGES))


class ToolExtractTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.tmp = Path(temp.name)
        self.root = self.tmp/'invented-devkit'
        for name in ('msys2/usr/bin/bash.exe', *toolchain.REQUIRED_FILES):
            path = self.root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'')
        self.tools = self.tmp/'work'/'tools'/'bin'
        self.tools.mkdir(parents=True)
        (self.tools/'bannertool.exe').write_bytes(PROGRAM)
        self.archive = self.tmp/'makerom.zip'
        with zipfile.ZipFile(self.archive, 'w', zipfile.ZIP_DEFLATED) as output:
            output.writestr('release/makerom.exe', PROGRAM)

    def detect(self):
        return toolchain.detect(str(self.tools), platform='win32', roots=[str(self.root)],
                                run=lambda argv: (0, PACKAGES))

    def install_button(self, tc):
        page = gui.ToolchainPage.__new__(gui.ToolchainPage)
        page.app = mock.Mock()
        page.app.state.tc = tc
        page.update_btn = mock.Mock()
        page.running_step = page.detecting = False
        page.boxes = []
        box = None
        for step in toolchain.full_plan(str(self.tools), str(self.tmp/'downloads'), root=str(self.root),
                                        platform='win32'):
            b = mock.Mock()
            b.step = step
            b.box.winfo_exists.return_value = True
            page.boxes.append(b)
            if step.key == 'makerom':
                box = b
        gui.ToolchainPage.update_buttons(page)
        return box.go.state.call_args.args[0]

    def test_a_full_disk_while_unpacking_leaves_no_tool_and_the_install_stays_offered(self):
        # The reviewer's order (change-scoursol4 test_partial_tool_install.py): ENOSPC after 4 bytes, then Check again.
        def full_disk(source, destination, *args, **kwargs):
            destination.write(source.read(4))
            raise OSError(errno.ENOSPC, 'invented disk full')
        with mock.patch.object(toolchain.shutil, 'copyfileobj', side_effect=full_disk):
            with self.assertRaises(OSError):
                toolchain.extract_exe(str(self.archive), 'makerom.exe', str(self.tools))
        self.assertEqual(sorted(p.name for p in self.tools.iterdir()), ['bannertool.exe'])
        tc = self.detect()
        self.assertIsNone(tc.makerom)
        self.assertEqual(self.install_button(tc), ['!disabled'])

    def test_a_failed_unpack_keeps_an_earlier_complete_tool(self):
        (self.tools/'makerom.exe').write_bytes(PROGRAM)
        with mock.patch.object(toolchain.os, 'fsync', side_effect=OSError(errno.EIO, 'invented write error')):
            with self.assertRaises(OSError):
                toolchain.extract_exe(str(self.archive), 'makerom.exe', str(self.tools))
        self.assertEqual((self.tools/'makerom.exe').read_bytes(), PROGRAM)
        self.assertFalse((self.tools/'makerom.exe.part').exists())

    def test_a_short_unpack_is_refused(self):
        def short(source, destination, *args, **kwargs):
            destination.write(source.read()[:-1])
        with mock.patch.object(toolchain.shutil, 'copyfileobj', side_effect=short):
            with self.assertRaises(toolchain.Refused):
                toolchain.extract_exe(str(self.archive), 'makerom.exe', str(self.tools))
        self.assertFalse((self.tools/'makerom.exe').exists())
        self.assertFalse((self.tools/'makerom.exe.part').exists())

    def test_a_cut_short_tool_left_by_an_older_builder_is_not_installed(self):
        for cut in (0, 4, 0x58, len(PROGRAM) - 1):
            with self.subTest(cut=cut):
                (self.tools/'makerom.exe').write_bytes(PROGRAM[:cut])
                tc = self.detect()
                self.assertIsNone(tc.makerom)
                self.assertEqual(self.install_button(tc), ['!disabled'])
                # The repair then replaces it with the whole tool.
                out = toolchain.extract_exe(str(self.archive), 'makerom.exe', str(self.tools))
                self.assertEqual(Path(out).read_bytes(), PROGRAM)
                self.assertEqual(self.detect().makerom, out)

    def test_a_complete_tool_is_installed_and_its_button_is_off(self):
        out = toolchain.extract_exe(str(self.archive), 'makerom.exe', str(self.tools))
        self.assertEqual(Path(out).read_bytes(), PROGRAM)
        self.assertEqual(sorted(p.name for p in self.tools.iterdir()), ['bannertool.exe', 'makerom.exe'])
        tc = self.detect()
        self.assertEqual(tc.makerom, out)
        self.assertTrue(tc.can_cia)
        self.assertEqual(self.install_button(tc), ['disabled'])

    def test_completeness_check(self):
        path = self.tmp/'program.exe'
        signed = PROGRAM + b'invented certificate after the sections'
        for data, complete in ((PROGRAM, True), (signed, True), (b'', False), (b'MZ', False),
                               (PROGRAM[:-1], False), (b'ZM' + PROGRAM[2:], False),
                               (PROGRAM[:0x40] + b'XX' + PROGRAM[0x42:], False)):
            path.write_bytes(data)
            self.assertIs(toolchain.complete_windows_exe(str(path)), complete)
        self.assertFalse(toolchain.complete_windows_exe(str(self.tmp/'missing.exe')))

    def test_unix_unpack_marks_only_the_complete_tool_executable(self):
        with zipfile.ZipFile(self.archive, 'w') as output:
            output.writestr('release/makerom', b'invented unix program')
        out = toolchain.extract_exe(str(self.archive), 'makerom', str(self.tools))
        self.assertEqual(Path(out).read_bytes(), b'invented unix program')
        if os.name != 'nt':
            self.assertTrue(os.access(out, os.X_OK))


if __name__ == '__main__':
    unittest.main()
