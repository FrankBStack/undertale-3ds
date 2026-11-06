"""Synthetic packaging-input fixtures; no downloads or installed runtime required."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime_pins
import package_builder


class RuntimePinsTests(unittest.TestCase):
    def test_inventory_diagnostics_bound_and_escape_untrusted_names(self):
        good = {'kept': b'good', 'missing': b'missing'}
        members = [[name, len(data), hashlib.sha256(data).hexdigest()] for name, data in sorted(good.items())]
        bad = {'kept': b'changed', **{'\x1b[31m\n%04d' % i + '\U0001f600' * 10000: b'extra' for i in range(100)}}
        with self.assertRaises(ValueError) as caught:
            runtime_pins.validate_inventory(bad, runtime_pins.inventory_pin(good), 'fixture', members)
        message = str(caught.exception)
        self.assertTrue(message.isascii())
        self.assertNotIn('\x1b', message)
        self.assertNotIn('\n', message)
        self.assertIn('\\x1b', message)
        self.assertIn('82 more differences', message)
        self.assertLessEqual(message.count('extra '), 20)
        self.assertLess(len(message), 4000)

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
        pins['windows']['inventory_members'] = inventory_rows(files)
        return files, pins

    def test_current_pin_declares_vendored_platforms_and_inventory_order(self):
        pins = runtime_pins.PINS
        self.assertEqual(pins['windows']['inventory'], dict(files=1067,
            sha256='a1f5754cbf8cd6845f7356360e84832f7bbb1f105d11b2b2446dbcd44de3bbeb'))
        self.assertNotIn('linux', pins)
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
                pins['macos']['licences_members'] = inventory_rows(expected)
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


def inventory_rows(files):
    return [[name, len(data), hashlib.sha256(data).hexdigest()] for name, data in sorted(files.items())]


class RuntimeDiagnosticTests(unittest.TestCase):
    def test_checked_in_diagnostic_rows_match_both_aggregate_pins(self):
        for platform, inventory, members in (('windows', 'inventory', 'inventory_members'),
                ('macos', 'licences_inventory', 'licences_members')):
            with self.subTest(platform=platform):
                rows = runtime_pins.PINS[platform][members]
                self.assertEqual(rows, sorted(rows))
                self.assertEqual(len({row[0] for row in rows}), len(rows))
                encoded = json.dumps(rows, ensure_ascii=True, separators=(',', ':')).encode('ascii')
                self.assertEqual(dict(files=len(rows), sha256=hashlib.sha256(encoded).hexdigest()),
                                 runtime_pins.PINS[platform][inventory])

    def test_windows_refusal_names_each_changed_input(self):
        for change, name in (('modified', 'tcl/init.tcl'), ('missing', 'tcl/init.tcl'),
                ('extra', 'desktop.ini'), ('extra', 'Thumbs.db')):
            with self.subTest(change=change, name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, pins = RuntimePinsTests().fixture(root)
                if change == 'missing':
                    (root / name).unlink()
                else:
                    (root / name).write_bytes(b'changed input')
                with mock.patch.object(runtime_pins, 'PINS', pins):
                    with self.assertRaises(ValueError) as raised:
                        runtime_pins.windows_files(root)
                self.assertIn(change + ' ' + ascii(name), str(raised.exception))

    def test_mac_refusal_names_missing_extra_and_modified_licence(self):
        for change, name in (('modified', 'arm64/LICENSE.fixture'),
                ('missing', 'arm64/LICENSE.fixture'), ('extra', 'arm64/.DS_Store')):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                expected = {'arm64/LICENSE.fixture': b'upstream licence'}
                (root / 'arm64').mkdir()
                (root / 'arm64/LICENSE.fixture').write_bytes(expected['arm64/LICENSE.fixture'])
                pins = copy.deepcopy(runtime_pins.PINS)
                pins['macos']['licences_inventory'] = runtime_pins.inventory_pin(expected)
                pins['macos']['licences_members'] = inventory_rows(expected)
                if change == 'missing':
                    (root / name).unlink()
                else:
                    (root / name).write_bytes(b'changed input')
                with mock.patch.object(runtime_pins, 'PINS', pins):
                    with self.assertRaises(ValueError) as raised:
                        runtime_pins.mac_licence_files(root)
                self.assertIn(change + ' ' + ascii(name), str(raised.exception))

    def test_untrusted_runtime_cannot_supply_diagnostic_inventory(self):
        expected = {'good.dll': b'pinned'}
        actual = {'good.dll': b'changed', 'runtime-provenance.json': b'{}'}
        with self.assertRaisesRegex(ValueError, 'metadata disagrees: builder-runtime-pins.json'):
            runtime_pins.validate_inventory(actual, runtime_pins.inventory_pin(expected),
                                           'Runtime', inventory_rows(actual))
        # Diagnostic rows cannot turn a changed inventory into an accepted one.
        with self.assertRaisesRegex(ValueError, "modified 'good.dll'"):
            runtime_pins.validate_inventory(actual, runtime_pins.inventory_pin(expected),
                                           'Runtime', inventory_rows(expected))

    def test_runtime_root_and_mac_archive_refusals_name_the_input_path(self):
        import macos_bundle
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = root / 'missing-runtime'
            with self.assertRaises(ValueError) as raised:
                runtime_pins.read_files(missing)
            self.assertIn(str(missing), str(raised.exception))
            archive = root / 'changed-runtime.tar.gz'
            archive.write_bytes(b'changed archive')
            with self.assertRaises(ValueError) as raised:
                macos_bundle.runtime_files(archive, 'arm64')
            self.assertIn(str(archive), str(raised.exception))

    def test_dsp_refusal_names_the_rejected_library_and_source(self):
        import sfx_encoder
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / 'changed-encoder.dll'
            library.write_bytes(b'changed')
            with self.assertRaises(ValueError) as raised:
                sfx_encoder.validate(library, root)
            self.assertIn(str(library), str(raised.exception))
            source = root / 'tools/audio/dspadpcm.c'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'changed source')
            with mock.patch.multiple(sfx_encoder, SIZE=7, SHA256=hashlib.sha256(b'changed').hexdigest()):
                with self.assertRaises(ValueError) as raised:
                    sfx_encoder.validate(library, root)
            self.assertIn(str(source), str(raised.exception))


if __name__ == '__main__':
    unittest.main()
