"""SD update lease and folder identity (outside audit DEEP-04/05, 2026-11-04). Invented files only; no card."""
import errno
import os
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / 'builder'), str(HERE)]
import deliver
import products
import sd_transaction as sd

UT = products.PRODUCTS['undertale']


def put(root, rel, data):
    path = Path(root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def inventory(root, updates=False):
    """The card's files. The update folder and its lease file are left out unless asked for (Windows refuses
    reads of a locked lease file)."""
    return {rel: path.read_bytes() for path in Path(root).rglob('*') if path.is_file()
            for rel in [path.relative_to(root).as_posix()] if updates or '-3ds-builder-update' not in rel}


def no_os_locks():
    """The real _lock, with the OS call failing as on a file system without locks."""
    def refuse(*args):
        raise OSError(errno.ENOLCK, 'fixture: no locks')
    if os.name == 'nt':
        import msvcrt
        return mock.patch.object(msvcrt, 'locking', side_effect=refuse)
    import fcntl
    return mock.patch.object(fcntl, 'flock', side_effect=refuse)


class Card(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.card, self.source, self.work = (self.root / name for name in ('card', 'game', 'work'))
        self.base = UT.sd_data_dir + '/'
        for name in ('data.win', 'undertale-3ds-o3ds.3dsx', 'install.json', 'saves/file0'):
            put(self.card, self.base + name, ('old ' + name).encode())
        self.items = []
        for name in ('data.win', 'undertale-3ds-o3ds.3dsx'):
            path = put(self.source, name, ('new ' + name).encode())
            self.items.append(deliver.CopyItem(str(path), self.base + name, path.stat().st_size))
        self.before = inventory(self.card, updates=True)

    def session(self):
        tx = sd.Transaction(self.card, UT)
        self.addCleanup(tx.release)
        return tx

    def stage(self, tx, data):
        put(tx.new, self.base + 'data.win', data)

    def copy(self):
        return deliver.copy_with_textures(str(self.card), self.items, UT, str(self.source), str(self.work),
                                          textures=False, log=lambda line: None)

    def folder(self):
        return self.card / ('.' + UT.key + '-3ds-builder-update')


class LeaseTests(Card):
    """DEEP-04: a second session must not treat a running update as abandoned and take it over."""

    def test_a_second_session_cannot_recover_or_restart_a_running_update(self):
        first = self.session()
        first.begin()
        self.stage(first, b'FIRST INSTALL')
        second = self.session()
        with self.assertRaises(sd.Busy):
            second.begin()
        with self.assertRaises(sd.Busy):
            second.recover()
        self.assertEqual((first.new / self.base / 'data.win').read_bytes(), b'FIRST INSTALL')
        first.publish()
        self.assertEqual((self.card / self.base / 'data.win').read_bytes(), b'FIRST INSTALL')
        self.assertFalse(self.folder().exists())
        self.assertFalse(first.lease.path.exists())  # No lease file left on the card.
        second.begin()  # Free again once the first has finished.
        second.recover()

    def test_a_copy_while_another_session_runs_is_refused_and_leaves_it_alone(self):
        first = self.session()
        first.begin()
        self.stage(first, b'FIRST INSTALL')
        with self.assertRaises(deliver.DeliverError) as caught:
            self.copy()
        self.assertEqual(str(caught.exception), deliver.BUSY_MESSAGE)
        self.assertEqual((first.new / self.base / 'data.win').read_bytes(), b'FIRST INSTALL')
        first.publish()
        self.assertEqual((self.card / self.base / 'data.win').read_bytes(), b'FIRST INSTALL')
        self.copy()  # And then an ordinary copy works.
        self.assertEqual((self.card / self.base / 'data.win').read_bytes(), b'new data.win')

    def test_a_copy_releases_the_lease_when_it_fails(self):
        with mock.patch.object(deliver.shutil, 'copy2', side_effect=OSError(28, 'fixture SD full')), \
                self.assertRaises(deliver.DeliverError):
            self.copy()
        self.assertEqual(inventory(self.card), self.before)
        self.copy()
        self.assertEqual((self.card / self.base / 'data.win').read_bytes(), b'new data.win')

    def test_another_process_holds_the_lease_until_it_dies_then_its_update_is_rolled_back(self):
        script = textwrap.dedent('''
            import os, sys
            from pathlib import Path
            sys.path[:0] = [sys.argv[1]]
            import products, sd_transaction as sd
            UT = products.PRODUCTS['undertale']
            tx = sd.Transaction(sys.argv[2], UT)
            tx.begin()
            for name in ('data.win', 'undertale-3ds-o3ds.3dsx'):
                path = tx.new / UT.sd_data_dir / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'CRASHED ' + name.encode())
            original = sd.replace
            def replace(source, destination):
                original(source, destination)
                if '-3ds-builder-update' not in str(destination):
                    print('ready', flush=True)
                    sys.stdin.readline()
                    os._exit(1)  # The builder dies partway through publishing: no rollback, no cleanup.
            sd.replace = replace
            tx.publish()
        ''')
        child = subprocess.Popen([sys.executable, '-I', '-B', '-c', script, str(HERE / 'builder'), str(self.card)],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertNotEqual(inventory(self.card), self.before)  # A live file is already the crashed copy's.
            with self.assertRaises(sd.Busy):
                self.session().recover()
            with self.assertRaises(deliver.DeliverError):
                self.copy()
        finally:
            child.stdin.write('\n')
            child.stdin.close()
            child.wait(30)
            child.stdout.close()
        self.session().recover()  # Its lock went with it: the folder is stale and is rolled back.
        self.assertEqual(inventory(self.card, updates=True), self.before)  # Lease file gone too.
        self.copy()
        self.assertEqual((self.card / self.base / 'data.win').read_bytes(), b'new data.win')

    def test_without_file_locks_nothing_is_copied(self):
        # R175 F1: the in-process registry and the publish-time owner check don't keep another process out, so a
        # card whose file system can't lock files is refused before anything on it changes.
        stubs = (('the OS lock call fails', no_os_locks),
                 ('the old False result', lambda: mock.patch.object(sd, '_lock', return_value=False)))
        for name, stub in stubs:
            with self.subTest(stub=name), stub():
                for start in ('begin', 'recover'):
                    with self.assertRaises(sd.NoLock):
                        getattr(self.session(), start)()
                with self.assertRaises(deliver.DeliverError) as caught:
                    self.copy()
                self.assertEqual(str(caught.exception), deliver.NO_LOCK_MESSAGE)
                self.assertEqual(inventory(self.card), self.before)
                self.assertFalse(self.folder().exists())

    def test_without_file_locks_a_second_process_cannot_take_a_live_staging(self):
        # The reviewer's R175 F1 case: with no lock, process B began and deleted process A's live staging.
        script = textwrap.dedent('''
            import sys
            from pathlib import Path
            sys.path.insert(0, sys.argv[1])
            import products, sd_transaction as sd
            sd._lock = lambda stream: False
            tx = sd.Transaction(sys.argv[2], products.PRODUCTS['undertale'])
            try:
                tx.begin()
                print('BEGAN')
            except sd.NoLock:
                print('REFUSED')
            print('STAGING', Path(sys.argv[3]).exists())
        ''')
        first = self.session()
        first.begin()
        self.stage(first, b'FIRST STILL ACTIVE')
        staged = first.new / self.base / 'data.win'
        child = subprocess.run([sys.executable, '-B', '-I', '-c', script, str(HERE / 'builder'), str(self.card),
                                str(staged)], stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(child.stdout.split(), ['REFUSED', 'STAGING', 'True'])
        self.assertEqual(staged.read_bytes(), b'FIRST STILL ACTIVE')

    def test_publish_refuses_a_folder_another_session_has_taken(self):
        first = self.session()
        first.begin()
        self.stage(first, b'FIRST INSTALL')
        other = 'builder SD transaction v2: %s %s\n' % (UT.key, 'f' * 32)
        (self.folder() / 'owner.json').write_bytes(other.encode('ascii'))
        with self.assertRaises(OSError):
            first.publish()
        self.assertEqual(inventory(self.card), self.before)
        self.assertEqual((first.new / self.base / 'data.win').read_bytes(), b'FIRST INSTALL')


class FolderIdentityTests(Card):
    """DEEP-05: a stop while the update folder's marker is being made or removed must not block later copies."""

    def test_a_stop_before_the_marker_exists_is_cleaned_up_by_the_next_copy(self):
        original = Path.open
        for when in ('open', 'fsync'):
            with self.subTest(when=when):
                tx = self.session()
                def fail_open(path, *args, **kwargs):
                    if path.name == 'owner.json.part' and when == 'open':
                        raise OSError(errno.ENOSPC, 'fixture card full')
                    return original(path, *args, **kwargs)
                def fail_fsync(fd):
                    raise OSError(errno.EIO, 'fixture card removed')
                with mock.patch.object(Path, 'open', new=fail_open), \
                        mock.patch.object(sd.os, 'fsync', side_effect=fail_fsync if when == 'fsync' else os.fsync), \
                        self.assertRaises(OSError):
                    tx.begin()
                tx.release()
                self.assertTrue(self.folder().is_dir())
                self.assertFalse((self.folder() / 'owner.json').exists())
                self.session().recover()
                self.assertFalse(self.folder().exists())
                self.assertEqual(inventory(self.card), self.before)

    def test_a_stop_at_any_cleanup_step_is_finished_by_the_next_copy(self):
        folder = self.folder()
        steps = {
            'journal': (Path, 'unlink', lambda path: path.name == 'journal.json'),
            'staging': (sd.shutil, 'rmtree', lambda path: path.name in ('new', 'old')),
            'marker': (Path, 'unlink', lambda path: path.name == 'owner.json'),
            'folder': (sd.os, 'rmdir', lambda path: path == folder),
        }
        for step, (where, name, hit) in steps.items():
            with self.subTest(step=step):
                original = getattr(where, name)
                state = {'left': 1}
                def guarded(*args, **kwargs):
                    if state['left'] and hit(Path(args[0])):
                        state['left'] = 0
                        raise OSError(errno.EIO, 'fixture card removed during cleanup')
                    return original(*args, **kwargs)
                tx = self.session()
                tx.begin()
                for item in self.items:
                    put(tx.new, item.dst, Path(item.src).read_bytes())
                with mock.patch.object(where, name, new=guarded), self.assertRaises(OSError):
                    tx.publish()
                self.assertFalse(state['left'])
                tx.release()
                self.assertTrue(folder.exists())
                self.session().recover()
                self.assertFalse(folder.exists())
                for item in self.items:
                    self.assertEqual((self.card / item.dst).read_bytes(), Path(item.src).read_bytes())
                    put(self.card, item.dst, ('old ' + Path(item.dst).name).encode())

    def test_a_marked_folder_made_by_begin_with_a_backup_beside_it_is_kept(self):
        # R175b F2, the reviewer's own steps: a real begin(), a player's backup added, then a later recovery.
        for name in ('settings.ini', 'saves/file0', 'rescued/saves/file0'):
            with self.subTest(name=name):
                tx = self.session()
                tx.begin()
                put(self.folder(), name, b'foreign player backup')
                tx.release()
                with self.assertRaises(OSError) as caught:
                    self.session().recover()
                self.assertEqual(str(caught.exception), sd.UNRECOGNISED)
                self.assertEqual((self.folder() / name).read_bytes(), b'foreign player backup')
                shutil.rmtree(self.folder())
                self.assertEqual(inventory(self.card), self.before)

    def test_a_marker_cut_short_or_an_empty_layout_is_finished(self):
        # R175 F2: without owner.json only begin()'s first step (a partial marker) or empty folders are cleaned up.
        full = ('builder SD transaction v2: %s %s\n' % (UT.key, '0123456789abcdef' * 2)).encode('ascii')
        legacy = ('builder SD transaction v1: %s\n' % UT.key).encode('ascii')
        cases = {'empty': {}, 'empty layout': {'new/3ds/': None, 'old/': None},
                 'empty marker': {'owner.json.part': b''}, 'cut short': {'owner.json.part': full[:40]},
                 'zero tail': {'owner.json.part': full[:50] + b'\0' * 30}, 'whole': {'owner.json.part': full},
                 'older builder': {'owner.json.part': legacy, 'new/': None}}
        for name, content in cases.items():
            with self.subTest(case=name):
                self.folder().mkdir()
                for rel, data in content.items():
                    if data is None:
                        (self.folder() / rel).mkdir(parents=True)
                    else:
                        put(self.folder(), rel, data)
                self.session().recover()
                self.assertFalse(self.folder().exists())
                self.assertEqual(inventory(self.card), self.before)

    def test_an_unmarked_folder_with_files_or_a_journal_is_kept(self):
        # R175 F2: no marker means no proof the files are ours, even in the update layout. The reviewer's case is a
        # save backup alone below old/; an older builder's half-cleaned folder with a journal is kept the same way.
        full = ('builder SD transaction v2: %s %s\n' % (UT.key, '0' * 32)).encode('ascii')
        cases = {
            'save below old': {'old/' + self.base + 'saves/file0': b'unrecognised save backup'},
            'game file below old': {'old/' + self.base + 'data.win': b'old backup'},
            'file below new': {'new/3ds/notes.txt': b'not proven ours'},
            'journal': {'journal.json': b'{"state": "committed", "entries": []}\n'},
            'journal part': {'journal.part': b'{}'},
            'other marker part': {'owner.json.part': b'builder SD transaction v2: other-game ' + b'0' * 32},
            'marker part with more': {'owner.json.part': full + b'extra'},
            'marker part not hex': {'owner.json.part': full[:-10] + b'XYZ'},
        }
        for name, content in cases.items():
            with self.subTest(case=name):
                self.folder().mkdir()
                for rel, data in content.items():
                    put(self.folder(), rel, data)
                for start in (lambda: self.session().recover(), self.copy):
                    with self.assertRaises((OSError, deliver.DeliverError)) as caught:
                        start()
                    if isinstance(caught.exception, OSError):
                        self.assertEqual(str(caught.exception), sd.UNRECOGNISED)
                    for rel, data in content.items():
                        self.assertEqual((self.folder() / rel).read_bytes(), data)
                shutil.rmtree(self.folder())
                self.assertEqual(inventory(self.card), self.before)

    def test_an_older_builders_interrupted_publish_is_still_rolled_back(self):
        folder = self.folder()
        put(folder, 'owner.json', ('builder SD transaction v1: ' + UT.key + '\n').encode('ascii'))
        name = self.base + 'data.win'
        put(folder, 'old/' + name, self.before[name])
        put(self.card, name, b'half published')
        put(folder, 'journal.json',
            ('{"state": "publishing", "entries": [{"path": "%s", "existed": true, "new": true}]}\n' % name).encode())
        self.session().recover()
        self.assertEqual(inventory(self.card), self.before)

    def test_a_folder_holding_anything_else_is_kept(self):
        folder = self.folder()
        v1 = ('builder SD transaction v1: ' + UT.key + '\n').encode('ascii')
        v2 = ('builder SD transaction v2: %s %s\n' % (UT.key, 'a' * 32)).encode('ascii')
        for content in ({'notes.txt': b'not ours'}, {'owner.json': b'someone else\n', 'new/x': b'x'},
                        # R175 F2: the reviewer's save backup, unmarked and under either marker; a builder never
                        # stages or backs up saves or settings, so a folder holding them is not ours to delete.
                        {'old/' + self.base + 'saves/file0': b'unrecognised save backup'},
                        {'owner.json': v1, 'old/' + self.base + 'saves/file0': b'unrecognised save backup'},
                        {'owner.json': v2, 'old/' + self.base + 'SAVES/file0': b'unrecognised save backup'},
                        {'owner.json': v2, 'new/' + self.base + 'settings.ini': b'not staged by a builder'},
                        # R175b F2: the reviewer's player backups beside new/ and old/, under either marker. Cleanup
                        # deletes every top-level entry, so a marked folder may hold nothing but its own layout.
                        *({'owner.json': marker, name: b'foreign player backup'}
                          for marker in (v1, v2) for name in ('settings.ini', 'saves/file0', 'rescued/saves/file0',
                                                              'notes.txt', 'NEW/x')),
                        {'owner.json': v2, 'journal.json/x': b'a folder where the journal goes'},
                        {'owner.json': v2, 'new': b'a file where new/ goes'}):
            with self.subTest(content=sorted(content)):
                for rel, data in content.items():
                    put(folder, rel, data)
                with self.assertRaises(OSError) as caught:
                    self.session().recover()
                self.assertEqual(str(caught.exception), sd.UNRECOGNISED)
                for rel, data in content.items():
                    self.assertEqual((folder / rel).read_bytes(), data)
                with self.assertRaises(deliver.DeliverError):
                    self.copy()
                shutil.rmtree(folder)
                self.assertEqual(inventory(self.card), self.before)


if __name__ == '__main__':
    unittest.main()
