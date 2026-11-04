"""The Mac app's Finder launcher and runtime check carry on when the home Library cannot be written
(scour SCOURS1-004, 2026-11-04). A child Python runs the packed launcher text with an invented home folder;
no Mac, window or game files."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import macos_bundle as bundle
import macos_runtime_check as runtime_check


class LauncherLogTests(unittest.TestCase):
    def launch(self, home):
        resources = home.parent / 'Fixture.app/Contents/Resources'
        builder = resources / 'builder/tools/release/builder/builder.py'
        builder.parent.mkdir(parents=True)
        builder.write_text('import sys\nprint("PASS", sys.argv[1:])\n', encoding='utf-8')
        boot = resources / 'app_bootstrap.py'
        boot.write_text(bundle.BOOTSTRAP, encoding='utf-8')
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
        # No --cli/--dry-run: the Finder path, which sends output to the launcher log.
        return subprocess.run([sys.executable, '-I', '-B', str(boot), 'fixture-arg'], env=env,
                              stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30)

    def test_a_writable_home_gets_the_launcher_log(self):
        with tempfile.TemporaryDirectory(prefix='launcher-home-') as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            run = self.launch(home)
            self.assertEqual(run.returncode, 0, run.stderr)
            log = (home / 'Library/Logs/3DS Builder/launcher.log').read_text(encoding='utf-8')
            self.assertIn('Bundled Python:', log)
            self.assertIn("PASS ['fixture-arg']", log)

    def test_an_unwritable_logs_folder_still_starts_the_builder(self):
        with tempfile.TemporaryDirectory(prefix='launcher-home-') as tmp:
            home = Path(tmp) / 'home'
            home.mkdir()
            (home / 'Library').write_text('not a folder', encoding='utf-8')  # mkdir fails as on a read-only home.
            run = self.launch(home)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertIn("PASS ['fixture-arg']", run.stdout)


class RuntimeCheckReportTests(unittest.TestCase):
    def test_the_report_is_saved_for_support(self):
        with tempfile.TemporaryDirectory(prefix='runtime-home-') as tmp:
            runtime_check.save_report({'passed': True}, home=tmp)
            saved = Path(tmp) / 'Library/Logs/3DS Builder/runtime-check.json'
            self.assertEqual(json.loads(saved.read_text(encoding='utf-8')), {'passed': True})

    def test_an_unwritable_home_does_not_stop_the_check(self):
        with tempfile.TemporaryDirectory(prefix='runtime-home-') as tmp:
            (Path(tmp) / 'Library').write_text('not a folder', encoding='utf-8')
            with mock.patch('sys.stderr', new_callable=io.StringIO) as err:
                runtime_check.save_report({'passed': True}, home=tmp)
            self.assertIn('Could not save runtime-check.json', err.getvalue())


if __name__ == '__main__':
    unittest.main()
