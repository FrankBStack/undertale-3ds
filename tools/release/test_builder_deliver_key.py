"""A finished copy only counts for the build, game files and destination it copied (outside audit AUD-05,
2026-11-04). Headless page callbacks with invented builds; no window, card or console."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'builder'))
import deliver
import gui
from test_builder_card_names import Combo


class Var:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def artifact(sha):
    return SimpleNamespace(path='/fixture-work/out/game-o3ds.3dsx', sha256=sha, kind='3dsx')


class DeliveryKeyTests(unittest.TestCase):
    def setUp(self):
        state = gui.State('undertale')
        state.folder, state.artifacts = '/fixture-game', [artifact('a' * 64)]
        app = SimpleNamespace(state=state, opts=SimpleNamespace(work='/fixture-work'), update_nav=lambda: None,
                              boring=Var(False))
        app.work = lambda job, done, **kwargs: done(_run(job))
        page = gui.DeliverPage.__new__(gui.DeliverPage)
        page.app = app
        page.how, page.card, page.addr = Var('sd'), Var('E:/'), Var('192.0.2.7:5000')
        page.manual, page.copying, page.saved_key = None, False, None
        app.opts.autopilot = 'fixture'  # copy() goes straight to the copy, with no file list window.
        page.go, page.steps, page.open_files = mock.Mock(), mock.Mock(), mock.Mock()
        page.panels = {name: mock.Mock() for name in ('sd', 'wifi', 'files')}
        page.set_status, page.show_progress, page._show_status = mock.Mock(), mock.Mock(), mock.Mock()
        page.wifi_busy = lambda busy: setattr(page, 'copying', busy)
        page.cancelled = __import__('threading').Event()
        self.page, self.state = page, state

    def copy_sd(self, result=(1, 0, 10, SimpleNamespace(message='')), error=None):
        with mock.patch.object(deliver, 'copy_with_textures', return_value=result, side_effect=error), \
                mock.patch.object(deliver, 'dsp_missing', return_value=False):
            self.page.copying = True
            self.page._copy_approved('E:/', [], None)

    def send(self, error=None):
        with mock.patch.object(gui.ftp_delivery, 'send_product', return_value=SimpleNamespace(root='/x'),
                               side_effect=error), mock.patch.object(gui.preferences, 'save'):
            self.page.send()

    def back_and_return(self):
        self.page.mode()  # What the page decides on its own; on_show also forgets the copy (R175 F4).

    def test_a_rebuild_after_an_sd_copy_must_be_copied_again(self):
        self.copy_sd()
        self.back_and_return()
        self.assertTrue(self.page.can_next())
        self.state.artifacts = [artifact('b' * 64)]  # Back, other chapters or console, build again.
        self.back_and_return()
        self.assertFalse(self.page.can_next())
        self.copy_sd()
        self.assertTrue(self.page.can_next())

    def test_other_chapters_or_another_card_must_be_copied_again(self):
        self.copy_sd()
        self.state.parts = ['chapter1_windows']
        self.assertFalse(self.page.can_next())
        self.state.parts = None
        self.assertTrue(self.page.can_next())
        self.page.card.set('F:/')
        self.back_and_return()
        self.assertFalse(self.page.can_next())

    def test_a_failed_repeat_copy_does_not_keep_the_earlier_success(self):
        self.copy_sd()
        with mock.patch.object(self.page.app, 'work', lambda job, done, **kwargs: None):
            self.page.copy()  # The list is being prepared: the earlier success no longer counts.
        self.assertFalse(self.page.can_next())
        self.copy_sd(error=deliver.DeliverError('fixture card full'))
        self.assertFalse(self.page.can_next())

    def test_a_rebuild_after_a_wifi_send_must_be_sent_again(self):
        self.page.how.set('wifi')
        self.send()
        self.assertTrue(self.page.can_next())
        self.state.artifacts = [artifact('c' * 64)]
        self.back_and_return()
        self.assertFalse(self.page.can_next())
        self.page.addr.set('192.0.2.8:5000')
        self.send(error=deliver.DeliverError('fixture upload failed'))
        self.assertFalse(self.page.can_next())


class ReceiptIdentityTests(DeliveryKeyTests):
    """R175 F4: the reviewer's two cases, run through the page's own callbacks."""

    def setUp(self):
        super().setUp()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.game = Path(tmp.name) / 'game'
        (self.game / 'lang').mkdir(parents=True)
        (self.game / 'data.win').write_bytes(b'original game')
        (self.game / 'song_fixture.ogg').write_bytes(b'original music')
        (self.game / 'lang' / 'lang_en.json').write_bytes(b'{}')
        self.state.folder = str(self.game)

    def test_game_files_changed_at_the_same_path_must_be_copied_again(self):
        for name, data in (('data.win', b'changed bytes'), ('song_fixture.ogg', b'changed music'),
                           ('lang/lang_en.json', b'{"x": 1}'), ('song_new.ogg', b'added music')):
            with self.subTest(changed=name):
                self.copy_sd()
                self.back_and_return()
                self.assertTrue(self.page.can_next())
                path = self.game / name
                before = path.stat().st_mtime_ns if path.exists() else 0
                path.write_bytes(data)
                # A replacement comes seconds or more after the copy; Windows' file clock can lag 16 ms behind.
                os.utime(path, ns=(before + 10**9, before + 10**9))
                self.back_and_return()
                self.assertFalse(self.page.can_next())
        (self.game / 'song_new.ogg').unlink()
        self.copy_sd()
        self.assertTrue(self.page.can_next())
        (self.game / 'song_fixture.ogg').unlink()
        self.assertFalse(self.page.can_next())

    def test_a_rebuild_with_the_same_outputs_must_be_copied_or_sent_again(self):
        build = gui.BuildPage.__new__(gui.BuildPage)
        build.app, build.stop = self.page.app, __import__('threading').Event()
        build.log, build.intro, build.status, build.eta, build.bar = (mock.Mock() for _ in range(5))
        same = list(self.state.artifacts)
        for how in ('sd', 'wifi'):
            with self.subTest(how=how):
                self.page.how.set(how)
                self.copy_sd() if how == 'sd' else self.send()
                self.assertTrue(self.page.can_next())
                with mock.patch.object(gui.threading, 'Thread') as thread, \
                        mock.patch.object(gui.BuildPage, 'buttons'):
                    build.start()  # The worker never runs: only the start of a build matters here.
                thread.return_value.start.assert_called_once()
                self.state.artifacts = list(same)  # Rebuilt to the same executable.
                self.back_and_return()
                self.assertFalse(self.page.can_next())

    def test_checking_the_game_folder_again_must_be_copied_again(self):
        self.copy_sd()
        verify = gui.VerifyPage.__new__(gui.VerifyPage)
        verify.app, verify.bar, verify.render = self.page.app, mock.Mock(), mock.Mock()
        verify.done(SimpleNamespace(accepted=True, parts=['root']))  # Back to Check, same folder, checked again.
        self.assertIsNone(self.state.parts)
        self.back_and_return()
        self.assertFalse(self.page.can_next())

    def test_a_replacement_card_at_the_same_drive_must_be_copied_again(self):
        self.copy_sd()
        self.page.card, self.page.go = Combo(), mock.Mock()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[deliver.Card('E:/', 10**9, 'OTHER CARD')]):
            self.page.refresh()
        self.page.mode()
        self.assertFalse(self.page.can_next())
        self.copy_sd()
        self.assertTrue(self.page.can_next())

    def test_coming_back_to_the_page_or_finding_the_console_again_asks_again(self):
        self.copy_sd()
        self.page.card = Combo()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[deliver.Card('E:/', 10**9, 'SAME CARD')]):
            self.page.on_show()
        self.assertFalse(self.page.can_next())
        self.page.how.set('wifi')
        self.send()
        self.assertTrue(self.page.can_next())
        with mock.patch.object(self.page.app, 'root', create=True):
            self.page.find_console()
        self.page.copying = False  # The search is still running; its result doesn't matter here.
        self.assertFalse(self.page.can_next())

    def test_an_unreadable_subfolder_does_not_block_next_until_it_changes(self):
        real = gui.os.scandir

        def scandir(path):
            if Path(path).name == 'lang' and locked:
                raise PermissionError(13, 'fixture: no access')
            return real(path)
        locked = True
        with mock.patch.object(gui.os, 'scandir', side_effect=scandir):
            self.copy_sd()
            self.back_and_return()
            self.assertTrue(self.page.can_next())
            locked = False  # Readable again: what is inside may have changed, so copy again.
            self.assertFalse(self.page.can_next())

    def test_a_copy_finishing_after_a_refresh_does_not_count(self):
        # R175b F4, the reviewer's order: card A's copy finishes on the worker, card B replaces A at E:/ and Refresh
        # finds it, then A's completion reaches Tk. Next must stay off until B is copied.
        pending = []
        with mock.patch.object(self.page.app, 'work', side_effect=lambda job, done, **kwargs: pending.append(done)):
            self.copy_sd()
        self.page.card, self.page.go = Combo(), mock.Mock()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[deliver.Card('E:/', 10**9, 'OTHER CARD')]):
            self.page.refresh()
        with mock.patch.object(deliver, 'dsp_missing', return_value=False):
            pending.pop()((1, 0, 10, SimpleNamespace(message='')))
        self.assertFalse(self.page.copying)
        self.assertFalse(self.page.can_next())
        self.assertFalse(self.state.delivered)
        self.assertIn(gui.STALE_COPY, self.page.set_status.call_args[0][1])
        self.copy_sd()  # Copying to B counts.
        self.assertTrue(self.page.can_next())

    def test_a_copy_started_before_choose_folder_or_a_new_visit_does_not_count(self):
        for name, invalidate in (('choose folder', lambda: self.page.set_manual('F:/chosen')),
                                 ('new visit', self.page.on_show)):
            with self.subTest(event=name):
                self.page.manual = None
                self.page.card, self.page.go = Combo(), mock.Mock()
                with mock.patch.object(deliver, 'list_sd_cards', return_value=[deliver.Card('E:/', 10**9, 'A')]):
                    self.page.refresh()
                pending = []
                with mock.patch.object(self.page.app, 'work',
                                       side_effect=lambda job, done, **kwargs: pending.append(done)):
                    self.page.copy()  # The file list is prepared...
                    pending.pop()(([], None, ''))  # ...and, in autopilot, the copy starts at once.
                with mock.patch.object(deliver, 'list_sd_cards', return_value=[deliver.Card('E:/', 10**9, 'A')]):
                    invalidate()
                self.page.card.set('E:/  A (1000 MB free)')
                with mock.patch.object(deliver, 'dsp_missing', return_value=False):
                    pending.pop()((1, 0, 10, SimpleNamespace(message='')))
                self.page.mode()
                self.assertFalse(self.page.can_next())

    def test_a_send_or_save_finishing_after_a_new_visit_does_not_count(self):
        pending = []
        work = lambda job, done, **kwargs: pending.append(done)
        self.page.how.set('wifi')
        with mock.patch.object(self.page.app, 'work', side_effect=work):
            self.page.send()
        self.page.forget()  # What on_show does on the next visit.
        with mock.patch.object(gui.preferences, 'save'):
            pending.pop()(SimpleNamespace(root='/x'))
        self.assertFalse(self.page.can_next())
        self.page.how.set('files')
        self.page.save = mock.Mock()
        with mock.patch.object(self.page.app, 'work', side_effect=work):
            self.page.save_files()
        self.page.forget()
        pending.pop()(SimpleNamespace(folder='/fixture-out', root='/fixture-out', files=1, bytes=1,
                                      textures=SimpleNamespace(message='')))
        self.assertFalse(self.page.can_next())
        self.assertIsNone(self.page.saved_key)

    def test_an_unchanged_page_still_allows_next(self):
        self.copy_sd()
        for _ in range(3):
            self.back_and_return()
            self.assertTrue(self.page.can_next())

    def save(self, work=None, error=None):
        result = SimpleNamespace(folder='/fixture-out', root='/fixture-out', files=1, bytes=1,
                                 textures=SimpleNamespace(message=''))
        self.page.how.set('files')
        self.page.save = mock.Mock()
        with mock.patch.object(deliver, 'save_files', return_value=result, side_effect=error), \
                mock.patch.object(self.page.app, 'work', side_effect=work or self.page.app.work):
            self.page.save_files()
        return result

    def test_a_saved_folder_needs_saving_again_on_a_new_visit(self):
        # R175c, the reviewer's first order: a successful save, then a new visit to the page.
        self.save()
        self.page.mode()
        self.assertTrue(self.page.can_next())
        self.page.card = Combo()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[]):
            self.page.on_show()
        self.assertIsNone(self.page.saved_key)
        self.assertFalse(self.page.can_next())
        self.save()  # Saving again counts.
        self.assertTrue(self.page.can_next())

    def test_an_earlier_save_does_not_count_for_a_stale_or_failed_later_one(self):
        # R175c, the reviewer's second order: an earlier success, another save started, forget(), then its
        # completion. The earlier key must not enable Next either; nor after a failed later save.
        self.save()
        pending = []
        result = self.save(work=lambda job, done, **kwargs: pending.append((job, done)))
        self.page.forget()
        pending.pop()[1](result)
        self.assertFalse(self.page.can_next())
        self.save()
        self.assertTrue(self.page.can_next())
        self.save(error=deliver.DeliverError('fixture disk full'))
        self.assertFalse(self.page.can_next())

    def test_a_saved_folder_follows_the_same_inputs(self):
        result = SimpleNamespace(folder='/fixture-out', root='/fixture-out', files=1, bytes=1,
                                 textures=SimpleNamespace(message=''))
        self.page.how.set('files')
        self.page.save = mock.Mock()
        with mock.patch.object(deliver, 'save_files', return_value=result):
            self.page.save_files()
        self.assertTrue(self.page.can_next())
        (self.game / 'data.win').write_bytes(b'changed bytes')
        self.page.mode()
        self.assertFalse(self.page.can_next())


def _run(job):
    try:
        return job()
    except Exception as exc:
        return exc


if __name__ == '__main__':
    unittest.main()
