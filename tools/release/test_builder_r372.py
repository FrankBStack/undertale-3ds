"""R372 regressions use invented game folders and isolated host lookups only."""
from pathlib import Path
import os
from types import SimpleNamespace
from unittest import mock
import unittest

import test_builder as fixtures
import gui
import toolchain
from gui_test_support import isolated_builder_host


class ManualHarnessSafetyTests(unittest.TestCase):
    def test_polish_harness_isolates_lookups_before_app_construction_without_pytest(self):
        import test_builder_polish as polish
        before = gui.deliver.list_sd_cards
        case = polish.PolishGuiTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        self.assertIsNot(gui.deliver.list_sd_cards, before)
        root = Path(case.tmp) / 'isolated-polish-host'
        self.assertEqual(Path(os.environ['LOCALAPPDATA']), root / 'local')
        self.assertEqual(gui.deliver.list_sd_cards(), [])


class ReviewGuiTests(unittest.TestCase):
    tearDown = fixtures.GuiTest.tearDown
    wizard = fixtures.BuilderUiTest.wizard
    toolchain_fixture = fixtures.BuilderUiTest.toolchain_fixture
    open_toolchain_page = fixtures.BuilderUiTest.open_toolchain_page

    def setUp(self):
        fixtures.GuiTest.setUp(self)
        guard = isolated_builder_host(Path(self.tmp) / 'empty-review-host')
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)

    def completed(self, app):
        app.state.artifacts = [SimpleNamespace(path='fixture.3dsx', kind='3dsx', size=4)]
        app.state.records = [dict(target='n3ds', seconds=1)]
        app.pages[5].finished(None)
        self.assertTrue(app.state.build_ok)

    def test_choosing_another_game_folder_discards_the_finished_build(self):
        app = self.wizard()
        self.completed(app)
        page = app.pages[1]
        folder = str(Path(self.tmp) / 'other-game')
        row = page.tree.insert('', 'end', values=('Folder', folder, 'Not checked yet'))
        page.tree.selection_set(row)
        with mock.patch.object(app.theme, 'load_from_game_dir'):
            page.picked()
        self.assertFalse(app.state.build_ok)
        self.assertEqual(app.state.artifacts, [])
        with mock.patch.object(app.pages[5], 'start') as start:
            app.show(4)
            app.next()
            start.assert_called_once()

    def test_rechecking_the_same_game_folder_discards_the_finished_build(self):
        app = self.wizard()
        app.state.verdict = object()
        self.completed(app)
        app.pages[1].forget_check()
        self.assertFalse(app.state.build_ok)
        self.assertEqual(app.state.artifacts, [])

    def test_new_verification_discards_the_finished_build(self):
        app = self.wizard()
        self.completed(app)
        verdict = SimpleNamespace(accepted=False)
        with mock.patch.object(app.pages[2], 'render'):
            app.pages[2].done(verdict)
        self.assertFalse(app.state.build_ok)
        self.assertEqual(app.state.artifacts, [])

    def test_a_changed_toolchain_cannot_reuse_the_finished_build(self):
        app = self.wizard()
        app.state.tc = SimpleNamespace(root='fixture-tools', compiler_info={'version': '1'})
        self.completed(app)
        app.state.tc.compiler_info['version'] = '2'
        with mock.patch.object(app.pages[5], 'start') as start:
            app.show(5)
            start.assert_called_once()
        self.assertFalse(app.state.build_ok)

    def test_done_names_the_card_or_console_that_received_the_saves(self):
        app = self.wizard()
        state = app.state
        for mode in ('sd', 'wifi'):
            with self.subTest(mode=mode):
                state.deliver_how = mode
                state.sd_root = str(Path(self.tmp) / 'game-card') if mode == 'sd' else None
                state.ftp_console = '127.0.0.1:10001'
                state.save_how = mode
                state.save_destination = (str(Path(self.tmp) / 'save-card') if mode == 'sd'
                                          else '127.0.0.1:10002')
                state.save_result = SimpleNamespace(copied=4, backup_dir=None)
                state.save_receipt = state.delivery_context(), state.save_how, state.save_destination
                app.show(8)
                line = next(line for line in app.page.summary_label.cget('text').splitlines()
                            if line.startswith('PC saves:'))
                self.assertIn(state.save_destination, line)
                self.assertNotIn(state.sd_root or state.ftp_console, line)

    def test_recommended_tools_do_not_claim_that_next_is_grey(self):
        app = self.wizard()
        tc = self.toolchain_fixture()
        tc.missing_recommended = [toolchain.RECOMMENDED_PACKAGES[0]]
        self.open_toolchain_page(app, tc)
        page = app.page
        self.assertTrue(page.can_next())
        self.assertNotIn('Next stays grey', page.compiler_status.cget('text'))
        self.assertIn('Next to continue', page.compiler_status.cget('text'))
        rows = {page.tree.item(row, 'values')[1]: page.tree.item(row, 'values')[0]
                for row in page.tree.get_children()}
        self.assertEqual(rows['3DS tools'], 'Needs setup')

    def test_broken_installed_tools_say_needs_setup_instead_of_not_installed(self):
        app = self.wizard()
        root = Path(self.tmp) / 'partial-tools'
        root.mkdir()
        tc = toolchain.Toolchain(str(root), None,
            [toolchain.Check('Compiler and libraries', False, 'fixture broken compiler', 'build')],
            [], [], None, None, None, 'win32')
        with mock.patch.object(app.pages[3], 'detect'):
            app.show(3)
        app.page.detected(tc)
        page = app.page
        self.assertFalse(page.can_next())
        rows = {page.tree.item(row, 'values')[1]: page.tree.item(row, 'values')[0]
                for row in page.tree.get_children()}
        self.assertEqual(rows['3DS tools'], 'Needs setup')

    def test_sd_review_counts_only_changed_files_and_keeps_fallback_visible(self):
        app = self.wizard()
        app.show(6)
        page = app.page
        card = str(Path(self.tmp) / 'card')
        class Notes(str):
            texture_fallback = True
        notes = Notes(gui.deliver.TEXTURE_FALLBACK)
        items = [SimpleNamespace(size=4, skip=False), SimpleNamespace(size=8_000_000, skip=True)]
        with mock.patch.object(page, 'target_root', return_value=card), \
             mock.patch.object(gui.deliver, 'sd_preview', return_value=(items, None, notes)), \
             mock.patch.object(page, '_copy_approved') as copied:
            page.copy()
            shown = app.overlay
            self.assertIn('Game and build files to copy: 1 (0.0 MB)', shown.message)
            self.assertIn(gui.deliver.TEXTURE_FALLBACK, shown.message)
            self.assertEqual(shown.details_area.winfo_manager(), '')
            shown.choose('Cancel')
            copied.assert_not_called()
