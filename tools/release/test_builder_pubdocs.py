"""Public wording follows real failures; all inputs and destinations are invented."""
import errno
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

import test_builder as fixtures
import cleanup
import deliver
import ftp_delivery
import ftp_saves
import gui
import library_pins
import pipeline
import products
import saves
import sd_transaction
import texcache
import toolchain
from gui_test_support import isolated_builder_host

UT = products.PRODUCTS['undertale']


class FailureTextTests(unittest.TestCase):
    def test_download_errors_distinguish_network_full_disk_and_folder_access(self):
        cases = [(urllib.error.URLError('fixture offline'), 'connection'),
                 (OSError(errno.ENOSPC, 'fixture full'), 'free space'),
                 (PermissionError(errno.EACCES, 'fixture denied'), 'access'),
                 (OSError(errno.EIO, 'fixture failed'), 'downloaded or saved')]
        with tempfile.TemporaryDirectory() as folder:
            for error, advice in cases:
                with self.subTest(error=type(error), advice=advice):
                    with self.assertRaises(toolchain.Refused) as caught:
                        library_pins._download_file({}, 'https://example.invalid/fixture',
                            Path(folder) / 'fixture', 3, 'unused', mock.Mock(side_effect=error))
                    self.assertIn(advice, str(caught.exception))
                    self.assertIn('was not changed', str(caught.exception))
                    self.assertEqual(caught.exception.details, str(error))
                    self.assertFalse((Path(folder) / 'fixture').exists())

    def test_local_download_write_failures_do_not_blame_the_connection(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'fixture'
            with mock.patch.object(Path, 'open', side_effect=PermissionError(errno.EACCES, 'fixture denied')):
                with self.assertRaises(toolchain.Refused) as caught:
                    library_pins._download_file({}, 'https://example.invalid/fixture', target,
                                                3, 'unused', lambda *a, **k: io.BytesIO(b'abc'))
            self.assertIn('access', str(caught.exception))
            self.assertNotIn('connection', str(caught.exception))

    def test_manual_setup_does_not_claim_the_server_blocked_the_download(self):
        for platform in ('win32', 'darwin', 'linux'):
            with self.subTest(platform=platform):
                text = toolchain.manual_install_message(platform)
                self.assertIn('did not provide', text)
                self.assertNotIn('blocked', text)
                self.assertIn('official', text)

    def test_interrupted_wifi_send_requires_completion_before_playing(self):
        with self.assertRaises(ftp_delivery.Cancelled) as caught:
            ftp_delivery.check_cancel(lambda: True)
        self.assertIn('before starting the game', str(caught.exception))
        self.assertNotIn('Nothing is lost', str(caught.exception))
        text = str(ftp_delivery.delivery_error(ConnectionResetError('fixture reset')))
        self.assertIn('before starting the game', text)
        self.assertLessEqual(len(text.split()), 25)

    def test_graphics_fallback_names_the_space_needed_on_the_card(self):
        self.assertEqual(deliver.TEXTURE_FALLBACK, texcache.FIRST_START)
        self.assertIn('free SD card space', deliver.TEXTURE_FALLBACK)

    def test_full_card_graphics_fallback_keeps_the_rounded_space_requirement(self):
        with mock.patch.object(texcache, 'plan', return_value=[mock.Mock(bytes=1000001)]), \
             mock.patch.object(texcache.shutil, 'disk_usage', return_value=mock.Mock(free=0)), \
             mock.patch.object(texcache, 'write_plans') as write:
            result = texcache.deliver_textures('fixture-card', UT, 'fixture-game', 'fixture-work',
                tool=texcache.Tool('fixture', 'pin', 'ok'), prepared=([object()], []), log=lambda _: None)
        self.assertFalse(result.used)
        self.assertIn('at least 2 MB', result.message)
        self.assertIn('3DS also needs free space', result.message)
        write.assert_not_called()


class BuildFailureTests(unittest.TestCase):
    setUp = fixtures.BuildTest.setUp
    tearDown = fixtures.BuildTest.tearDown
    outputs = fixtures.BuildTest.outputs
    make = fixtures.BuildTest.make

    def test_multiline_library_refusal_keeps_the_reason_in_details_and_the_log(self):
        reason = 'fixture link file has the wrong bytes'
        job, _ = self.make(['LIBRARY REFUSED: final check failed\n', reason + '\n'], rc=2)
        with self.assertRaises(pipeline.BuildFailed) as caught:
            job.run()
        self.assertIn('did not pass the final check', str(caught.exception))
        self.assertIn(reason, caught.exception.details)
        self.assertIn(reason, Path(job.log_path).read_text(encoding='utf-8'))

    def test_preparation_download_diagnostics_reach_the_persistent_log(self):
        error = library_pins.download_error(PermissionError(errno.EACCES, 'fixture cannot write'), self.work)
        job, _ = self.make([])
        with mock.patch.object(pipeline.library_pins, 'select', side_effect=error):
            with self.assertRaises(pipeline.BuildFailed) as caught:
                job.run()
        self.assertIn('access', str(caught.exception))
        self.assertIn('fixture cannot write', caught.exception.details)
        self.assertIn('fixture cannot write', Path(job.log_path).read_text(encoding='utf-8'))

    def test_late_output_failure_does_not_claim_the_entire_old_build_was_kept(self):
        self.tc.makerom = 'fixture-makerom'
        self.tc.bannertool = 'fixture-bannertool'
        job, _ = self.make([], kinds=('3dsx', 'cia'), outputs=('3dsx', 'cia'))
        destination = Path(self.work) / 'out/n3ds'
        destination.mkdir(parents=True)
        for kind in ('3dsx', 'cia'):
            (destination / ('undertale-3ds-n3ds.' + kind)).write_bytes(b'old')
        original = pipeline.shutil.copy2
        def fail_second(source, target, *args, **kwargs):
            if str(source).endswith('.cia'):
                raise OSError(errno.ENOSPC, 'fixture full')
            return original(source, target, *args, **kwargs)
        with mock.patch.object(pipeline.shutil, 'copy2', side_effect=fail_second):
            with self.assertRaises(pipeline.BuildFailed) as caught:
                job.run()
        self.assertIn('Some build files may already have been updated', str(caught.exception))
        self.assertNotEqual((destination / 'undertale-3ds-n3ds.3dsx').read_bytes(), b'old')
        self.assertEqual((destination / 'undertale-3ds-n3ds.cia').read_bytes(), b'old')


class CopyRecoveryTests(unittest.TestCase):
    def test_unverified_sd_recovery_requires_retry_for_errors_and_cancellation(self):
        for error in (InterruptedError('fixture cancelled'), OSError(errno.EIO, 'fixture card absent')):
            for recovered in (False, True):
                with self.subTest(error=type(error), recovered=recovered):
                    tx = mock.Mock()
                    tx.recover.side_effect = [None, None if recovered else OSError(errno.EIO, 'fixture absent')]
                    with mock.patch.object(products, 'log_ignored_music'), \
                         mock.patch.object(texcache, 'data_wins', side_effect=error):
                        with self.assertRaises(deliver.DeliverError) as caught:
                            deliver._copy_transaction(tx, 'fixture-card', [], UT, 'fixture-game',
                                'fixture-work', [], None, lambda: False, lambda _: None, False, None, False)
                    text = str(caught.exception)
                    self.assertEqual('Do not start the game' in text, not recovered or not isinstance(error, InterruptedError))
                    self.assertEqual(tx.recover.call_count, 2)


class SaveFailureTests(unittest.TestCase):
    def test_unreadable_save_folder_is_distinct_from_absent_and_empty(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertTrue(saves.scan_saves(root).exists)
            self.assertIsNone(saves.scan_saves(root).error)
            self.assertFalse(saves.scan_saves(os.path.join(root, 'missing')).exists)
            with mock.patch.object(saves.os, 'listdir', side_effect=PermissionError('fixture denied')):
                scan = saves.scan_saves(root)
            self.assertTrue(scan.exists)
            self.assertIn('could not read the PC save folder', scan.error)
            self.assertIn('Skip', scan.error)
            with self.assertRaisesRegex(ftp_delivery.TransferError, 'could not read the PC save folder'):
                ftp_saves.copy(None, UT, scan, None)

    def test_file_read_failure_is_not_diagnosed_as_corruption_or_an_sd_lock(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'file0'
            source.write_bytes(b'NAME\n1\n0\n')
            with mock.patch('builtins.open', side_effect=PermissionError('fixture denied')):
                sf = saves.inspect_save_file(str(source))
            self.assertTrue(sf.read_error)
            self.assertIn('Check folder access', sf.detail)
            self.assertNotIn('Corrupt', sf.detail)
            sf.corrupt = False  # A scan supplied without checked bytes must re-read before importing.
            with mock.patch('builtins.open', side_effect=PermissionError('fixture denied')):
                with self.assertRaises(saves.DeliverError) as caught:
                    saves.validated_payloads(saves.SaveScan(root, [sf], True), 'undertale')
            self.assertIn('PC save folder', str(caught.exception))
            self.assertNotIn('Lock switch', str(caught.exception))

    def test_listed_save_with_unreadable_metadata_is_not_silently_skipped(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'file0'
            source.write_bytes(b'NAME\n1\n0\n')
            original = saves.os.stat
            def fail_file(path, *args, **kwargs):
                if os.fspath(path) == str(source):
                    raise PermissionError('fixture file access denied')
                return original(path, *args, **kwargs)
            with mock.patch.object(saves.os, 'stat', side_effect=fail_file):
                scan = saves.scan_saves(root)
            self.assertTrue(scan.exists)
            self.assertEqual([sf.name for sf in scan.files], ['file0'])
            self.assertTrue(scan.files[0].read_error)

    def test_unknown_save_format_is_refused_without_claiming_damaged_bytes(self):
        with tempfile.TemporaryDirectory() as root:
            for data in (b'\0unknown', b'\xffunknown', b'NAME\nnot-a-level\n'):
                source = Path(root) / 'file0'
                source.write_bytes(data)
                result = saves.inspect_save_file(str(source))
                self.assertFalse(result.valid)
                self.assertIn('format not recognized', result.detail)

    def test_partial_save_publication_requires_finishing_with_or_without_a_backup(self):
        for existing in (False, True):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as root:
                card, pc = Path(root) / 'card', Path(root) / 'pc'
                live = Path(saves.sd_save_dir(str(card), UT))
                live.mkdir(parents=True)
                pc.mkdir()
                for name in ('file0', 'file9'):
                    (pc / name).write_bytes(b'NEW\n1\n0\n')
                    if existing:
                        (live / name).write_bytes(b'OLD\n1\n0\n')
                original = saves.os.replace
                def fail_second(source, destination):
                    if Path(destination) == live / 'file9':
                        raise OSError(errno.EIO, 'fixture removed')
                    return original(source, destination)
                with mock.patch.object(saves.os, 'replace', side_effect=fail_second):
                    with self.assertRaises(saves.DeliverError) as caught:
                        saves.copy_pc_saves(str(card), UT, str(pc), overwrite=True)
                self.assertIn('Save copying stopped before it finished.', str(caught.exception))
                self.assertIn('fixture removed', str(caught.exception))
                self.assertIn('Do not start the game yet', str(caught.exception))
                self.assertIn('copy the same PC saves again', str(caught.exception))
                self.assertEqual('backed up in' in str(caught.exception), existing)
                self.assertEqual((live / 'file0').read_bytes(), (pc / 'file0').read_bytes())
                self.assertEqual((live / 'file9').exists(), existing)
                saves.copy_pc_saves(str(card), UT, str(pc), overwrite=True)
                for name in ('file0', 'file9'):
                    self.assertEqual((live / name).read_bytes(), (pc / name).read_bytes())


class PublicGuiTextTests(unittest.TestCase):
    tearDown = fixtures.GuiTest.tearDown
    wizard = fixtures.BuilderUiTest.wizard

    def setUp(self):
        fixtures.GuiTest.setUp(self)
        guard = isolated_builder_host(Path(self.tmp) / 'isolated-pubdocs-host')
        guard.__enter__()
        self.addCleanup(guard.__exit__, None, None, None)

    def test_save_folder_error_is_not_shown_as_no_saves(self):
        app = self.wizard()
        error = 'The builder could not read the PC save folder fixture. Check access, choose another folder, or Skip.'
        with mock.patch.object(deliver, 'scan_saves', return_value=saves.SaveScan('fixture', [], True, error)):
            app.show(7)
        self.assertIn(error, app.page.notice.cget('text'))
        self.assertNotIn('No PC saves', app.page.notice.cget('text'))
        self.assertIn('disabled', app.page.copy_radio.state())

    def test_failed_build_shows_full_library_details_below_the_short_summary(self):
        app = self.wizard()
        page = app.pages[5]
        reason = 'fixture exact library mismatch reason'
        error = pipeline.BuildFailed('The required 3DS files did not pass the final check.', details=reason)
        page.finished(error)
        self.assertIn(reason, page.log.get('1.0', 'end'))
        self.assertNotIn(reason, page.status.cget('text'))

    def test_cleanup_only_help_and_grouped_preview_describe_the_real_actions(self):
        app = self.wizard()
        page = app.pages[8]
        page.cleanup_only = True
        page.on_show()
        self.assertIn('Done to return to the first screen', page.cleanup_help.cget('text'))
        self.assertNotIn('Finish closes', page.cleanup_help.cget('text'))
        root = os.path.join(self.tmp, 'work', 'cache')
        page.cleanup_plan = cleanup.Plan([cleanup.File(os.path.join(root, str(i)), root, 'build', 1, 0, i)
                                          for i in range(13)], [])
        page.cleanup_choices['build'].set(True)
        with mock.patch.object(app, 'prompt') as prompt:
            page.preview_cleanup()
        self.assertIn('Large groups', prompt.call_args.args[1])
        self.assertIn('(13 files)', prompt.call_args.kwargs['details'])

    def test_find_page_names_supported_files_without_install_record_advice(self):
        app = self.wizard()
        app.show(1)
        text = app.page.intro.cget('text')
        for edition in ('Windows Steam', 'macOS Steam', 'Windows GOG'):
            self.assertIn(edition, text)
        self.assertIn('On Linux, use the Windows files', text)
        self.assertNotIn('Install it in', app.page.status.cget('text'))


class MacWindowRecoveryTests(unittest.TestCase):
    def test_missing_tk_advice_uses_the_actual_runtime_not_just_the_host_platform(self):
        app = fixtures.app
        original_import = __import__
        def without_gui(name, *args, **kwargs):
            if name == 'gui':
                raise ModuleNotFoundError('fixture missing Tk', name='tkinter')
            return original_import(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as root:
            resources = Path(root) / 'UNDERTALE 3DS Builder.app/Contents/Resources'
            entry = resources / 'builder/tools/release/builder'
            for embedded in (True, False):
                executable = resources / 'runtime/arm64/bin/python3' if embedded else Path(root) / 'python3'
                output = io.StringIO()
                with self.subTest(embedded=embedded), mock.patch.object(app, 'HERE', str(entry)), \
                     mock.patch.object(app.sys, 'executable', str(executable)), \
                     mock.patch.object(app.sys, 'platform', 'darwin'), \
                     mock.patch('builtins.__import__', side_effect=without_gui), \
                     mock.patch.object(sys, 'stderr', output):
                    self.assertEqual(app.main(['builder.py', '--work', str(Path(root) / 'work')]), 2)
                self.assertEqual('unpack the complete Mac builder again' in output.getvalue(), embedded)
                self.assertEqual('universal2' in output.getvalue(), not embedded)
