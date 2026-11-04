"""SCOURSOL4-001: an import never replaces a 3DS save before its backup reads back byte for byte.
Invented files and loopback FTP only; never a console."""
from pathlib import Path
import sys
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from test_builder_save_audit import SaveFixture, UT
import ftp_delivery
import ftp_saves
import saves

OLD = {'file0': b'OLD\n1\n0\n', 'file9': b'OLD9\n1\n0\n', 'undertale.ini': b'[General]\nName="OLD"\nLove="1"\n'}
NEW = {'file0': b'NEW\n2\n0\n', 'undertale.ini': b'[General]\nName="NEW"\nLove="2"\n'}


class BackupReadBackTests(SaveFixture):

    def prepare(self, old=OLD):
        for name, data in old.items():
            (self.saves/name).write_bytes(data)
        for name, data in NEW.items():
            (self.pc/name).write_bytes(data)
        scan = saves.scan_saves(str(self.pc))
        self.assertFalse(scan.has_corrupt)
        return scan

    def backups(self):
        return [p for p in self.saves.iterdir() if p.is_dir() and p.name.startswith('backup-')]

    def assert_untouched(self, old=OLD):
        self.assertEqual(self.live(), old)
        self.assertEqual(self.backups(), [])
        self.assertEqual(sorted(p.name for p in self.saves.rglob('*.part')), [])
        self.assertEqual({p.name: p.read_bytes() for p in self.pc.iterdir()}, NEW)

    def refused(self, scan):
        with self.assertRaises(saves.DeliverError) as caught:
            saves.copy_pc_saves(str(self.card), UT, scan, overwrite=True)
        self.assertEqual(str(caught.exception), saves.BACKUP_MISMATCH_MESSAGE)
        return caught.exception

    def test_a_backup_the_card_stores_wrongly_stops_the_import_before_any_save_changes(self):
        # The reviewer's fault model (change-scoursol4 test_sd_save_backups.py): the card keeps other bytes.
        scan = self.prepare()
        real_utime = saves.os.utime
        def damage(path, *args, **kwargs):
            real_utime(path, *args, **kwargs)
            if Path(path).parent.name.startswith('backup-') and Path(path).name == 'file0.part':
                Path(path).write_bytes(b'BAD\n1\n0\n')
        with mock.patch.object(saves.os, 'utime', side_effect=damage):
            self.refused(scan)
        self.assert_untouched()

    def test_a_backup_that_changes_once_renamed_is_refused_too(self):
        scan = self.prepare()
        real_replace = saves.os.replace
        def damage(src, dst, *args, **kwargs):
            real_replace(src, dst, *args, **kwargs)
            if Path(dst).parent.name.startswith('backup-') and Path(dst).name == 'file0':
                Path(dst).write_bytes(b'OLD\n1\n')  # Shorter: a lost tail is a mismatch, not a prefix match.
        with mock.patch.object(saves.os, 'replace', side_effect=damage):
            self.refused(scan)
        self.assert_untouched()

    def test_the_second_backup_failing_leaves_every_live_save_as_it_was(self):
        scan = self.prepare()
        real_utime = saves.os.utime
        seen = []
        def damage(path, *args, **kwargs):
            real_utime(path, *args, **kwargs)
            if Path(path).parent.name.startswith('backup-') and str(path).endswith('.part'):
                seen.append(Path(path).name)
                if len(seen) == 2:
                    Path(path).write_bytes(Path(path).read_bytes() + b'\0')  # Longer: also a mismatch.
        with mock.patch.object(saves.os, 'utime', side_effect=damage):
            self.refused(scan)
        self.assertEqual(len(seen), 2)
        self.assert_untouched()

    def test_an_ordinary_import_keeps_an_exact_backup_of_every_old_file(self):
        old = dict(OLD, **{'unknown.bin': bytes(range(256)) * 300})  # Larger than one read block.
        scan = self.prepare(old)
        result = saves.copy_pc_saves(str(self.card), UT, scan, overwrite=True)
        self.assertEqual(self.live(), NEW)
        backup = Path(result.backup_dir)
        self.assertEqual({p.name: p.read_bytes() for p in backup.iterdir()}, old)

    def test_same_bytes_compares_every_byte_and_the_length(self):
        a, b = self.root/'a', self.root/'b'
        data = bytes(range(256)) * 600
        for other, same in ((data, True), (data[:-1], False), (data + b'x', False),
                            (data[:70000] + b'\0' + data[70001:], False), (b'', False)):
            a.write_bytes(data)
            b.write_bytes(other)
            self.assertIs(saves._same_bytes(str(a), str(b)), same)
        a.write_bytes(b'')
        self.assertIs(saves._same_bytes(str(a), str(b)), True)

    def test_ftp_import_refuses_a_backup_upload_the_card_stores_wrongly(self):
        # Each save-sized upload is hash-checked before its rename (MAX_SAVE_BYTES <= SMALL).
        self.assertLessEqual(saves.MAX_SAVE_BYTES, ftp_delivery.SMALL)
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        self.server.corrupt_stor = {'backup-': -1}  # Every backup upload lands with its first byte flipped.
        with self.assertRaises(ftp_delivery.TransferError):
            ftp_saves.copy(self.address, UT, scan, expected, overwrite=True)
        self.assertEqual(self.live(), OLD)


