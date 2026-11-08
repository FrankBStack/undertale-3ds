"""Save-listing errors must never authorize replacement. Invented saves, loopback only."""
from pathlib import Path
import ftplib
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE/'builder')]
from test_builder_save_audit import SaveFixture, UT
import ftp_delivery
import ftp_saves
import saves

OLD = b'OLD\n1\n0\n'
NEW = b'NEW\n2\n0\n'


class ListingSafetyTests(SaveFixture):
    def exercise(self, failures, *, reply='550 Input/output error'):
        (self.saves/'file0').write_bytes(OLD)
        (self.pc/'file0').write_bytes(NEW)
        scan = saves.scan_saves(str(self.pc))
        folder = '/' + UT.sd_save_dir()
        calls = 0
        commands_at_fault = []
        server = self.server

        class FixtureFTP(ftp_delivery.ConsoleFTP):
            def mlsd(self, path='', facts=[]):
                nonlocal calls
                if path == folder:
                    calls += 1
                    if calls in failures:
                        commands_at_fault.append(len(server.cmds))
                        raise ftplib.error_perm(reply)
                return super().mlsd(path, facts)

        if failures:
            with self.assertRaisesRegex(ftp_delivery.TransferError, 'saves folder could not be checked'):
                expected = ftp_saves.inspect(self.address, UT, factory=FixtureFTP)
                ftp_saves.copy(self.address, UT, scan, expected, overwrite=bool(expected.files), factory=FixtureFTP)
            self.assertEqual((self.saves/'file0').read_bytes(), OLD)
            self.assertEqual(len(commands_at_fault), 1)
            # After the failed listing, do not publish, remove, upload or create anything.
            self.assertFalse(any(cmd in ('DELE', 'RNFR', 'RNTO', 'STOR', 'MKD', 'RMD')
                                 for cmd, _ in server.cmds[commands_at_fault[0]:]))
            if min(failures) <= 2:
                self.assertEqual({p.relative_to(self.card).as_posix(): p.read_bytes()
                                  for p in self.card.rglob('*') if p.is_file()},
                                 {UT.sd_save_dir()+'/file0': OLD})
        else:
            expected = ftp_saves.inspect(self.address, UT, factory=FixtureFTP)
            result = ftp_saves.copy(self.address, UT, scan, expected, overwrite=True, factory=FixtureFTP)
            self.assertEqual((self.saves/'file0').read_bytes(), NEW)
            self.assertEqual((self.card/result.backup_dir.lstrip('/')/'file0').read_bytes(), OLD)
        self.assertEqual((self.pc/'file0').read_bytes(), NEW)

    def test_scourw3_no_failure_control_preserves_a_verified_backup(self):
        self.exercise(set())

    def test_scourw3_preview_error_stops_before_any_write(self):
        self.exercise({1})

    def test_scourw3_copy_start_error_stops_before_any_write(self):
        self.exercise({2})

    def test_scourw3_three_errors_cannot_skip_confirmation_and_backup(self):
        self.exercise({1, 2, 3})

    def test_scourw3_four_errors_cannot_erase_the_original_or_claim_it_was_absent(self):
        self.exercise({1, 2, 3, 4})

    def test_prepublication_error_keeps_live_saves_and_the_verified_backup(self):
        # The backup-name parent check is listing 3; prepublication is listing 4.
        self.exercise({4})
        self.assertTrue(any(p.read_bytes() == OLD for p in self.saves.glob('backup-*/file0')))

    def test_real_enoent_reply_does_not_override_a_parent_listing_that_names_the_folder(self):
        self.exercise({1}, reply='550 No such file or directory')

    def test_first_import_with_no_save_folder_needs_no_overwrite_permission(self):
        self.saves.rmdir()
        (self.pc/'file0').write_bytes(NEW)
        # Both the saves-only and entire game-folder-absent cases use the fixture's
        # real socket reply: 550 No such file or directory, as documented for ftpd.
        for missing_game_folder in (False, True):
            with self.subTest(missing_game_folder=missing_game_folder):
                if missing_game_folder:
                    (self.saves/'file0').unlink()
                    self.saves.rmdir()
                    self.saves.parent.rmdir()
                expected = ftp_saves.inspect(self.address, UT)
                self.assertEqual(expected.files, {})
                result = ftp_saves.copy(self.address, UT, saves.scan_saves(str(self.pc)), expected, overwrite=False)
                self.assertEqual((self.saves/'file0').read_bytes(), NEW)
                self.assertIsNone(result.backup_dir)
                self.assertEqual(result.backed_up, 0)

    def test_ambiguous_or_broken_parent_listing_never_proves_absence(self):
        folder = '/3ds/undertale-3ds/saves'
        for rows in ([('SAVES', {'type': 'dir'})], [('', {})], [('junk', {})],
                     ftplib.error_perm('550 Input/output error'), ftplib.error_perm('550 Permission denied')):
            with self.subTest(rows=rows):
                ftp = mock.Mock()
                def listing(path, facts):
                    if path == folder:
                        raise ftplib.error_perm('550 No such file or directory')
                    if isinstance(rows, Exception):
                        raise rows
                    return iter(rows)
                ftp.mlsd.side_effect = listing
                with self.assertRaisesRegex(ftp_delivery.TransferError, 'saves folder could not be checked'):
                    ftp_saves.read_folder(ftp, folder)
                ftp.delete.assert_not_called()

    def test_unproven_prior_state_does_not_claim_no_saves_or_advise_deleting_them(self):
        exc = ftp_saves.IncompleteImport('listing failed', '/saves', None,
            ftp_saves.Snapshot({}, ''), [], {'file0': 'unsure'})
        for wizard in (False, True):
            with self.subTest(wizard=wizard):
                text = exc.describe(wizard=wizard)
                self.assertIn('No verified backup', text)
                self.assertNotIn('There were no 3DS saves', text)
                self.assertNotIn('go back to no saves', text)
                self.assertNotIn('delete file0', text)



