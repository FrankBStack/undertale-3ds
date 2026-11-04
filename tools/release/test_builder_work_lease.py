"""Two builders must not share one work folder (outside audit AUD-15, 2026-11-04). A second builder process
stops before it touches the folder; a builder that crashed never blocks the next. Invented folders and a child
Python process only; no window, compiler, card or console."""
import contextlib
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'builder'))
import builder
import gui
import pipeline
import sd_transaction

HOLDER = r'''
import sys
sys.path.insert(0, sys.argv[1])
import pipeline
lease = pipeline.claim_work(sys.argv[2])
print('HELD' if lease is not None and lease.held else 'NONE', flush=True)
sys.stdin.readline()
'''


class HeldElsewhere:
    """Another builder process holding the work folder, ended normally or killed like a crash."""

    def __init__(self, work):
        self.proc = subprocess.Popen([sys.executable, '-B', '-I', '-c', HOLDER, str(HERE / 'builder'), str(work)],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.ready = self.proc.stdout.readline().strip()

    def end(self, crash=False):
        if crash:
            self.proc.kill()
        else:
            self.proc.stdin.write('\n')
            self.proc.stdin.flush()
        self.proc.wait(timeout=30)
        self.proc.stdin.close()
        self.proc.stdout.close()


class WorkLeaseTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='builder-work-lease-')
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name) / 'w'

    def hold(self):
        other = HeldElsewhere(self.work)
        self.addCleanup(lambda: other.proc.poll() is not None or other.end(crash=True))
        self.assertEqual(other.ready, 'HELD')
        return other

    def test_a_second_process_is_refused_until_the_first_ends(self):
        for crash in (False, True):
            with self.subTest(crash=crash):
                other = self.hold()
                with self.assertRaises(pipeline.WorkBusy) as caught:
                    pipeline.claim_work(str(self.work))
                self.assertEqual(str(caught.exception), pipeline.WORK_BUSY % self.work)
                other.end(crash=crash)
                lease = pipeline.claim_work(str(self.work))
                self.assertTrue(lease.held)
                lease.release()

    def test_the_same_process_cannot_claim_twice_and_release_frees_it(self):
        lease = pipeline.claim_work(str(self.work))
        with self.assertRaises(pipeline.WorkBusy):
            pipeline.claim_work(str(self.work))
        lease.release()
        self.assertFalse((self.work / pipeline.WORK_LEASE).exists())
        pipeline.claim_work(str(self.work)).release()

    def test_other_work_folders_are_independent(self):
        self.hold()
        other = self.work.parent / 'other'
        lease = pipeline.claim_work(str(other))
        self.assertTrue(lease.held)
        lease.release()

    def test_a_folder_without_file_locks_is_refused(self):
        # R175 F1: no cross-process lock means no build, on the command line and in the window.
        from test_builder_sd_lease import no_os_locks
        with no_os_locks():
            with self.assertRaises(pipeline.WorkLockError) as caught:
                pipeline.claim_work(str(self.work))
            self.assertNotIsInstance(caught.exception, pipeline.WorkBusy)
            self.assertEqual(str(caught.exception), pipeline.WORK_NO_LOCK % self.work)
            options = builder.parse(['--cli', '--folder', '/fixture-game', '--work', str(self.work)])
            verdict = mock.Mock(accepted=True, message='checked', parts=['root'])
            lines = []
            with mock.patch.object(builder.discover, 'verify_copy', return_value=verdict), \
                    mock.patch.object(builder.toolchain, 'detect') as detect:
                self.assertEqual(builder.cli(options, out=lines.append), 1)
            detect.assert_not_called()
            self.assertEqual(lines[-1], pipeline.WORK_NO_LOCK % self.work)
            root = mock.Mock()
            with mock.patch.object(gui.tk, 'Tk', return_value=root), mock.patch.object(gui, 'App') as app, \
                    mock.patch.object(gui.messagebox, 'showerror') as shown, \
                    mock.patch('sys.stderr', new_callable=__import__('io').StringIO):
                self.assertEqual(gui.run(gui.Options(work=str(self.work))), 1)
            app.assert_not_called()
            shown.assert_called_once_with("Builder can't start", pipeline.WINDOW_NO_LOCK % self.work, parent=root)
            # The window can't choose a work folder: it says so and points to --work on a command line, and doesn't
            # ask the player to move the folder (the next launch would use the same path).
            self.assertIn("This window can't choose another work folder", pipeline.WINDOW_NO_LOCK)
            self.assertIn('from a command line with --work', pipeline.WINDOW_NO_LOCK)
            self.assertNotIn('make it a folder', pipeline.WINDOW_NO_LOCK)
            self.assertIn('--work', pipeline.WORK_NO_LOCK)
        self.assertFalse((self.work / 'src').exists())

    def test_any_other_lock_error_stops_the_builder(self):
        # R175 F3: the reviewer's case is a writable work folder whose lock path is a directory; both claims used to
        # return None and the build ran unlocked. A folder that can't be made or a lock file that can't be opened
        # stops the builder the same way, with the folder and the reason, and is not reported as "already open".
        def directory():
            (self.work / pipeline.WORK_LEASE).mkdir(parents=True)
            return contextlib.nullcontext()
        def unwritable():
            return mock.patch.object(pipeline.os, 'makedirs', side_effect=PermissionError(13, 'Permission denied'))
        def unopenable():
            return mock.patch.object(sd_transaction, 'open', create=True,
                                     side_effect=OSError(5, 'Input/output error'))
        for name, setup in (('lock path is a directory', directory), ('folder cannot be made', unwritable),
                            ('lock file cannot be opened', unopenable)):
            with self.subTest(case=name), setup():
                for _ in range(2):
                    with self.assertRaises(pipeline.WorkLockError) as caught:
                        pipeline.claim_work(str(self.work))
                    self.assertNotIsInstance(caught.exception, pipeline.WorkBusy)
                    message, window = str(caught.exception), caught.exception.window
                    self.assertTrue(message.startswith("Can't use the work folder %s (" % self.work), message)
                    self.assertTrue(message.endswith(pipeline.WORK_LOCK_ERROR.split('\n')[1]), message)
                    self.assertIn('--work', message)
                    self.assertTrue(window.startswith("The builder can't use its work folder %s (" % self.work))
                    self.assertTrue(window.endswith(pipeline.WINDOW_LOCK_ERROR.split('\n')[1]), window)
                    self.assertNotIn('--work', window)
                options = builder.parse(['--cli', '--folder', '/fixture-game', '--work', str(self.work)])
                verdict = mock.Mock(accepted=True, message='checked', parts=['root'])
                lines = []
                with mock.patch.object(builder.discover, 'verify_copy', return_value=verdict), \
                        mock.patch.object(builder.toolchain, 'detect') as detect:
                    self.assertEqual(builder.cli(options, out=lines.append), 1)
                detect.assert_not_called()
                self.assertEqual(lines[-1], message)
                root = mock.Mock()
                with mock.patch.object(gui.tk, 'Tk', return_value=root), mock.patch.object(gui, 'App') as app, \
                        mock.patch.object(gui.messagebox, 'showerror') as shown, \
                        mock.patch('sys.stderr', new_callable=__import__('io').StringIO):
                    self.assertEqual(gui.run(gui.Options(work=str(self.work))), 1)
                app.assert_not_called()
                shown.assert_called_once_with("Builder can't start", window, parent=root)
            self.assertFalse((self.work / 'src').exists())
            if (self.work / pipeline.WORK_LEASE).is_dir():
                (self.work / pipeline.WORK_LEASE).rmdir()

    def test_cli_stops_before_touching_the_work_folder(self):
        self.hold()
        options = builder.parse(['--cli', '--folder', '/fixture-game', '--work', str(self.work)])
        verdict = mock.Mock(accepted=True, message='checked', parts=['root'])
        lines = []
        with mock.patch.object(builder.discover, 'verify_copy', return_value=verdict), \
                mock.patch.object(builder.toolchain, 'detect') as detect, \
                mock.patch.object(builder.pipeline, 'Build') as build:
            self.assertEqual(builder.cli(options, out=lines.append), 1)
        detect.assert_not_called()
        build.assert_not_called()
        self.assertEqual(lines[-1], pipeline.WORK_BUSY % self.work)

    def test_cli_releases_the_folder_when_it_finishes(self):
        options = builder.parse(['--cli', '--folder', '/fixture-game', '--work', str(self.work)])
        verdict = mock.Mock(accepted=True, message='checked', parts=['root'])
        tc = mock.Mock(can_build=False, checks=[])
        with mock.patch.object(builder.discover, 'verify_copy', return_value=verdict), \
                mock.patch.object(builder.toolchain, 'detect', return_value=tc):
            self.assertEqual(builder.cli(options, out=lambda line: None), 1)
        pipeline.claim_work(str(self.work)).release()

    def test_a_second_window_explains_and_never_opens_the_wizard(self):
        self.hold()
        root = mock.Mock()
        with mock.patch.object(gui.tk, 'Tk', return_value=root), mock.patch.object(gui, 'App') as app, \
                mock.patch.object(gui.messagebox, 'showerror') as shown, \
                mock.patch('sys.stderr', new_callable=__import__('io').StringIO):
            self.assertEqual(gui.run(gui.Options(work=str(self.work))), 1)
        app.assert_not_called()
        shown.assert_called_once_with('Builder already open', pipeline.WORK_BUSY % self.work, parent=root)
        root.destroy.assert_called_once()

    def test_a_window_holds_the_folder_until_it_closes(self):
        root, app = mock.Mock(), mock.Mock(exit_code=0)

        def mainloop():
            with self.assertRaises(pipeline.WorkBusy):
                pipeline.claim_work(str(self.work))
        root.mainloop.side_effect = mainloop
        with mock.patch.object(gui.tk, 'Tk', return_value=root), mock.patch.object(gui, 'App', return_value=app):
            self.assertEqual(gui.run(gui.Options(work=str(self.work))), 0)
        root.mainloop.assert_called_once()
        pipeline.claim_work(str(self.work)).release()


if __name__ == '__main__':
    unittest.main()
