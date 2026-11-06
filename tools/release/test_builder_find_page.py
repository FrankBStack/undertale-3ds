"""The game-folder page: a search still running must not replace a folder chosen by hand (outside audit DEEP-08,
2026-11-04). Headless page callbacks with invented folders; no window, no real search."""
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'builder'))
import gui


class Label:
    def __init__(self):
        self.text = ''

    def config(self, **kwargs):
        self.text = kwargs.get('text', self.text)


class Tree:
    def __init__(self):
        self.rows, self.selected = {}, ()

    def get_children(self):
        return list(self.rows)

    def delete(self, *ids):
        for i in ids:
            self.rows.pop(i, None)
        self.selected = ()

    def insert(self, parent, index, iid, values):
        self.rows[str(iid)] = values

    def selection_set(self, iid):
        self.selected = (str(iid),)

    def selection(self):
        return self.selected

    def item(self, iid, key):
        return self.rows[iid]


def copy(folder):
    return SimpleNamespace(store='Steam', folder=folder, version='v1', note='')


class FindPageTests(unittest.TestCase):
    def test_verified_bundle_pick_stays_selected_after_search_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / 'picked copy'
            resources = folder / 'UNDERTALE.app/Contents/Resources'
            resources.mkdir(parents=True)
            (resources / 'game.ios').write_bytes(b'invented Mac container')
            for pick in (folder / 'UNDERTALE.app', resources.parent, resources):
                with self.subTest(pick=pick.name):
                    self.page.add_manual(str(pick))
                    self.state.folder = str(folder)  # The successful verifier's normalized build folder.
                    self.page.search()
                    self.finish(len(self.jobs) - 1, [copy(str(Path(tmp) / 'other Steam copy'))])
                    self.assertEqual(self.state.folder, str(folder))
                    self.assertEqual(self.page.manual, [str(folder)])
                    self.assertEqual(self.page.tree.selection(), ('1',))
                    self.assertEqual(self.folders(), [str(Path(tmp) / 'other Steam copy'), str(folder)])

    def setUp(self):
        self.jobs = []
        app = SimpleNamespace(state=gui.State('undertale'), opts=SimpleNamespace(probes=None, folder=None),
                              theme=SimpleNamespace(load_from_game_dir=lambda folder: None), update_nav=lambda: None)
        app.work = lambda job, done, **kwargs: self.jobs.append((job, done))
        page = gui.FindPage.__new__(gui.FindPage)
        page.app, page.tree, page.status, page.intro = app, Tree(), Label(), Label()
        page.searching, page.searched_for = False, None
        page.search_generation, page.manual = 0, []
        self.page, self.state = page, app.state

    def finish(self, job, copies):
        self.jobs[job][1](copies)

    def folders(self):
        return [values[1] for values in self.page.tree.rows.values()]

    def test_source_column_says_found_in_with_the_existing_tree(self):
        def init(page, app):
            page.app, page.frame = app, mock.Mock()

        with mock.patch.object(gui.Page, '__init__', init), mock.patch.object(gui, 'label'), \
                mock.patch.object(gui, 'button'), mock.patch.object(gui.ttk, 'Frame'), \
                mock.patch.object(gui.ttk, 'Treeview') as tree:
            gui.FindPage(self.page.app)
        self.assertEqual(tree.call_args.kwargs['columns'], ('store', 'folder', 'version'))
        tree.return_value.heading.assert_any_call('store', text='Found in')

    def test_a_search_finishing_after_a_folder_is_chosen_keeps_that_choice(self):
        self.page.search()
        self.page.add_manual('C:/my-chosen-copy')
        self.assertEqual(self.state.folder, 'C:/my-chosen-copy')
        self.assertTrue(self.page.can_next())  # The choice ends the wait for the search.
        self.finish(0, [copy('C:/older-search-result')])
        self.assertEqual(self.state.folder, 'C:/my-chosen-copy')
        self.assertTrue(self.page.can_next())
        self.finish(0, [])  # An empty late result must not erase it either.
        self.assertEqual(self.state.folder, 'C:/my-chosen-copy')
        self.assertEqual(self.folders(), ['C:/my-chosen-copy'])

    def test_search_again_lists_its_copies_and_keeps_the_chosen_folder_selected(self):
        self.page.add_manual('C:/my-chosen-copy')
        self.page.search()
        self.assertFalse(self.page.can_next())
        self.finish(0, [copy('C:/steam-copy'), copy('C:/gog-copy')])
        self.assertEqual(self.folders(), ['C:/steam-copy', 'C:/gog-copy', 'C:/my-chosen-copy'])
        self.assertEqual(self.state.folder, 'C:/my-chosen-copy')
        self.assertTrue(self.page.can_next())

    def test_only_the_newest_search_counts(self):
        self.page.search()
        self.page.search()
        self.finish(0, [copy('C:/first-search')])
        self.assertTrue(self.page.busy())
        self.assertIsNone(self.state.folder)
        self.finish(1, [copy('C:/second-search')])
        self.assertFalse(self.page.busy())
        self.assertEqual(self.state.folder, 'C:/second-search')

    def test_a_search_with_no_choice_selects_the_first_copy_as_before(self):
        self.page.search()
        self.finish(0, [copy('C:/steam-copy'), copy('C:/gog-copy')])
        self.assertEqual(self.state.folder, 'C:/steam-copy')
        self.assertEqual(self.page.status.text, 'Found 2 copies.')
        self.page.search()
        self.finish(1, [])
        self.assertIn('was not found', self.page.status.text)
        self.assertFalse(self.page.can_next())


if __name__ == '__main__':
    unittest.main()
