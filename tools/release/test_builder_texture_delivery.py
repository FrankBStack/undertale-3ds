"""Prepared texture results survive every delivery route. Invented data and cards only."""
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE/'builder')]
import discover
import deliver
import gui
import products
import texcache
from test_texcache import Fixture, FAKE_TOOL, fake_run


class PreparationDiagnostics(unittest.TestCase):
    def setUp(self):
        # These data files have no music. Do not depend on another product's
        # release metadata being present in a product-specific source export.
        music = mock.patch.object(products, 'read_music_manifest', return_value={'releases': {}})
        music.start()
        self.addCleanup(music.stop)

    def test_prepared_result_uses_graphics_ready_and_keeps_counts_in_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Fixture(tmp)
            lines = []
            result = texcache.deliver_textures(tree.sd, products.PRODUCTS['undertale'], tree.game,
                tree.work, tool=FAKE_TOOL, run=fake_run, log=lines.append, halfart=False)
            self.assertTrue(result.used)
            self.assertEqual(result.message, 'Graphics ready.')
            self.assertIn('Textures prepared: 1 folder(s) written, 0 already up to date.', lines)

    def test_mac_game_ios_prepares_all_26_pages_in_the_normal_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Fixture(tmp, pages=((16, 16),)*26)
            bundle = Path(tree.game)/'UNDERTALE.app/Contents/Resources'
            bundle.mkdir(parents=True)
            (Path(tree.game)/'data.win').rename(bundle/'game.ios')
            sets, problems = texcache.prepare(FAKE_TOOL, products.PRODUCTS['undertale'],
                tree.game, tree.work, run=fake_run, log=lambda text: None, halfart=False)
            self.assertEqual(problems, [])
            self.assertEqual(len(sets), 1)
            self.assertEqual(sets[0].pages, 26)
            self.assertEqual(sets[0].sd_dir, '3ds/undertale-3ds/cache')

    def test_sd_preview_keeps_compiler_diagnostics_before_copy_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Fixture(tmp)
            lines = []
            def missing_tool(work, log):
                log('fixture first compiler error')
                return texcache.Tool(None, '', 'fixture compiler failed')
            with mock.patch.object(texcache, 'find_tool', side_effect=missing_tool):
                _items, _tool, text = deliver.sd_preview(tree.sd, products.PRODUCTS['undertale'], [],
                    tree.game, tree.work, log=lines.append)
            self.assertIn('fixture first compiler error', lines)
            self.assertIn('texprep: fixture compiler failed', lines)
            self.assertIn('fixture compiler failed', text)

    def test_failed_packer_keeps_its_stderr_in_the_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Fixture(tmp)
            lines = []
            failed = SimpleNamespace(returncode=7, stdout='', stderr='fixture: cannot decode texture page 4')
            _sets, problems = texcache.prepare(FAKE_TOOL, products.PRODUCTS['undertale'],
                tree.game, tree.work, run=lambda argv: failed, log=lines.append, halfart=False)
            self.assertTrue(problems)
            self.assertIn(failed.stderr, '\n'.join(lines))

    def test_source_compiler_failure_keeps_the_first_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            lines = []
            failed = SimpleNamespace(returncode=1, stdout='',
                stderr='fixture first compiler error\ncontext 1\ncontext 2\ncontext 3\nlast line')
            path, reason = texcache.build_tool(tmp, platform='darwin', log=lines.append,
                which=lambda name: '/fixture/'+name, run=lambda argv, env: failed)
            self.assertIsNone(path)
            self.assertIn('exit 1', reason)
            self.assertIn('fixture first compiler error', '\n'.join(lines))

    def test_compiler_launch_and_timeout_failures_return_an_actionable_reason(self):
        for error in (OSError('fixture compiler unavailable'), subprocess.TimeoutExpired('cc', 900)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as tmp:
                lines = []
                def run(argv, env):
                    raise error
                path, reason = texcache.build_tool(tmp, platform='darwin', log=lines.append,
                    which=lambda name: '/fixture/'+name, run=run)
                self.assertIsNone(path)
                self.assertIn('texprep build failed', reason)
                self.assertTrue(lines)


class DeliveryTextureGuiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        from gui_test_support import isolated_builder_host
        isolation = isolated_builder_host(self.base/'host')
        isolation.__enter__()
        self.addCleanup(isolation.__exit__, None, None, None)
        picker = mock.patch.object(gui.filedialog, 'askdirectory',
                                   return_value=str(self.base/'chosen-exports'))
        picker.start()
        self.addCleanup(picker.stop)
        try:
            self.root = gui.tk.Tk()
        except gui.tk.TclError as error:
            from gui_test_support import tk_unavailable
            tk_unavailable(error)
        self.root.withdraw()
        self.addCleanup(self.close)

    def close(self):
        for token in self.root.tk.call('after', 'info'):
            self.root.after_cancel(token)
        self.root.destroy()

    def app(self):
        app = gui.App(self.root, gui.Options(game='undertale', work=str(self.base/'work'),
            probes=discover.Probes(steam_roots=[], gog_dirs=[], save_dir=str(self.base/'pc'))))
        app.state.folder = str(self.base/'game')
        Path(app.state.folder).mkdir(exist_ok=True)
        def work(job, done, errors=False):
            try:
                result = job()
            except Exception as error:
                result = error
            done(result)
        app.work = work
        app.call = lambda function, *args: function(*args)
        return app

    def test_sd_wifi_and_saved_folder_keep_the_texture_warning_in_done_and_the_build_log(self):
        self.check_delivery_result(texcache.Result(False, texcache.FIRST_START))

    def test_sd_wifi_and_saved_folder_show_prepared_textures_in_done(self):
        self.check_delivery_result(texcache.Result(True, 'Graphics ready.'))

    def test_saved_folder_result_survives_radio_changes_only_while_its_receipt_is_current(self):
        for used, message in ((False, texcache.FIRST_START), (True, 'Graphics ready.')):
            with self.subTest(used=used):
                app = self.app()
                page = app.pages[6]
                result = texcache.Result(used, message)
                saved = SimpleNamespace(root=str(self.base/'saved'), folder=str(self.base/'saved'),
                                        files=1, bytes=1, textures=result)
                page.how.set('files')
                with mock.patch.object(gui.deliver, 'save_files', return_value=saved):
                    page.save_files()
                for how in ('wifi', 'sd', 'files'):
                    page.how.set(how)
                    page.mode()
                self.assertTrue(app.state.delivered)
                app.pages[8].on_show()
                self.assertIn(message, app.pages[8].summary_label.cget('text'))
                app.state.inputs += 1
                page.mode()
                self.assertFalse(app.state.delivered)
                self.assertIsNone(app.state.texture_result)

    def test_unwritable_log_never_interrupts_a_real_sd_copy_or_its_completion(self):
        app = self.app()
        page = app.pages[6]
        blocked = self.base/'blocked-log-parent'
        blocked.write_text('Not a directory')
        app.pages[5].log_path = str(blocked/'build.log')
        tree = Fixture(str(self.base/'payload'))
        app.state.folder = tree.game
        page.how.set('sd')
        with mock.patch.object(products, 'read_music_manifest', return_value={'releases': {}}), \
                mock.patch.object(texcache, '_run', side_effect=fake_run):
            items = deliver.plan_sd_copy(tree.sd, app.state.product, [], tree.game)
            page._copy_approved(tree.sd, items, FAKE_TOOL)
        self.assertTrue(app.state.delivered, page.texts['sd'])
        self.assertTrue(app.state.texture_result.used)
        target = Path(tree.sd)/app.state.product.sd_data_dir
        self.assertEqual((target/'data.win').read_bytes(), (Path(tree.game)/'data.win').read_bytes())
        self.assertTrue((target/'cache/complete').is_file())
        self.assertTrue((target/'install.json').is_file())
        app.pages[8].on_show()
        self.assertIn('Graphics ready.', app.pages[8].summary_label.cget('text'))

    def test_full_disk_log_error_does_not_escape_the_logging_callback(self):
        import errno
        page = self.app().pages[6]
        with mock.patch('builtins.open', side_effect=OSError(errno.ENOSPC, 'fixture disk full')):
            page.log_delivery('fixture diagnostic')

    def test_unwritable_log_during_completion_does_not_lock_next(self):
        app = self.app()
        page = app.pages[6]
        blocked = self.base/'blocked-completion-log'
        blocked.write_text('Not a directory')
        app.pages[5].log_path = str(blocked/'build.log')
        page.how.set('sd')
        page.manual = str(self.base/'card')
        page.card.set(page.manual)
        result = texcache.Result(True, 'Graphics ready.')
        with mock.patch.object(gui.deliver, 'copy_with_textures', return_value=(1, 0, 1, result)):
            page._copy_approved(str(self.base/'card'), [], None)
        self.assertTrue(app.state.delivered)
        self.assertTrue(page.can_next())

    def test_wifi_compiler_output_stays_in_the_log_and_out_of_the_status_label(self):
        app = self.app()
        page = app.pages[6]
        log = self.base/'compiler.log'
        app.pages[5].log_path = str(log)
        result = texcache.Result(True, 'Graphics ready.')
        output = '\n'.join('fixture compiler diagnostic %d' % i for i in range(150))
        def transfer(*args, **kwargs):
            kwargs['log'](output)
            self.assertNotIn('fixture compiler diagnostic', page.status.cget('text'))
            self.assertLessEqual(len(page.status.cget('text').splitlines()), 2)
            self.assertIn(output, log.read_text())
            return SimpleNamespace(root=str(self.base/'sent'), textures=result)
        page.how.set('wifi')
        page.mode()  # Map the real panel so the label has the same painted text as a visible page.
        page.addr.set('127.0.0.1:5001')
        with mock.patch.object(gui.ftp_delivery, 'send_product', side_effect=transfer):
            page.send()
        self.assertTrue(app.state.delivered, page.texts['wifi'])
        self.assertIn('Graphics ready.', page.texts['wifi'])

    def test_sd_copy_passes_the_persistent_logger_to_preview(self):
        app = self.app()
        page = app.pages[6]
        log = self.base/'preview.log'
        app.pages[5].log_path = str(log)
        app.prompt = mock.Mock()
        def preview(*args, **kwargs):
            kwargs['log']('fixture preview diagnostic')
            return [], None, 'Fixture file list'
        with mock.patch.object(page, 'target_root', return_value=str(self.base/'card')), \
                mock.patch.object(gui.deliver, 'sd_preview', side_effect=preview):
            page.copy()
        self.assertIn('fixture preview diagnostic', log.read_text())
        app.prompt.assert_called_once()

    def check_delivery_result(self, result):
        for method in ('sd', 'wifi', 'files'):
            with self.subTest(method=method):
                app = self.app()
                page = app.pages[6]
                log = self.base/('build-'+method+'.log')
                log.write_text('synthetic build\n')
                app.pages[5].log_path = str(log)
                card = self.base/'card'
                (card/'3ds').mkdir(parents=True, exist_ok=True)
                saved = SimpleNamespace(root=str(card), folder=str(card), files=1, bytes=1, textures=result)
                def transfer(*args, **kwargs):
                    kwargs.get('log', lambda text: None)('texprep: fixture compiler failed')
                    return (1, 0, 1, result) if method == 'sd' else saved
                page.how.set(method)
                if method == 'sd':
                    with mock.patch.object(gui.deliver, 'copy_with_textures', side_effect=transfer):
                        page._copy_approved(str(card), [], None)
                elif method == 'wifi':
                    page.addr.set('127.0.0.1:5001')
                    with mock.patch.object(gui.ftp_delivery, 'send_product', side_effect=transfer):
                        page.send()
                else:
                    with mock.patch.object(gui.deliver, 'save_files', side_effect=transfer):
                        page.save_files()
                self.assertTrue(app.state.delivered if method != 'files' else page.saved_key)
                self.assertIn(result.message, page.texts[method])
                self.assertIn('texprep: fixture compiler failed', log.read_text())
                self.assertIn(result.message, log.read_text())
                app.pages[8].on_show()
                self.assertIn(result.message, app.pages[8].summary_label.cget('text'))
                app.state.new_delivery()
                app.pages[8].on_show()
                self.assertNotIn(result.message, app.pages[8].summary_label.cget('text'))


if __name__ == '__main__':
    unittest.main()
