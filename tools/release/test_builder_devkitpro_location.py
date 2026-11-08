"""Read-only installer discovery with invented registry records and toolchains."""
import contextlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / 'builder')]
import toolchain
import products


def registry(records):
    # Only the read API exists: a write, key creation or broad enumeration fails.
    reg = SimpleNamespace(HKEY_LOCAL_MACHINE=1, KEY_READ=0x20019,
                          KEY_WOW64_32KEY=0x200, KEY_WOW64_64KEY=0x100, REG_SZ=1)
    def open_key(hive, key, reserved, access):
        view = access & 0x300
        value = records.get(view, FileNotFoundError())
        if isinstance(value, OSError):
            raise value
        return contextlib.nullcontext(view)
    reg.OpenKey = mock.Mock(side_effect=open_key)
    reg.QueryValueEx = mock.Mock(side_effect=lambda view, name: records[view])
    return reg


class DevkitProLocationTests(unittest.TestCase):
    def test_both_registry_views_are_read_without_requesting_write_access(self):
        reg = registry({0x200: ('D:/devkitPro', 1), 0x100: ('E:/devkitPro', 1)})
        self.assertEqual(toolchain.windows_install_roots(reg), ['D:/devkitPro', 'E:/devkitPro'])
        key = r'Software\Microsoft\Windows\CurrentVersion\Uninstall\devkitProUpdater'
        self.assertEqual(reg.OpenKey.call_args_list, [
            mock.call(1, key, 0, 0x20219), mock.call(1, key, 0, 0x20119)])
        self.assertEqual(reg.QueryValueEx.call_args_list, [
            mock.call(0x200, 'InstallLocation'), mock.call(0x100, 'InstallLocation')])

    def test_missing_or_unreadable_record_does_not_hide_the_other_view(self):
        for error in (FileNotFoundError(), PermissionError()):
            reg = registry({0x200: error, 0x100: ('D:/devkitPro', 1)})
            self.assertEqual(toolchain.windows_install_roots(reg), ['D:/devkitPro'])

    def test_only_absolute_drive_paths_in_string_values_are_candidates(self):
        for value, kind in (('', 1), ('relative/path', 1), ('D:relative', 1), ('/opt/devkitpro', 1),
                            ('D:/broken\0path', 1), (45, 1), ('D:/devkitPro', 4)):
            with self.subTest(value=value, kind=kind):
                self.assertEqual(toolchain.windows_install_roots(registry({0x200: (value, kind)})), [])

    def test_user_override_then_recorded_location_then_default_and_unix_unchanged(self):
        with mock.patch.object(toolchain, 'windows_install_roots', return_value=['D:/devkitPro']) as read:
            self.assertEqual(toolchain.candidate_roots({'DEVKITPRO': 'E:/custom'}, 'win32'),
                             [os.path.normpath(p) for p in ('E:/custom', 'D:/devkitPro', 'C:/devkitPro')])
            self.assertEqual(toolchain.candidate_roots({'DEVKITPRO': '/opt/devkitpro'}, 'win32')[0],
                             os.path.normpath('D:/devkitPro'))
            read.reset_mock()
            self.assertEqual(toolchain.candidate_roots({}, 'linux'), [os.path.normpath('/opt/devkitpro')])
            read.assert_not_called()

    def test_detection_uses_the_recorded_drive_for_queries_and_required_files(self):
        alternate = os.path.normpath('D:/devkitPro')
        def isfile(path):
            return os.path.normpath(path).startswith(alternate + os.sep)
        query = mock.Mock(return_value=(0, ''.join(p + ' 1-1\n' for p in
            toolchain.REQUIRED_PACKAGES + toolchain.RECOMMENDED_PACKAGES)))
        with mock.patch.object(toolchain, 'windows_install_roots', return_value=[alternate]), \
                mock.patch.object(toolchain.os, 'makedirs') as mkdir:
            tc = toolchain.detect('/fixture/tools', env={'DEVKITPRO': '/opt/devkitpro'},
                                  platform='win32', run=query, isfile=isfile)
        self.assertEqual(tc.root, alternate)
        self.assertTrue(tc.can_build)
        self.assertEqual(query.call_args.args[0][0], os.path.join(alternate, 'msys2', 'usr', 'bin', 'bash.exe'))
        mkdir.assert_not_called()

    def test_absent_record_and_files_reports_locations_without_blaming_a_component(self):
        with mock.patch.object(toolchain, 'windows_install_roots', return_value=[]):
            tc = toolchain.detect('/fixture/tools', env={}, platform='win32',
                                  isfile=lambda path: False, run=mock.Mock())
        self.assertIsNone(tc.root)
        text = '\n'.join(c.detail for c in tc.checks)
        self.assertIn('not found', text)
        self.assertIn(os.path.normpath('C:/devkitPro'), text)
        self.assertNotIn('component', text)

    def run_installer(self, files, roots):
        query = mock.Mock(return_value=(0, 'unused'))
        tested = products.release_contract.read()['tested_compiler']
        compiler = dict(version=tested['version'], target=tested['target'], vendor='devkitARM',
                        package=tested['package_version'], errors={})
        step = toolchain.Step('devkitpro', 'fixture', 'fixture', [], [['fixture-installer']],
                              admin=True, platform='win32')
        actions = toolchain.Actions(elevated=mock.Mock(return_value=0), query=query)
        with mock.patch.object(toolchain, 'require_safe_setup', return_value=True), \
                mock.patch.object(toolchain, 'candidate_roots', return_value=roots), \
                mock.patch.object(toolchain.os.path, 'isfile', side_effect=lambda p: os.path.normpath(p) in files), \
                mock.patch.object(toolchain, 'compiler_details', return_value=compiler) as details:
            result = toolchain.run_step(step, lambda text: None, False, actions,
                                       game='undertale', tested=tested)
        return result, details

    def test_installer_postcheck_rediscovers_the_selected_drive_before_compiler_check(self):
        root = os.path.normpath('D:/devkitPro')
        files = {os.path.normpath(os.path.join(root, relative)) for relative in
                 ('msys2/usr/bin/bash.exe', 'devkitARM/bin/arm-none-eabi-gcc.exe')}
        result, checked = self.run_installer(files, [root, 'C:/devkitPro'])
        self.assertTrue(result)
        self.assertEqual(checked.call_args.args[0].root, root)

    def test_postcheck_distinguishes_missing_msys_from_missing_compiler(self):
        root = os.path.normpath('D:/devkitPro')
        with self.assertRaisesRegex(toolchain.Refused, "MSYS2 tools couldn't be found.*Check again"):
            self.run_installer(set(), [root])
        bash = os.path.normpath(os.path.join(root, 'msys2/usr/bin/bash.exe'))
        with self.assertRaisesRegex(toolchain.Refused, "3DS compiler wasn't found.*Use Install beside the 3DS tools"):
            self.run_installer({bash}, [root])

    def test_missing_msys_message_keeps_the_installer_retry_button(self):
        import gui
        with self.assertRaises(toolchain.Refused) as caught:
            self.run_installer(set(), ['D:/devkitPro'])
        box = gui.StepBox.__new__(gui.StepBox)
        box.go, box.bar, box.show_btn = mock.Mock(), mock.Mock(), mock.Mock()
        box.page_btn, box._say = None, mock.Mock()
        box.failed(str(caught.exception))
        box.go.config.assert_called_once_with(text='Try again')
        box.go.state.assert_called_once_with(['!disabled'])


if __name__ == '__main__':
    unittest.main()
