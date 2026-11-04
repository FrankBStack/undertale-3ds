"""A confirmed Cancel on the Build page stops every model still to build (outside audit AUD-14, 2026-11-04).
Headless page callbacks with invented builds; no window, compiler or console."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'builder'))
import gui
import pipeline


class Widget:
    def config(self, *args, **kwargs):
        pass


class BuildCancelTests(unittest.TestCase):
    def setUp(self):
        self.built, self.cancelled, self.finished = [], [], []
        self.on_post = lambda fn, args: None
        state = gui.State('undertale')
        state.targets, state.folder, state.tc = ['n3ds', 'o3ds'], '/fixture-game', None
        state.verdict = SimpleNamespace(result=SimpleNamespace(store='steam'))
        page = gui.BuildPage.__new__(gui.BuildPage)
        page.intro, page.line, page.progress = Widget(), lambda value: None, lambda value: None
        page.build, page.log_path, page.running = None, None, True
        page.stop = __import__('threading').Event()
        page.finished = lambda err: self.finished.append(err)
        page.app = SimpleNamespace(state=state, opts=SimpleNamespace(work='/fixture-work'), call=self.call)
        self.page, self.state = page, state
        test = self

        class FakeBuild:
            def __init__(self, product, tc, work, target, folder, **kwargs):
                self.target, self.log_path, self.stopped = target, 'fixture-%s.log' % target, False

            def run(self):
                test.built.append(self.target)
                test.on_run(self)
                if self.stopped:
                    raise pipeline.BuildFailed('The build was cancelled.', self.log_path)
                return [], {'target': self.target}

            def cancel(self):
                self.stopped = True
                test.cancelled.append(self.target)

        self.on_run = lambda build: None
        self.patches = [mock.patch.object(pipeline, 'Build', FakeBuild),
                        mock.patch.object(gui.messagebox, 'askyesno', return_value=True)]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def call(self, fn, *args):
        self.on_post(fn, args)
        fn(*args)

    def run_worker(self):
        self.page.worker()
        self.assertEqual(len(self.finished), 1)
        return self.finished[0]

    def test_cancel_at_the_handoff_between_models_stops_the_second(self):
        # The Tk thread handles Cancel after the first build returned and the second title was posted,
        # before the worker replaced self.build: the audit's handoff window.
        def handoff(fn, args):
            if fn == self.page.intro.config and self.built == ['n3ds']:
                self.page.cancel()
        self.on_post = handoff
        err = self.run_worker()
        self.assertEqual(self.built, ['n3ds'])
        self.assertIsInstance(err, pipeline.BuildFailed)
        self.assertIn('cancelled', str(err))
        self.assertEqual(err.log_path, 'fixture-o3ds.log')

    def test_cancel_before_the_first_build_exists_is_not_ignored(self):
        def early(fn, args):
            if fn == self.page.intro.config and not self.built:
                self.page.cancel()
        self.on_post = early
        err = self.run_worker()
        self.assertEqual(self.built, [])
        self.assertIsInstance(err, pipeline.BuildFailed)

    def test_cancel_during_a_build_stops_it_and_the_next(self):
        self.on_run = lambda build: self.page.cancel() if build.target == 'n3ds' else None
        err = self.run_worker()
        self.assertEqual((self.built, self.cancelled), (['n3ds'], ['n3ds']))
        self.assertIsInstance(err, pipeline.BuildFailed)

    def test_a_declined_cancel_builds_every_model(self):
        with mock.patch.object(gui.messagebox, 'askyesno', return_value=False):
            self.on_run = lambda build: self.page.cancel()
            self.assertIsNone(self.run_worker())
        self.assertEqual((self.built, self.cancelled), (['n3ds', 'o3ds'], []))

    def test_try_again_clears_an_earlier_cancel(self):
        page = self.page
        page.stop.set()
        for name in ('log', 'intro', 'status', 'eta', 'bar'):
            setattr(page, name, mock.Mock())
        page.buttons = mock.Mock()
        page.app.update_nav = lambda: None
        with mock.patch.object(gui.threading, 'Thread') as thread:
            page.start()
        self.assertFalse(page.stop.is_set())
        thread.return_value.start.assert_called_once()

    def test_cancel_when_nothing_is_running_does_nothing(self):
        self.page.running = False
        with mock.patch.object(gui.messagebox, 'askyesno') as ask:
            self.page.cancel()
        ask.assert_not_called()
        self.assertFalse(self.page.stop.is_set())


if __name__ == '__main__':
    unittest.main()
