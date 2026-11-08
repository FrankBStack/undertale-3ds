"""Incomplete extracted kits: invented folders only, no game, installs or GUI."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import package_builder
import macos_bundle


class FirstLaunchTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows cmd launcher')
    def test_windows_launcher_alone_explains_extract_all_before_starting_python(self):
        for game in ('undertale', 'deltarune'):
            for arguments in ([], ['--help']):
                with self.subTest(game=game, arguments=arguments), tempfile.TemporaryDirectory() as tmp:
                    launcher = Path(tmp) / (game + '-3ds-builder.cmd')
                    launcher.write_bytes(package_builder.launcher(game, 'windows').encode('utf-8'))
                    result = subprocess.run(['cmd.exe', '/d', '/c', str(launcher), *arguments],
                        stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
                        creationflags=subprocess.CREATE_NO_WINDOW)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertIn('Extract the whole builder ZIP first.', result.stdout)
                    self.assertIn('Right-click the downloaded ZIP and choose Extract All.', result.stdout)
                    self.assertIn(game + '-3ds-builder.cmd from the extracted folder.', result.stdout)
                    self.assertNotIn('cannot find', result.stdout + result.stderr)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows cmd launcher')
    def test_windows_partial_runtime_is_refused_before_start(self):
        for missing in ('builder.py', 'runtime/python.exe', 'runtime/pythonw.exe'):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for relative in ('builder.py', 'runtime/python.exe', 'runtime/pythonw.exe'):
                    if relative != missing:
                        path = root / 'tools/release/builder' / relative
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(b'not executable')
                launcher = root / 'builder.cmd'
                launcher.write_bytes(package_builder.launcher('undertale', 'windows').encode('utf-8'))
                run = subprocess.run(['cmd.exe', '/d', '/c', str(launcher), '--help'],
                    stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW)
                self.assertEqual(run.returncode, 2, run.stdout + run.stderr)
                self.assertIn('Extract All', run.stdout)

    @unittest.skipUnless(sys.platform == 'win32', 'Windows packaged console launcher')
    def test_complete_windows_kit_forwards_arguments_and_the_python_exit_code(self):
        # A tiny console fixture using this test interpreter; no Tk or game files.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            builder = root / 'tools/release/builder'
            runtime = builder / 'runtime'
            runtime.mkdir(parents=True)
            shutil.copyfile(sys.executable, runtime / 'python.exe')
            version = 'python%d%d' % sys.version_info[:2]
            shutil.copyfile(Path(sys.base_prefix) / (version + '.dll'), runtime / (version + '.dll'))
            # Installed Python uses Lib; the embedded test runner uses pythonXY.zip.
            paths = [str(Path(sys.base_prefix) / (version + '.zip')), sysconfig.get_path('stdlib')]
            (runtime / (version + '._pth')).write_text('\n'.join(paths) + '\n', encoding='utf-8')
            (runtime / 'pythonw.exe').touch()  # This command-line route must never start it.
            (builder / 'builder.py').write_text('import sys\nprint(repr(sys.argv[1:]))\n'
                                               'raise SystemExit(37)\n', encoding='utf-8')
            launcher = root / 'builder.cmd'
            launcher.write_bytes(package_builder.launcher('undertale', 'windows').encode('utf-8'))
            run = subprocess.run(['cmd.exe', '/d', '/c', str(launcher), '--cli', '--folder',
                                  "C:/Fixture Game/O'Brien"], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW,
                env=dict(os.environ, ERRORLEVEL='0'))
            self.assertEqual(run.returncode, 37, run.stdout + run.stderr)
            self.assertIn(repr(['--game', 'undertale', '--cli', '--folder', "C:/Fixture Game/O'Brien"]), run.stdout)

    def test_unix_launcher_alone_explains_extraction_before_python(self):
        shell = shutil.which('sh')
        if not shell:
            self.skipTest('POSIX shell unavailable')
        for platform in ('linux', 'macos'):
            with self.subTest(platform=platform), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'builder.sh'
                path.write_text(package_builder.launcher('undertale', platform), encoding='utf-8', newline='\n')
                result = subprocess.run([shell, str(path)], stdin=subprocess.DEVNULL,
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                self.assertIn('Extract the whole builder download first.', result.stderr)
                self.assertIn('from the extracted folder.', result.stderr)

    def test_mac_app_launcher_alone_refuses_before_starting_bundled_python(self):
        shell = shutil.which('sh')
        if not shell:
            self.skipTest('POSIX shell unavailable')
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'Fixture.app/Contents/MacOS/builder-launcher'
            path.parent.mkdir(parents=True)
            path.write_text(macos_bundle.launcher('undertale'), encoding='utf-8', newline='\n')
            result = subprocess.run([shell, str(path), '--help'], stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('Extract the whole builder ZIP first.', result.stderr)
            self.assertIn('UNDERTALE 3DS Builder.app from the extracted folder.', result.stderr)
            self.assertNotIn('not found', result.stderr)


if __name__ == '__main__':
    unittest.main()
