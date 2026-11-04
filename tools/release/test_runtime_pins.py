"""Synthetic packaging-input fixtures; no downloads or installed runtime required."""
import copy
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_pins
import package_builder


class RuntimePinsTests(unittest.TestCase):
    def fixture(self, root):
        files = {'python.exe': b'fixture interpreter', 'tcl/init.tcl': b'fixture Tcl'}
        for name in ('pythonw.exe', '_tkinter.pyd', '_multiprocessing.pyd', 'tcl86t.dll', 'tk86t.dll',
                     'tkinter/__init__.py', 'LICENSE.txt', 'tcl/tcl8.6/license.terms', 'tcl/tk8.6/license.terms'):
            files[name] = b'fixture dependency'
        for name, data in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        pins = copy.deepcopy(runtime_pins.PINS)
        pins['windows']['python_exe_sha256'] = hashlib.sha256(files['python.exe']).hexdigest()
        pins['windows']['inventory'] = runtime_pins.inventory_pin(files)
        return files, pins

    def test_current_pin_declares_all_platforms_and_inventory_order(self):
        pins = runtime_pins.PINS
        self.assertEqual(pins['windows']['inventory'], dict(files=1067,
            sha256='a1f5754cbf8cd6845f7356360e84832f7bbb1f105d11b2b2446dbcd44de3bbeb'))
        self.assertEqual(pins['linux'], dict(mode='system', executable='python3', minimum_version='3.9', requires=['Tk']))
        self.assertEqual(set(pins['macos']['archives']), {'arm64', 'x86_64'})
        self.assertEqual(runtime_pins.inventory_pin({'z': b'2', 'A': b'1'}),
                         runtime_pins.inventory_pin({'A': b'1', 'z': b'2'}))

    def test_relocated_exact_bytes_accepted_and_loose_caches_omitted(self):
        with tempfile.TemporaryDirectory(prefix='runtime moved ') as tmp:
            root = Path(tmp)
            files, pins = self.fixture(root)
            for name in ('tkinter/__pycache__/test.pyc', 'stray.pyo', '.pytest_cache/state'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'host state')
            with mock.patch.object(runtime_pins, 'PINS', pins):
                self.assertEqual(runtime_pins.windows_files(root), files)

    def test_mutated_extra_and_missing_files_refused_before_packaging(self):
        for change in ('mutated', 'extra', 'missing', 'interpreter'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, pins = self.fixture(root)
                if change == 'mutated':
                    (root / 'tcl/init.tcl').write_bytes(b'changed Tcl')
                elif change == 'extra':
                    (root / 'extra.dll').write_bytes(b'extra')
                elif change == 'missing':
                    (root / 'tcl/init.tcl').unlink()
                else:
                    (root / 'python.exe').write_bytes(b'changed interpreter')
                output = root / 'out'
                with mock.patch.object(runtime_pins, 'PINS', pins), mock.patch.object(
                        package_builder.pipeline, 'release_version', return_value='1.0.0-beta.1'):
                    with self.assertRaisesRegex(ValueError, 'pin'):
                        package_builder.package(root / 'unused source', output, 'undertale', 'windows', runtime=root)
                self.assertFalse(output.exists())

    def test_mac_licences_are_exact_including_extra_and_missing_inputs(self):
        for change in ('none', 'mutated', 'extra', 'missing'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                expected = {'arm64/LICENSE.txt': b'upstream licence'}
                path = root / 'arm64/LICENSE.txt'
                path.parent.mkdir()
                path.write_bytes(expected['arm64/LICENSE.txt'])
                pins = copy.deepcopy(runtime_pins.PINS)
                pins['macos']['licences_inventory'] = runtime_pins.inventory_pin(expected)
                if change == 'mutated':
                    path.write_bytes(b'altered licence')
                elif change == 'extra':
                    (root / 'extra').write_bytes(b'extra')
                elif change == 'missing':
                    path.unlink()
                with mock.patch.object(runtime_pins, 'PINS', pins):
                    if change == 'none':
                        self.assertEqual(runtime_pins.mac_licence_files(root), expected)
                    else:
                        with self.assertRaisesRegex(ValueError, 'licence.*pin'):
                            runtime_pins.mac_licence_files(root)


if __name__ == '__main__':
    unittest.main()
