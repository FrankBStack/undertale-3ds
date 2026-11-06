"""SCOURSOL4-002: after a refused game check, a repaired game is checked again. Invented Steam files only, with the
real verifier and the real page callbacks; Tk widgets are mocks and no window opens."""
import hashlib
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE/'builder'), str(HERE)]
import discover
import gui
import products
from test_verify_game import Tree, row

DATA = b'invented recognized container'
MUSIC = b'invented music bytes'
ALLOW = [row('undertale', 'root', DATA)]


class VerifyRetryTests(unittest.TestCase):

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        tree = Tree(temp.name)
        self.folder = tree.install('391540', 'Undertale', {'data.win': DATA, 'credits.txt': b'invented credits'})
        self.data, self.music = Path(self.folder)/'data.win', Path(self.folder)/'fixture.ogg'
        self.music.write_bytes(MUSIC)
        self.probes = discover.Probes(steam_roots=[tree.root], gog_dirs=[], platform='win32')
        manifest = [{'name': self.music.name, 'size': len(MUSIC), 'sha256': hashlib.sha256(MUSIC).hexdigest()}]
        patch = mock.patch.object(products, 'load_music_manifest', return_value=manifest)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(products, 'load_credits_manifest', return_value=dict(
            name='credits.txt', size=len(b'invented credits'),
            sha256=hashlib.sha256(b'invented credits').hexdigest()))
        patch.start()
        self.addCleanup(patch.stop)
        real = discover.verify_copy
        self.verify = mock.Mock(side_effect=lambda game, folder, probes: real(game, folder, probes, allow_list=ALLOW))
        patch = mock.patch.object(discover, 'verify_copy', self.verify)
        patch.start()
        self.addCleanup(patch.stop)
        patch = mock.patch.object(discover, 'find_copies',
                                  side_effect=lambda game, probes: [discover.Copy('Steam', self.folder, 'fixture')])
        patch.start()
        self.addCleanup(patch.stop)

        self.state = gui.State('undertale')
        self.app = SimpleNamespace(state=self.state, opts=SimpleNamespace(probes=self.probes, folder=None,
                                                                          autopilot=None),
                                   update_nav=mock.Mock(), theme=mock.Mock())
        self.app.work = mock.Mock(side_effect=lambda job, after: after(job()))
        find = self.find = gui.FindPage.__new__(gui.FindPage)
        find.app, find.tree, find.status, find.intro = self.app, mock.Mock(), mock.Mock(), mock.Mock()
        find.manual, find.search_generation, find.searching, find.searched_for = [], 0, False, None
        find.tree.get_children.return_value = ('0',)
        find.tree.selection.return_value = ('0',)
        find.tree.item.return_value = ('Steam', self.folder, 'fixture version')
        check = self.check = gui.VerifyPage.__new__(gui.VerifyPage)
        check.app, check.running = self.app, False
        check.intro, check.result, check.details, check.bar, check.links = (mock.Mock() for _ in range(5))
        check.links.winfo_children.return_value = []
        check.render = mock.Mock()

    def first_visit(self):
        """Find the game, then Next: the check runs once."""
        self.find.on_show()
        self.assertEqual(self.state.folder, self.folder)
        self.check.on_show()
        self.assertEqual(self.verify.call_count, 1)
        self.verify.reset_mock()
        return self.state.verdict

    def break_game(self, missing):
        (self.data if missing == 'data' else self.music).unlink()

    def repair(self):
        self.data.write_bytes(DATA)
        self.music.write_bytes(MUSIC)

    def assert_checked_once_and_accepted(self):
        self.assertEqual(self.verify.call_count, 1, 'the repaired game must be checked again')
        self.assertTrue(self.state.verdict.accepted)
        self.assertTrue(self.check.can_next())

    def search_again_after_repair(self, missing):
        # The reviewer's order (change-scoursol4 test_verification_retry.py): Back, Search again, Next.
        self.break_game(missing)
        self.assertFalse(self.first_visit().accepted)
        self.repair()
        self.find.search()
        self.assertEqual(self.state.folder, self.folder)
        self.assertTrue(self.find.can_next())
        self.check.on_show()
        self.assert_checked_once_and_accepted()

    def test_search_again_after_restoring_data_win_checks_the_same_folder_again(self):
        self.search_again_after_repair('data')

    def test_search_again_after_restoring_the_music_checks_the_same_folder_again(self):
        self.search_again_after_repair('music')

    def test_back_and_next_after_a_repair_checks_again(self):
        self.break_game('data')
        self.assertFalse(self.first_visit().accepted)
        self.repair()
        self.check.on_show()  # Back, then Next, with no new search.
        self.assert_checked_once_and_accepted()

    def test_choosing_the_same_folder_by_hand_checks_it_again(self):
        self.break_game('music')
        self.assertFalse(self.first_visit().accepted)
        self.repair()
        self.find.add_manual(self.folder)
        self.check.on_show()
        self.assert_checked_once_and_accepted()

    def test_a_game_still_broken_is_refused_again(self):
        self.break_game('data')
        self.assertFalse(self.first_visit().accepted)
        self.check.on_show()
        self.assertEqual(self.verify.call_count, 1)
        self.assertFalse(self.state.verdict.accepted)
        self.assertFalse(self.check.can_next())

    def test_an_accepted_game_is_not_checked_again_on_back_and_next(self):
        self.assertTrue(self.first_visit().accepted)
        inputs = self.state.inputs
        self.check.on_show()
        self.assertEqual(self.verify.call_count, 0)
        self.assertEqual(self.state.inputs, inputs)
        self.check.render.assert_called()

    def test_search_again_checks_an_accepted_game_again_and_makes_earlier_copies_stale(self):
        self.assertTrue(self.first_visit().accepted)
        inputs = self.state.inputs
        self.find.search()
        self.assertIsNone(self.state.verdict)
        self.assertGreater(self.state.inputs, inputs)
        self.assertFalse(self.check.can_next())
        self.check.on_show()
        self.assert_checked_once_and_accepted()


if __name__ == '__main__':
    unittest.main()
