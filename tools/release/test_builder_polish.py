"""Player-facing polish regressions: invented files, isolated host, hidden Tk desktop."""
import os
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

import test_builder as fixtures
import gui
import toolchain
from gui_test_support import isolated_builder_host


class PolishGuiTests(unittest.TestCase):
    tearDown = fixtures.GuiTest.tearDown
    wizard = fixtures.BuilderUiTest.wizard
    toolchain_fixture = fixtures.BuilderUiTest.toolchain_fixture
    open_toolchain_page = fixtures.BuilderUiTest.open_toolchain_page

    def setUp(self):
        fixtures.GuiTest.setUp(self)
        guard = isolated_builder_host(Path(self.tmp) / 'isolated-polish-host')
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)

    def test_clean_compiler_page_names_missing_tools_and_the_next_action(self):
        app = self.wizard()
        missing = toolchain.Toolchain(None, None,
            [toolchain.Check('devkitPro', False, 'not found', 'build')],
            list(toolchain.REQUIRED_PACKAGES), list(toolchain.RECOMMENDED_PACKAGES),
            None, None, None, 'win32')
        self.open_toolchain_page(app, missing)
        page = app.page
        rows = [page.tree.item(row, 'values') for row in page.tree.get_children()]
        self.assertIn('Not installed', [row[0] for row in rows])
        self.assertNotIn('Ready', [row[0] for row in rows])
        self.assertIn('Next stays grey', page.compiler_status.cget('text'))
        self.assertIn(page.boxes[0].step.title, page.compiler_status.cget('text'))
        self.assertFalse(page.can_next())
        for box in page.boxes:
            optional = box.step.key in ('makerom', 'bannertool')
            self.assertEqual(box.box.cget('text').startswith('Optional:'), optional)
            self.assertEqual(box.go._primary, not optional)

    def test_successful_update_removes_its_temporary_step_box(self):
        app = self.wizard(confirm_install=lambda *_: True)
        self.open_toolchain_page(app, self.toolchain_fixture())
        page = app.page
        with mock.patch.object(toolchain, 'run_step'), mock.patch.object(page, 'detect'):
            page.update()
        self.assertTrue(page.update_box is None or not page.update_box.box.winfo_exists())

    def test_linux_arm_options_does_not_send_players_to_unavailable_downloads(self):
        app = self.wizard()
        app.state.tc = SimpleNamespace(can_cia=False, platform='linux-aarch64')
        app.show(4)
        self.assertIn('not available for this computer', app.page.cia_note.cget('text'))
        self.assertNotIn('go Back', app.page.cia_note.cget('text'))

    def test_unchanged_options_keeps_the_finished_build_and_artifacts(self):
        app = self.wizard()
        marker = object()
        app.state.build_ok = True
        app.state.artifacts = [marker]
        app.state.records = [dict(target='o3ds', seconds=1)]
        with mock.patch.object(app.pages[5], 'start') as start:
            app.show(4)
            self.assertTrue(app.state.build_ok)
            app.next()
            self.assertEqual(app.index, 5)
            start.assert_not_called()
        self.assertEqual(app.state.artifacts, [marker])

    def test_changing_a_build_option_invalidates_the_finished_build(self):
        app = self.wizard()
        page = app.pages[4]
        for field in ('target', 'v3dsx'):
            app.state.build_ok = True
            if field == 'target':
                page.target.set('o3ds')
            else:
                page.v3dsx.set(False)
            page.changed()
            self.assertFalse(app.state.build_ok)

    def test_window_uses_the_game_title_and_the_existing_heart_icon(self):
        with mock.patch.object(self.root, 'iconphoto', wraps=self.root.iconphoto) as install:
            app = self.wizard()
        self.assertEqual(self.root.title(), 'UNDERTALE 3DS Builder')
        install.assert_called_once_with(True, app._window_icon)
        mask = app.theme.soul_mask
        self.assertEqual(app._window_icon.width(), len(mask[0]) * 2)
        for y, row in enumerate(mask):
            for x, on in enumerate(row):
                if on:
                    self.assertEqual(app._window_icon.get(x * 2, y * 2), (255, 0, 0))
                else:
                    self.assertTrue(app._window_icon.transparency_get(x * 2, y * 2))
        app.reset('deltarune')
        self.assertEqual(self.root.title(), 'DELTARUNE 3DS Builder')

    def test_automatic_check_waits_until_welcome_next_and_honors_opt_out(self):
        app = self.wizard()
        page = app.pages[0]
        with mock.patch.object(app.update_checker, 'request') as request:
            self.root.update()
            request.assert_not_called()
            page.check_updates.set(False)
            page.update_preference()
            page.on_next()
            request.assert_not_called()
            page.check_updates.set(True)
            # A deliberate checkbox change may still check immediately, as before.
            page.on_next()
            request.assert_called_once()

    def test_cleanup_only_done_and_report_close_return_to_welcome(self):
        app = self.wizard()
        page = app.pages[8]
        with mock.patch.object(self.root, 'destroy') as close:
            page.cleanup_only = True
            app.show(8)
            self.assertEqual(page.finish_label(), 'Done')
            app.next()
            self.assertEqual(app.index, 0)
            self.assertFalse(page.cleanup_only)
            page.cleanup_only = True
            app.show(8)
            page.report_cleanup([], [])
            app.overlay.choose('Close')
            self.assertEqual(app.index, 0)
            self.assertFalse(page.cleanup_only)
            close.assert_not_called()

    def test_both_wifi_panels_offer_a_working_ftpd_link(self):
        app = self.wizard()
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        for panel in (app.pages[6].wifi, app.pages[7].wifi):
            links = [widget for widget in descendants(panel)
                     if isinstance(widget, gui.UtButton) and widget.cget('text') == 'Get ftpd']
            self.assertEqual(len(links), 1)
            with mock.patch.object(gui.webbrowser, 'open') as opened:
                links[0].invoke()
                opened.assert_called_once_with('https://github.com/mtheall/ftpd#latest-builds')

    def test_folder_export_asks_for_a_destination_and_cancel_does_nothing(self):
        app = self.wizard()
        page = app.pages[6]
        selected = Path(self.tmp) / 'chosen-output'
        with mock.patch.object(gui.filedialog, 'askdirectory', return_value='') as pick, \
             mock.patch.object(app, 'work') as worker:
            page.save_files()
            pick.assert_called_once()
            worker.assert_not_called()
            self.assertFalse(page.copying)
        result = SimpleNamespace(root=str(selected / 'ready/SD-CARD-FILES'), folder=str(selected / 'ready'),
                                 files=1, bytes=4, textures=SimpleNamespace(message='Ready.'))
        with mock.patch.object(gui.filedialog, 'askdirectory', return_value=str(selected)) as pick, \
             mock.patch.object(gui.deliver, 'save_files', return_value=result) as export:
            page.save_files()
            self.assertEqual(export.call_args.kwargs['output_parent'], str(selected))
            self.assertIn('initialdir', pick.call_args.kwargs)
            self.assertEqual(app.state.files_root, result.folder)

    def test_done_keeps_cleanup_details_out_of_the_normal_screen(self):
        app = self.wizard()
        work = Path(app.opts.work)
        (work / 'texcache').mkdir(parents=True)
        (work / 'texcache' / 'unrecorded.txt').write_text('player file', encoding='utf-8')
        app.show(8)
        page = app.page
        self.assertNotIn('Kept (', page.cleanup_notice.cget('text'))
        self.assertNotIn('no record', page.cleanup_notice.cget('text'))
        self.assertIn('undertale-3ds', page.steps_label.cget('text'))
        self.assertIn('UNDERTALE', page.steps_label.cget('text'))
        self.assertNotIn('What to do now:', page.steps_label.cget('text'))

    def test_sd_review_starts_with_a_wrapped_summary_and_can_show_all_files(self):
        app = self.wizard()
        app.show(6)
        page = app.page
        card = Path(self.tmp) / 'fixture-card'
        card.mkdir()
        items = [SimpleNamespace(size=4, skip=False)]
        detail = 'Add: 3ds/undertale-3ds/data.win\n' * 240
        with mock.patch.object(page, 'target_root', return_value=str(card)), \
             mock.patch.object(gui.deliver, 'sd_preview', return_value=(items, None, detail)), \
             mock.patch.object(page, '_copy_approved') as copied:
            page.copy()
            shown = app.overlay
            self.assertIn('Game and build files to copy: 1', shown.message)
            self.assertIn('Saves, settings, other homebrew and other games are kept.', shown.message)
            self.assertNotIn('data.win', shown.message)
            self.assertEqual(shown.details_area.winfo_manager(), '')
            self.assertEqual(shown.list.cget('wrap'), 'word')
            shown.details_toggle.invoke()
            self.assertEqual(shown.details_area.winfo_manager(), 'pack')
            self.assertEqual(shown.list.get('1.0', 'end').count('data.win'), 240)
            shown.details_toggle.invoke()
            self.assertEqual(shown.details_area.winfo_manager(), '')
            shown.choose('Cancel')
            copied.assert_not_called()

    def test_sd_review_summary_fits_both_looks_at_100_and_200_percent(self):
        app = self.wizard()
        app.theme.runtime_loaded = True
        self.root.deiconify()
        for scale in (1, 2):
            self.root.tk.call('tk', 'scaling', scale * 96 / 72)
            width = min(680 * scale, self.root.winfo_screenwidth() - 40)
            height = min(560 * scale, self.root.winfo_screenheight() - 80)
            self.root.minsize(width, height)
            self.root.geometry('%dx%d' % (width, height))
            for boring in (False, True):
                with self.subTest(scale=scale, boring=boring):
                    app.theme.boring = boring
                    app.theme.apply()
                    app.prompt('Files for this SD card',
                               'Game and build files to copy: 240 (168.3 MB).\nOnly missing or changed files will be copied. '
                               'Saves, settings, other homebrew and other games are kept.\n\n' +
                               gui.deliver.TEXTURE_FALLBACK,
                               [('Cancel', lambda: None, False), ('Copy to card', lambda: None, True)],
                               details='Add: 3ds/undertale-3ds/data.win\n' * 240, collapse_details=True)
                    shown = app.overlay
                    for expanded in (False, True):
                        if expanded:
                            shown.details_toggle.invoke()
                        for _ in range(3):
                            self.root.update()
                            shown.fit()
                        self.assertLessEqual(shown.frame.winfo_width(), shown.canvas.winfo_width())
                        for widget in shown.wrappers:
                            self.assertLessEqual(widget._wrap, max(120, shown.wrap_width(widget)))
                    shown.choose('Cancel')

    def test_about_fits_the_smallest_window_in_both_looks_at_100_and_200_percent(self):
        # The built-in font is the look before the game is found; the About's OK must not sit under the box's edge.
        app = self.wizard()
        app.theme.runtime_loaded = True
        self.root.deiconify()
        for scale in (1, 2):
            self.root.tk.call('tk', 'scaling', scale * 96 / 72)
            width = min(680 * scale, self.root.winfo_screenwidth() - 40)
            height = min(560 * scale, self.root.winfo_screenheight() - 80)
            self.root.minsize(width, height)
            self.root.geometry('%dx%d' % (width, height))
            for boring in (False, True):
                with self.subTest(scale=scale, boring=boring):
                    app.theme.boring = boring
                    app.theme.apply()
                    app.about()
                    shown = app.overlay
                    for _ in range(3):
                        self.root.update()
                        shown.fit()
                    self.assertTrue(shown.message.startswith('UNDERTALE and DELTARUNE are by Toby Fox.'))
                    self.assertIn('\n\nPort source code: Copyright (C) 2026 ', shown.message)
                    self.assertFalse(shown.scrollable())
                    shown.choose('OK')

    def test_only_the_built_in_font_halves_the_blank_line_between_paragraphs(self):
        app = self.wizard()
        theme = app.theme
        lh = theme.line_height()
        self.assertEqual(theme.render_text_image('a\n\nb', wrap=600).height(), 2 * lh + lh // 2)
        theme.glyphs = dict(theme.glyphs)  # any other font, as the game's own once it is found
        theme._text_cache.clear()
        self.assertEqual(theme.render_text_image('a\n\nb', wrap=600).height(), 3 * lh)