class FinalListingSafetyTests(SaveFixture):
    def final_listing(self, empty):
        if not empty:
            (self.saves/'file0').write_bytes(OLD)
        (self.pc/'file0').write_bytes(NEW)
        folder = '/' + UT.sd_save_dir()
        published = False
        class FinalFailure(ftp_delivery.ConsoleFTP):
            def rename(self, source, destination):
                nonlocal published
                result = super().rename(source, destination)
                if destination == folder+'/file0':
                    published = True
                return result
            def mlsd(self, path='', facts=[]):
                if published and path == folder:
                    raise ftplib.error_perm('550 Input/output error')
                return super().mlsd(path, facts)
        expected = ftp_saves.inspect(self.address, UT)
        with self.assertRaises(ftp_saves.IncompleteImport) as caught:
            ftp_saves.copy(self.address, UT, saves.scan_saves(str(self.pc)), expected,
                           overwrite=not empty, factory=FinalFailure)
        exc = caught.exception
        self.assertEqual((self.saves/'file0').read_bytes(), NEW)
        self.assertEqual(exc.states['file0'], 'unsure')
        for wizard in (True, False):
            text = exc.describe(wizard=wizard)
            self.assertIn('could not be read back after copying', text)
            self.assertNotIn('No saves were replaced', text)
            if empty:
                self.assertIn('There were no 3DS saves before this import.', text)
                self.assertIn('To go back to no saves instead, delete file0', text)
                self.assertNotIn('No verified backup', text)
        if not empty:
            self.assertEqual((self.card/exc.backup.lstrip('/')/'file0').read_bytes(), OLD)

    def test_final_verification_failure_names_readback_after_replacement(self):
        self.final_listing(False)

    def test_proven_empty_first_import_keeps_accurate_undo_advice(self):
        self.final_listing(True)

    def test_unreadable_resume_backup_stops_without_mutation_or_false_no_replacement_claim(self):
        (self.saves/'file0').write_bytes(OLD)
        (self.pc/'file0').write_bytes(NEW)
        folder = '/' + UT.sd_save_dir()
        class PublishStop(ftp_delivery.ConsoleFTP):
            def rename(self, source, destination):
                result = super().rename(source, destination)
                if destination == folder+'/file0':
                    raise ftplib.error_perm('550 invented interruption after replacement')
                return result
        scan = saves.scan_saves(str(self.pc))
        expected = ftp_saves.inspect(self.address, UT)
        with self.assertRaises(ftp_saves.IncompleteImport) as first:
            ftp_saves.copy(self.address, UT, scan, expected, overwrite=True, factory=PublishStop)
        stopped = first.exception
        before = {p.relative_to(self.card).as_posix(): p.read_bytes()
                  for p in self.card.rglob('*') if p.is_file()}
        class BackupFailure(ftp_delivery.ConsoleFTP):
            def mlsd(self, path='', facts=[]):
                if path == stopped.backup:
                    raise ftplib.error_perm('550 Input/output error')
                return super().mlsd(path, facts)
        expected = ftp_saves.inspect(self.address, UT)
        command_count = len(self.server.cmds)
        with self.assertRaisesRegex(ftp_delivery.TransferError, 'backup folder for the earlier save copy') as caught:
            ftp_saves.copy(self.address, UT, scan, expected, overwrite=True,
                           factory=BackupFailure, resume=stopped)
        self.assertNotIn('No saves were replaced', str(caught.exception))
        self.assertIn('Earlier copied saves and the backup are kept', str(caught.exception))
        self.assertEqual(before, {p.relative_to(self.card).as_posix(): p.read_bytes()
                         for p in self.card.rglob('*') if p.is_file()})
        self.assertFalse(any(cmd in ('STOR', 'DELE', 'RNFR', 'RNTO', 'MKD', 'RMD')
                             for cmd, _ in self.server.cmds[command_count:]))

if __name__ == '__main__':
    unittest.main()
