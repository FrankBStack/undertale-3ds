"""AOT input labels are independent of the player's folder name. Synthetic files only."""
from pathlib import Path
import os
import errno
import hashlib
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE/'builder')]
import pipeline
import products


class AotNameTests(unittest.TestCase):
    def test_all_hosts_and_install_names_reach_aot_as_undertale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for host in ('win32', 'linux', 'darwin'):
                for index, name in enumerate(('Undertale', 'steam', 'My Games/UNDERTALE 2', 'uNdErTaLe')):
                    with self.subTest(host=host, name=name):
                        folder = root/host/str(index)/name
                        folder.mkdir(parents=True)
                        (folder/'data.win').write_bytes(b'invented Steam or GOG data')
                        staged = Path(products.aot_data_dir(products.PRODUCTS['undertale'], str(folder),
                            str(root/'work'/host/str(index)/'data')))
                        self.assertEqual(staged.name, 'Undertale')
                        self.assertNotEqual(staged, folder)
                        self.assertEqual((staged/'data.win').read_bytes(), (folder/'data.win').read_bytes())
                        tc = SimpleNamespace(bash='/fixture/bash', platform=host, root='/fixture/sdk')
                        for target in ('o3ds', 'n3ds'):
                            argv = pipeline.build_argv(tc, str(root/'work'), 'undertale', target, str(staged), platform=host)
                            data = next(a[5:] for a in argv if a.startswith('data='))
                            self.assertEqual(Path(data).name, 'Undertale')

    def test_mac_bundle_reaches_the_same_label_on_every_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'My Games/UNDERTALE 2'
            source = folder/'UNDERTALE.app/Contents/Resources/game.ios'
            source.parent.mkdir(parents=True)
            source.write_bytes(b'invented Mac input')
            staged = Path(products.aot_data_dir(products.PRODUCTS['undertale'], str(folder), str(root/'work/data')))
            self.assertEqual(staged.name, 'Undertale')
            self.assertEqual((staged/'data.win').read_bytes(), source.read_bytes())

    def test_copy_fallback_rechecks_a_same_size_changed_input_without_touching_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'selected'
            folder.mkdir()
            source = folder/'data.win'
            source.write_bytes(b'first')
            staging = root/'work/data'
            with mock.patch.object(products.os, 'link', side_effect=OSError('fixture no hard links')):
                staged = Path(products.aot_data_dir(products.PRODUCTS['undertale'], str(folder), str(staging)))
                self.assertEqual(staged.name, 'Undertale')
                source.write_bytes(b'other')
                stamp = source.stat()
                self.assertEqual(products.aot_data_dir(products.PRODUCTS['undertale'], str(folder), str(staging)), str(staged))
                self.assertEqual((staged/'data.win').read_bytes(), b'other')
                self.assertEqual(source.read_bytes(), b'other')
                self.assertEqual(source.stat().st_mtime_ns, stamp.st_mtime_ns)

    def test_private_copy_preserves_source_metadata_and_cannot_write_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root/'selected'
            folder.mkdir()
            source = folder/'data.win'
            source.write_bytes(b'invented official input')
            before = source.stat()
            with mock.patch.object(products.os, 'link', side_effect=OSError(errno.EXDEV, 'other drive')) as link:
                staged = Path(products.aot_data_dir(products.PRODUCTS['undertale'], str(folder), str(root/'work/data')))
            link.assert_not_called()
            after = source.stat()
            self.assertEqual((before.st_nlink, before.st_ctime_ns, before.st_mtime_ns),
                             (after.st_nlink, after.st_ctime_ns, after.st_mtime_ns))
            self.assertFalse(os.path.samefile(source, staged/'data.win'))
            (staged/'data.win').write_bytes(b'private replacement')
            self.assertEqual(source.read_bytes(), b'invented official input')

    def test_missing_input_is_refused_instead_of_passing_the_original_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, 'Could not find UNDERTALE'):
                products.aot_data_dir(products.PRODUCTS['undertale'], tmp, str(Path(tmp)/'stage'))

    def test_failed_private_copy_removes_partial_data_at_every_publication_phase(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'input/data.win'
            source.parent.mkdir()
            source.write_bytes(b'invented input, never modified')
            before = source.stat()
            for phase in ('copy', 'timestamp', 'rename'):
                with self.subTest(phase=phase):
                    staging = root/phase
                    part = staging/'Undertale/data.win.part'
                    error = OSError(errno.ENOSPC, 'fixture staging failure', str(part))
                    def failed_copy(src, dst):
                        Path(dst).write_bytes(b'partial input')
                        raise error
                    target = {'copy': (products.shutil, 'copyfile', failed_copy),
                              'timestamp': (products.os, 'utime', error),
                              'rename': (products.os, 'replace', error)}[phase]
                    with mock.patch.object(target[0], target[1], side_effect=target[2]):
                        with self.assertRaises(OSError) as caught:
                            products.aot_data_dir(products.PRODUCTS['undertale'], str(source.parent), str(staging))
                    self.assertIs(caught.exception, error)
                    self.assertFalse(part.exists(), 'Failed staging must not keep a large partial file')
                    self.assertFalse(part.with_suffix('').exists())
                    self.assertEqual(source.read_bytes(), b'invented input, never modified')
                    after = source.stat()
                    self.assertEqual((before.st_nlink, before.st_mtime_ns, before.st_ctime_ns),
                                     (after.st_nlink, after.st_mtime_ns, after.st_ctime_ns))

    def staging_job(self, root):
        job = object.__new__(pipeline.Build)
        job.product = products.PRODUCTS['undertale']
        job.data_dir = str(root/'input')
        job.log_path = str(root/'logs/build.log')
        return job

    def test_missing_and_unreadable_inputs_offer_the_real_choose_game_files_action(self):
        import gui
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'input').mkdir()
            try:
                products.aot_data_dir(products.PRODUCTS['undertale'], str(root/'input'), str(root/'stage'))
            except ValueError as missing:
                errors = [missing, PermissionError(errno.EACCES, 'fixture source unreadable',
                                                  str(root/'input/data.win'))]
            for error in errors:
                with self.subTest(error=error):
                    job = self.staging_job(root)
                    with self.assertRaises(pipeline.GameFilesRefused) as caught:
                        job.refuse_game_files(error)
                    self.assertIn('choose the game files', str(caught.exception))
                    page = object.__new__(gui.BuildPage)
                    page.failed, page.running, page.log_path = caught.exception, False, caught.exception.log_path
                    page.cancel_btn, page.retry_btn, page.copy_btn = mock.Mock(), mock.Mock(), mock.Mock()
                    state = SimpleNamespace(verdict='old', build_ok=True, artifacts=['old'], records=['old'], inputs=4)
                    page.app = SimpleNamespace(state=state, PAGES=[gui.FindPage, gui.BuildPage], show=mock.Mock())
                    page.buttons()
                    self.assertEqual(page.retry_btn.config.call_args.kwargs['text'], 'Choose game files')
                    page.retry_btn.config.call_args.kwargs['command']()
                    page.app.show.assert_called_once_with(0)
                    self.assertIsNone(page.st.verdict)
                    self.assertFalse(page.st.build_ok)
                    self.assertEqual((page.st.artifacts, page.st.records, page.st.inputs), ([], [], 5))

    def test_work_folder_errors_keep_retry_and_replace_the_old_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.staging_job(root)
            for error in (OSError(errno.ENOSPC, 'fixture full', str(root/'input/data.win')),
                          PermissionError(errno.EACCES, 'fixture target denied', str(root/'stage/data.win.part')),
                          OSError(errno.EIO, 'fixture copy error')):
                with self.subTest(error=error):
                    Path(job.log_path).parent.mkdir(exist_ok=True)
                    Path(job.log_path).write_text('OLD SUCCESSFUL BUILD\n', encoding='utf-8')
                    with self.assertRaises(pipeline.BuildFailed) as caught:
                        job.refuse_game_files(error)
                    self.assertNotIsInstance(caught.exception, pipeline.GameFilesRefused)
                    self.assertIn('try again', str(caught.exception).lower())
                    if error.errno != errno.ENOSPC:
                        self.assertIn('files can be saved in the work folder', str(caught.exception))
                    self.assertEqual(caught.exception.log_path, job.log_path)
                    text = Path(job.log_path).read_text(encoding='utf-8')
                    self.assertNotIn('OLD SUCCESSFUL BUILD', text)
                    self.assertEqual(text, 'UNDERTALE staging: '+str(error)+'\n')
            Path(job.log_path).unlink()
            Path(job.log_path).parent.rmdir()
            with self.assertRaises(pipeline.BuildFailed):
                job.refuse_game_files(OSError(errno.EIO, 'fixture new log'))
            self.assertTrue(Path(job.log_path).is_file())

    def test_unwritable_staging_log_does_not_offer_the_previous_build_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            job = self.staging_job(Path(tmp))
            with mock.patch('builtins.open', side_effect=PermissionError(errno.EACCES, 'fixture log denied')):
                with self.assertRaises(pipeline.BuildFailed) as caught:
                    job.refuse_game_files(OSError(errno.EIO, 'fixture staging error'))
            self.assertIsNone(caught.exception.log_path)

    def test_staging_errors_stop_before_compile_with_a_plain_message(self):
        import updates
        with tempfile.TemporaryDirectory() as tmp:
            for error, text in [(OSError(errno.ENOSPC, 'fixture full'), 'Not enough space'),
                                (PermissionError(errno.EACCES, 'fixture denied'), 'Could not prepare UNDERTALE'),
                                (OSError(errno.EIO, 'fixture read error'), 'Could not prepare UNDERTALE'),
                                (ValueError('Choose a work folder outside the game folder.'), 'Choose a work folder')]:
                with self.subTest(error=error):
                    job = object.__new__(pipeline.Build)
                    job.product = products.PRODUCTS['undertale']
                    job.tc = SimpleNamespace(platform=sys.platform)
                    job.source_root = tmp
                    job.work = tmp
                    job.data_dir = str(Path(tmp)/'input')
                    job.log_path = str(Path(tmp)/'build.log')
                    job.prepare = mock.Mock(return_value=('test', 0, 0))
                    job.environment = mock.Mock(side_effect=AssertionError('must not compile'))
                    with mock.patch.object(pipeline, 'release_version', return_value='test'), \
                         mock.patch.object(pipeline.toolchain, 'compiler_details', return_value={}), \
                         mock.patch.object(pipeline.toolchain, 'require_release_compiler'), \
                         mock.patch.object(updates, 'repository', return_value='https://github.com/test/undertale-3ds'), \
                         mock.patch.object(products.release_contract, 'read', return_value={
                             'tested_compiler': {}, 'development_source_base': 'https://example.invalid'}), \
                         mock.patch.object(products, 'aot_data_dir', side_effect=error):
                        with self.assertRaisesRegex(pipeline.BuildFailed, text):
                            job._run()
                    job.environment.assert_not_called()

    def test_dry_run_prints_the_private_input_without_creating_it(self):
        import builder as app
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root/'work'
            selected = root/'My Games/uNdErTaLe 2'
            o = dict(app.parse(['--dry-run', '--folder', str(selected), '--work', str(work),
                                '--target', 'n3ds', '--no-texprep']))
            probes = SimpleNamespace(roots=lambda: [], pc_save_dir=lambda game: str(root/'empty-saves'))
            tc = SimpleNamespace(bash='/fixture/bash', root='/fixture/sdk', platform=sys.platform)
            output = []
            with mock.patch.object(app, 'probes_for', return_value=probes), \
                 mock.patch.object(app.discover, 'find_copies', return_value=[]), \
                 mock.patch.object(app.toolchain, 'detect', return_value=tc), \
                 mock.patch.object(app.toolchain, 'dry_run_report', return_value='fixture tools'), \
                 mock.patch.object(app, 'source_line', return_value='fixture source'), \
                 mock.patch.object(app.texcache, 'data_version_dry_run_lines', return_value=[]):
                self.assertEqual(app.dry_run(o, out=output.append), 0)
            text = '\n'.join(output).replace('\\', '/')
            self.assertIn('data='+str(work/'data/Undertale').replace('\\', '/'), text)
            self.assertNotIn('data='+str(selected).replace('\\', '/'), text)
            self.assertFalse((work/'data').exists())

    def test_staging_cannot_be_inside_the_selected_game(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)/'selected'
            folder.mkdir()
            (folder/'data.win').write_bytes(b'invented input')
            with self.assertRaises(ValueError):
                products.aot_data_dir(products.PRODUCTS['undertale'], str(folder), str(folder/'staging'))
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['data.win'])

    def test_deltarune_keeps_its_existing_part_folders(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(products.aot_data_dir(products.PRODUCTS['deltarune'], tmp, str(Path(tmp)/'unused')), tmp)


class GeneratorNameTests(unittest.TestCase):
    def generate(self, root, name, payload, rows):
        import gmlaot as g
        import data_versions
        import weirdshd
        folder = root/name
        folder.mkdir(parents=True)
        source = folder/'data.win'
        source.write_bytes(payload)
        dw = SimpleNamespace(data=payload, wad=17, code=[], vars=[], funcs=[], code_by_name={},
                             patch_operands=lambda: None)
        out = root/'generated'
        with mock.patch.object(g, 'DataWin', return_value=dw), \
             mock.patch.object(data_versions, 'load_table', return_value=(1, rows)), \
             mock.patch.object(weirdshd, 'validate', wraps=weirdshd.validate) as validate:
            self.assertEqual(g.main(['gmlaot.py', str(out), '--game', str(source),
                                     '--target', 'o3ds', '--typed', 'all']), 0)
        return dw, validate.call_args.args[2], {p.name: p.read_bytes() for p in out.glob('*.c')}

    def setUp(self):
        sys.path.insert(0, str(HERE.parent/'aot'))
        self.addCleanup(sys.path.remove, str(HERE.parent/'aot'))

    def test_all_four_generator_labels_use_only_the_undertale_hash(self):
        payload = b'invented supported UNDERTALE container'
        rows = {('undertale', 'root', len(payload), hashlib.sha256(payload).hexdigest())}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            results = []
            for name in ('Undertale', 'My Games/uNdErTaLe 2', 'chapter5_windows'):
                dw, part, files = self.generate(root, name, payload, rows)
                self.assertEqual(dw.folder, 'Undertale')
                self.assertEqual(part, 'Undertale')
                self.assertIn(b'from Undertale/data.win.', files['aot_table.c'])
                self.assertIn(b'{ "Undertale",', files['aot_table.c'])
                results.append(files)
            self.assertTrue(all(files == results[0] for files in results))

    def test_deltarune_chapter_and_unknown_data_keep_existing_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index, game in enumerate(('deltarune', 'unknown')):
                payload = b'invented other container'
                rows = {(game, 'chapter5_windows', len(payload), hashlib.sha256(payload).hexdigest())}
                dw, part, files = self.generate(root/str(index), 'chapter5_windows', payload, rows)
                self.assertEqual(dw.folder, 'chapter5_windows')
                self.assertEqual(part, 'chapter5_windows')
                self.assertIn(b'{ "chapter5_windows",', files['aot_table.c'])


if __name__ == '__main__':
    unittest.main()