class FtpBackupReadBackTests(SaveFixture):
    """R181 F1: the Wi-Fi import reads the published backup folder back before any live save is staged or replaced.
    A transfer checks each upload before its rename, so damage after the rename needs this check."""
    prepare = BackupReadBackTests.prepare

    def run_with_damage(self, damage_name, damage):
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        real_upload = ftp_delivery.Transfer.upload
        damaged = []
        def upload(transfer, item):
            real_upload(transfer, item)
            parts = item.dst.split('/')
            if parts[-2].startswith('backup-') and parts[-1] == damage_name:
                final = self.saves/parts[-2]/parts[-1]
                final.write_bytes(damage(final.read_bytes()))  # The card keeps other bytes after the rename.
                damaged.append(final)
        with mock.patch.object(ftp_delivery.Transfer, 'upload', upload):
            with self.assertRaises(ftp_saves.BackupMismatch) as caught:
                ftp_saves.copy(self.address, UT, scan, expected, overwrite=True)
        self.assertEqual(len(damaged), 1)
        self.assertEqual(str(caught.exception), ftp_saves.BACKUP_MISMATCH_MESSAGE)
        self.assertEqual(ftp_saves.error_text(caught.exception), ftp_saves.BACKUP_MISMATCH_MESSAGE)
        self.assertEqual(self.live(), OLD)  # Nothing staged or replaced.
        self.assertEqual(sorted(p.name for p in self.saves.rglob('*') if p.is_file() and p.parent != self.saves), [])
        self.assertEqual({p.name: p.read_bytes() for p in self.pc.iterdir()}, NEW)

    def test_same_length_damage_after_the_rename_is_refused(self):
        self.run_with_damage('file0', lambda data: b'BAD' + data[3:])  # The reviewer's OLD -> BAD, same length.

    def test_a_shorter_backup_after_the_rename_is_refused(self):
        self.run_with_damage('undertale.ini', lambda data: data[:-1])

    def test_a_longer_backup_after_the_rename_is_refused(self):
        self.run_with_damage('file9', lambda data: data + b'x')

    def test_a_backup_grown_past_a_save_is_refused(self):
        self.run_with_damage('file9', lambda data: data + b'x' * (saves.MAX_SAVE_BYTES + 1))

    def test_an_ordinary_ftp_import_keeps_an_exact_backup(self):
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        result = ftp_saves.copy(self.address, UT, scan, expected, overwrite=True)
        self.assertEqual(self.live(), NEW)
        backup = self.card/result.backup_dir.lstrip('/')
        self.assertEqual({p.name: p.read_bytes() for p in backup.iterdir()}, OLD)


class CapitalsFTP(ftp_delivery.ConsoleFTP):
    """Lists the backup folder's names in capitals, as a FAT card may; the files are the same."""
    def mlsd(self, path='', facts=[]):
        for name, row in super().mlsd(path, facts):
            yield (name.upper() if '/backup-' in path else name), row


class FtpBackupNameTests(SaveFixture):
    """R190 LOW 1: backup names are matched the way FAT matches them (AUD-02)."""
    prepare = BackupReadBackTests.prepare

    def test_a_correct_backup_listed_in_capitals_is_accepted(self):
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        result = ftp_saves.copy(self.address, UT, scan, expected, overwrite=True, factory=CapitalsFTP)
        self.assertEqual(self.live(), NEW)
        backup = self.card/result.backup_dir.lstrip('/')
        self.assertEqual({p.name: p.read_bytes() for p in backup.iterdir()}, OLD)

    def test_folded_names_keep_the_exact_set_and_bytes(self):
        same = ftp_saves.same_files
        self.assertTrue(same({'FILE0': b'a', 'Undertale.ini': b'b'}, {'file0': b'a', 'undertale.ini': b'b'}))
        self.assertFalse(same({'FILE0': b'a'}, {'file0': b'b'}))
        self.assertFalse(same({'file0': b'a'}, {'file0': b'a', 'file9': b'a'}))
        self.assertFalse(same({'FILE0': b'a', 'file0': b'a'}, {'file0': b'a'}))  # Two names can't be one FAT file.
        self.assertFalse(same({'file0': b'a'}, {'FILE0': b'a', 'file0': b'a'}))
        self.assertTrue(same({}, {}))


