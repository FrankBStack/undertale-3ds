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


if __name__ == '__main__':
    unittest.main()
