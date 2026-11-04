"""A listed SD card is copied to its own root even when its name holds two spaces (scour SCOURS1-003,
2026-11-04). Headless page callbacks with invented cards; no window or card."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'builder'))
import deliver
import gui


class Combo:
    def __init__(self):
        self.values, self.value = [], ''

    def config(self, values):
        self.values = values

    def current(self, index):
        self.value = self.values[index]

    def set(self, value):
        self.value = value

    def get(self):
        return self.value


CARDS = [deliver.Card('/Volumes/SD  CARD', 900 * 10**6, 'SD  CARD'),
         deliver.Card('/media/fixture/3DS  SD  2', 800 * 10**6, '')]


class CardNameTests(unittest.TestCase):
    def page(self, cards):
        page = gui.DeliverPage.__new__(gui.DeliverPage)
        page.app = SimpleNamespace(state=gui.State('undertale'))  # refresh() forgets an SD copy (R175 F4).
        page.card, page.manual, page.copying = Combo(), None, False
        page.go, page.set_status = mock.Mock(), mock.Mock()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=cards):
            page.refresh()
        return page

    def test_each_listed_card_gives_back_its_own_root(self):
        page = self.page(CARDS)
        for index, card in enumerate(CARDS):
            with self.subTest(root=card.root):
                page.card.current(index)
                self.assertEqual(page.target_root(), card.root)

    def test_card_discovery_really_lists_such_a_root(self):
        import tempfile
        with tempfile.TemporaryDirectory(prefix='volumes-') as base:
            (Path(base) / 'SD  CARD' / '3ds').mkdir(parents=True)
            cards = deliver.list_sd_cards(platform='darwin', roots=[base], mounts=None)
            self.assertEqual([c.root for c in cards], [str(Path(base) / 'SD  CARD')])
            page = self.page(cards)
            self.assertEqual(page.target_root(), cards[0].root)

    def test_ordinary_names_and_a_chosen_folder_are_unchanged(self):
        page = self.page([deliver.Card('E:\\', 10**9, 'SDCARD')])
        self.assertEqual(page.card.get(), 'E:\\  SDCARD (1000 MB free)')
        self.assertEqual(page.target_root(), 'E:\\')
        page.manual = '/fixture/chosen  folder'
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[]):
            page.refresh()
        self.assertEqual(page.target_root(), '/fixture/chosen  folder')

    def test_a_refresh_forgets_cards_that_were_removed(self):
        page = self.page(CARDS)
        page.card.current(0)
        listed = page.card.get()
        with mock.patch.object(deliver, 'list_sd_cards', return_value=[]):
            page.refresh()
        self.assertNotIn(listed, page.card_roots)
        self.assertIsNone(page.target_root())


if __name__ == '__main__':
    unittest.main()