class UnreadableBackupTests(SaveFixture):
    """R190 LOW 2: a backup the card won't read back takes the mismatch path; a dropped connection says so."""
    prepare = BackupReadBackTests.prepare

    def run_with_read_error(self, error):
        class Failing(ftp_delivery.ConsoleFTP):
            def retrbinary(self, cmd, *args, **kwargs):
                if '/backup-' in cmd and not cmd.endswith('.builder-part'):  # The read-back, not the upload's check.
                    raise error
                return super().retrbinary(cmd, *args, **kwargs)
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        with self.assertRaises(ftp_delivery.TransferError) as caught:
            ftp_saves.copy(self.address, UT, scan, expected, overwrite=True, factory=Failing)
        self.assertEqual(self.live(), OLD)  # Nothing staged or replaced.
        self.assertFalse([c for c in self.server.cmds if c[0] == 'STOR' and c[1].endswith('.save-part')])
        return caught.exception

    def backup_files(self):
        return sorted(p.name for p in self.saves.rglob('*') if p.is_file() and p.parent != self.saves)

    def test_a_refused_backup_read_is_a_mismatch_and_the_backup_is_removed(self):
        import ftplib
        for error in (ftplib.error_perm('550 backup unreadable'), ftplib.error_temp('451 read failed'),
                      OSError(5, 'invented read error')):
            with self.subTest(error=error):
                exc = self.run_with_read_error(error)
                self.assertIsInstance(exc, ftp_saves.BackupMismatch)
                self.assertEqual(ftp_saves.error_text(exc), ftp_saves.BACKUP_MISMATCH_MESSAGE)
                self.assertEqual(self.backup_files(), [])

    def test_a_dropped_connection_while_checking_is_reported_as_one(self):
        for error in (EOFError(), ConnectionResetError(104, 'invented reset')):
            with self.subTest(error=type(error).__name__):
                exc = self.run_with_read_error(error)
                self.assertNotIsInstance(exc, ftp_saves.BackupMismatch)
                self.assertIn('connection', ftp_saves.error_text(exc).lower())


class BackupFolderCollisionTests(SaveFixture):
    """R190 LOW 3: the backup folder must be new, so a mismatch can never delete from an older backup."""
    prepare = BackupReadBackTests.prepare

    def refuse_collision(self, older_name='backup-FIXED-12345678', factory=ftp_delivery.ConsoleFTP):
        scan = self.prepare()
        expected = ftp_saves.inspect(self.address, UT)
        older = self.saves/older_name
        older.mkdir()
        kept = dict(OLD, **{'extra.bin': b'invented older backup file'})
        for name, data in kept.items():
            (older/name).write_bytes(data)
        uuid = mock.Mock(hex='12345678' + '0' * 24)
        with mock.patch.object(ftp_saves.time, 'strftime', return_value='FIXED'), \
                mock.patch.object(ftp_saves.uuid, 'uuid4', return_value=uuid):
            with self.assertRaises(ftp_delivery.TransferError) as caught:
                ftp_saves.copy(self.address, UT, scan, expected, overwrite=True, factory=factory)
        self.assertEqual(str(caught.exception), ftp_saves.BACKUP_FOLDER_MESSAGE)
        self.assertEqual({p.name: p.read_bytes() for p in older.iterdir()}, kept)
        self.assertEqual(self.live(), OLD)
        self.assertFalse([c for c in self.server.cmds if c[0] in ('STOR', 'DELE', 'RNFR')])

    def test_an_existing_folder_with_the_backup_name_is_refused_and_kept(self):
        self.refuse_collision()

    def test_an_ftpd_that_answers_250_for_an_existing_folder_is_still_refused(self):
        # R190b: ftpd v2.3.1 sends 250 OK when MKD finds the folder already there.
        self.server.mkd_exists_reply = '250 OK'
        self.refuse_collision()
        self.assertFalse([c for c in self.server.cmds if c[0] == 'MKD' and '/backup-' in c[1]])

    def test_an_existing_folder_spelled_in_other_capitals_is_refused(self):
        self.server.mkd_exists_reply = '250 OK'
        self.refuse_collision('BACKUP-fixed-12345678')

    def test_a_listing_that_fails_refuses_the_backup_folder(self):
        import ftplib
        class NoListing(ftp_delivery.ConsoleFTP):
            def mlsd(self, path='', facts=[]):
                if path.endswith('/saves') and list(facts) == ['type']:  # The name check's listing only.
                    raise ftplib.error_perm('500 listing refused')
                return super().mlsd(path, facts)
        self.server.mkd_exists_reply = '250 OK'
        self.refuse_collision(factory=NoListing)

    def faulty(self, parent_rows=None, omit_backup=False, child_reply=None):
        """R190c fault injection on the name check only (its MLSDs ask for the type fact alone): the saves
        folder's listing is replaced by raw `parent_rows` (fed through ftplib's own parser) or loses the backup's
        row, and listing the backup itself fails with `child_reply` after sending its rows."""
        import ftplib
        class Faulty(ftp_delivery.ConsoleFTP):
            raw = None
            def retrlines(self, cmd, callback=None):
                if self.raw is None:
                    return super().retrlines(cmd, callback)
                for line in self.raw:
                    callback(line)
                return '226 done'
            def mlsd(self, path='', facts=[]):
                check = list(facts) == ['type']
                if check and '/backup-' in path and child_reply:
                    list(super().mlsd(path, facts))  # Its rows arrive; ftplib raises only at the end.
                    raise ftplib.error_perm(child_reply)
                if check and path.endswith('/saves') and parent_rows is not None:
                    self.raw = parent_rows
                    try:
                        return list(super().mlsd(path, facts))
                    finally:
                        self.raw = None
                rows = list(super().mlsd(path, facts))
                if check and path.endswith('/saves') and omit_backup:
                    rows = [(n, f) for n, f in rows if not n.casefold().startswith('backup-')]
                return rows
        return Faulty

    def test_a_malformed_listing_and_a_refused_child_are_no_proof_the_name_is_free(self):
        # The reviewer's path (c26rev5 R190c): ftplib parses 'broken' as name '' with facts {'broke': ''}.
        self.server.mkd_exists_reply = '250 OK'
        self.refuse_collision(factory=self.faulty(['broken'], child_reply='550 Input/output error'))
        self.assertFalse([c for c in self.server.cmds if c[0] == 'MKD' and '/backup-' in c[1]])

    def test_a_malformed_listing_refuses_even_when_the_child_is_missing(self):
        for rows in (['broken'], ['modify=20260101000000; file0'], ['type=???; file0'], ['type=dir; ']):
            with self.subTest(rows=rows):
                self.tearDown()
                self.setUp()
                self.server.mkd_exists_reply = '250 OK'
                self.refuse_collision(factory=self.faulty(rows, child_reply='550 No such file or directory'))

    def test_a_listing_that_misses_the_folder_and_a_child_read_error_are_no_proof_either(self):
        # The reviewer's double false negative: the parent listing silently drops the backup's row, and the
        # existing backup's own listing sends its rows, then ends with a 550 read error.
        self.server.mkd_exists_reply = '250 OK'
        self.refuse_collision(factory=self.faulty(omit_backup=True, child_reply='550 Input/output error'))
        self.assertFalse([c for c in self.server.cmds if c[0] == 'MKD' and '/backup-' in c[1]])

    def test_only_ftpds_missing_path_reply_counts_as_absence(self):
        for reply in ('550 Input/output error', '550 Permission denied', '550 none', '550'):
            with self.subTest(reply=reply):
                self.tearDown()
                self.setUp()
                self.server.mkd_exists_reply = '250 OK'
                self.refuse_collision(factory=self.faulty(omit_backup=True, child_reply=reply))

    def test_an_ordinary_import_on_an_ftpd_that_answers_250_still_backs_up(self):
        self.server.mkd_exists_reply = '250 OK'
        scan = self.prepare()
        result = ftp_saves.copy(self.address, UT, scan, ftp_saves.inspect(self.address, UT), overwrite=True)
        self.assertEqual(self.live(), NEW)
        backup = self.card/result.backup_dir.lstrip('/')
        self.assertEqual({p.name: p.read_bytes() for p in backup.iterdir()}, OLD)

    def test_no_old_saves_needs_no_backup_folder(self):
        for name, data in NEW.items():
            (self.pc/name).write_bytes(data)
        scan = saves.scan_saves(str(self.pc))
        result = ftp_saves.copy(self.address, UT, scan, ftp_saves.inspect(self.address, UT), overwrite=True)
        self.assertIsNone(result.backup_dir)
        self.assertEqual(self.live(), NEW)
        self.assertFalse([p for p in self.saves.iterdir() if p.is_dir()])


if __name__ == '__main__':
    unittest.main()
