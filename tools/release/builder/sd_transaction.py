"""Recoverable SD update of explicit installer files; saves and unknown files never participate.

Stage the whole new set on the card before changing final names. A durable journal
and rename backups allow ordinary failures to roll back, and a later run to recover
after card removal/power loss. FAT does not offer a multi-file atomic rename: don't
start the game while the copy is running or before an interrupted copy is retried.
"""
import contextlib
import errno
import json
import os
from pathlib import Path
import re
import shutil
import stat
import threading
import uuid

import install_record

BUSY = 'Another copy to this SD card is running'
UNRECOGNISED = 'Unrecognised SD update folder; keep it and choose another card'
# A folder without owner.json is ours only at its two ends (R175 F2): begin() writes owner.json.part, then the marker,
# before it makes new/ and old/; cleanup removes the marker after everything else. So it may hold owner.json.part and
# empty new/ and old/ folders, never a journal or a file.
MARKERLESS = ('new', 'old', 'owner.json.part')
# All a marked folder of ours can hold at its top: the marker, the journal and the two payload folders (R175b F2).
MARKED = {'owner.json': 'file', 'owner.json.part': 'file', 'journal.json': 'file', 'journal.part': 'file',
          'new': 'dir', 'old': 'dir'}
# Never inside an update folder of ours: saves and the game's own runtime files are not staged or backed up there.
NEVER_STAGED = {'saves', 'settings.ini', 'log.txt', 'crash.txt', 'hang.txt'}

# Conservative FAT32 allocation, including cards formatted with 64 KiB clusters.
CLUSTER = 65536


def space_required(sizes, paths=()):
    files = sum(max(1, (size + CLUSTER - 1) // CLUSTER) * CLUSTER for size in sizes)
    # Inventory and the journal have bounded per-file records, plus rename/dir entries.
    names = list(paths)
    metadata = 1024 + sum(512 + len(name.encode('utf-8')) * 8 for name in names)
    return files + ((metadata + CLUSTER - 1) // CLUSTER + len(names) + 8) * CLUSTER


def sync_file(path):
    # Windows FlushFileBuffers requires a writable handle. These are our staged copies only.
    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
    with open(path, 'r+b') as stream:
        os.fsync(stream.fileno())


def sync_directory(path):
    # Windows does not expose directory fsync via os.open. File flushes are mandatory.
    if os.name != 'nt':
        fd = os.open(path, os.O_RDONLY)
        try:
            try:
                os.fsync(fd)
            except OSError as error:
                # Some removable filesystems on macOS do not support directory fsync.
                # Staged file/journal flushes above remain mandatory on every host.
                if error.errno not in (errno.EINVAL, errno.ENOTSUP):
                    raise
        finally:
            os.close(fd)


def replace(source, destination):
    os.replace(source, destination)
    sync_directory(Path(destination).parent)
    if Path(source).parent != Path(destination).parent:
        sync_directory(Path(source).parent)


class Busy(OSError):
    """Another builder session holds this card's update lease."""


class NoLock(OSError):
    """The file system can't give a lease across processes, so the operation is refused (R175 F1): the in-process
    registry and the owner check at publish do not keep another builder process out."""


_HELD = set()  # Lease files this process holds: two sessions in one builder exclude each other on every host.
_HELD_LOCK = threading.Lock()
_BUSY_ERRNOS = {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, errno.EDEADLK, getattr(errno, 'EDEADLOCK', errno.EDEADLK)}
_NO_LOCKS = {errno.ENOTSUP, errno.EOPNOTSUPP, errno.ENOLCK, errno.EINVAL, errno.ENOSYS}


def _lock(stream):
    """A non-blocking exclusive OS lock on the open lease file. NoLock where the file system has no locks."""
    try:
        if os.name == 'nt':
            import msvcrt
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        if error.errno in _BUSY_ERRNOS:
            raise Busy(BUSY) from error
        if error.errno in _NO_LOCKS:
            raise NoLock(error.errno, 'File locks are not available here') from error
        raise
    return True


def _same_file(stream, path):
    try:
        found = os.stat(path)
    except FileNotFoundError:
        return False
    held = os.fstat(stream.fileno())
    return (held.st_dev, held.st_ino) == (found.st_dev, found.st_ino)


class Lease:
    """One builder session's claim on a card's update folder, from recovery through staging, publication and
    cleanup. The OS drops the lock when its process ends, so a session that crashed or lost the card is stale and
    its folder is safe to recover; a running one makes others stop with Busy."""

    def __init__(self, path):
        self.path, self.stream, self.locked = Path(path), None, False
        self.key = os.path.normcase(str(self.path))

    @property
    def held(self):
        return self.stream is not None

    def acquire(self):
        with _HELD_LOCK:
            if self.key in _HELD:
                raise Busy(BUSY)
            _HELD.add(self.key)
        try:
            for _ in range(8):
                stream = open(self.path, 'a+b')
                try:
                    if not _lock(stream):
                        raise NoLock(errno.ENOLCK, 'File locks are not available here')
                    # POSIX release unlinks the file while locked; if that happened since our open, lock the new one.
                    if os.name != 'nt' and not _same_file(stream, self.path):
                        stream.close()
                        continue
                except BaseException:
                    stream.close()
                    raise
                self.stream, self.locked = stream, True
                return
            raise Busy(BUSY)
        except BaseException:
            with _HELD_LOCK:
                _HELD.discard(self.key)
            raise

    def release(self):
        stream, self.stream = self.stream, None
        if stream is None:
            return
        try:
            if os.name != 'nt':
                try:
                    self.path.unlink()  # Still locked, so a session waiting on this file sees it go and retries.
                except OSError:
                    pass
            elif self.locked:
                import msvcrt
                try:
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            stream.close()
            if os.name == 'nt':
                try:
                    self.path.unlink()
                except OSError:
                    pass  # Another session has it open now and removes it when it is done.
        finally:
            with _HELD_LOCK:
                _HELD.discard(self.key)

    def __del__(self):
        try:
            self.release()
        except Exception:
            pass


class Transaction:
    def __init__(self, root, product):
        self.root, self.product = Path(root).resolve(), product
        self.base = install_record.target(self.root, '.' + product.key + '-3ds-builder-update')
        self.new, self.old = self.base / 'new', self.base / 'old'
        self.journal = self.base / 'journal.json'
        self.operation = uuid.uuid4().hex  # Written in owner.json: which session's staging this is.
        self.lease = Lease(install_record.target(self.root, '.' + product.key + '-3ds-builder-update.lock'))
        self.pinned = False

    def acquire(self):
        """Hold the card's update lease until release(). Raises Busy while another session holds it."""
        if not self.lease.held:
            self.lease.acquire()
        self.pinned = True

    def release(self):
        self.pinned = False
        self.lease.release()

    def _hold(self):
        if not self.lease.held:
            self.lease.acquire()

    def _settle(self):
        # Without acquire(), a lease taken by recover()/begin() lasts until the update folder is gone.
        if not self.pinned and not (self.base.exists() or self.base.is_symlink()):
            self.lease.release()

    @contextlib.contextmanager
    def _step(self):
        # Without acquire(), a failed step gives the lease up. What it left on the card is then a stopped
        # session's, for the next recover().
        try:
            yield
        except BaseException:
            if not self.pinned:
                self.lease.release()
            raise

    def valid_name(self, name):
        return name == install_record.relative_path(self.product) or install_record.managed_path(self.product, name)

    def target(self, root, name):
        if not self.valid_name(name):
            raise OSError('Invalid SD update path')
        return install_record.target(root, name)

    def recover(self):
        """Finish or roll back a session that stopped, then remove its folder. Holding the lease means no running
        session owns the folder, so any owner of ours, this session or a stale one, is recovered."""
        self._hold()
        with self._step():
            self._recover()
            self._settle()

    def _recover(self):
        if not (self.base.exists() or self.base.is_symlink()):
            return
        marker = self.base / 'owner.json'
        if self.base.is_symlink() or not self.base.is_dir() or marker.is_symlink():
            raise OSError(UNRECOGNISED)
        if marker.exists():
            if not self.recognised(marker) or not self.contents_ours():
                raise OSError(UNRECOGNISED)
        elif not self.residue():
            raise OSError(UNRECOGNISED)
        if self.journal.exists() or self.journal.is_symlink():
            if self.journal.is_symlink() or self.journal.stat().st_size > install_record.MAX_BYTES:
                raise OSError('Invalid SD update journal')
            data = json.loads(self.journal.read_bytes())
            entries = data['entries']
            if data['state'] not in ('publishing', 'committed') or not isinstance(entries, list):
                raise OSError('Invalid SD update journal')
            seen = set()
            for entry in entries:
                name = entry['path']
                if (not self.valid_name(name) or name.casefold() in seen
                        or type(entry['existed']) is not bool or type(entry['new']) is not bool):
                    raise OSError('Invalid SD update journal')
                seen.add(name.casefold())
                for root in (self.root, self.old, self.new):
                    self.target(root, name)  # Reject redirected parents before any recovery writes.
            if data['state'] == 'publishing':
                for entry in reversed(entries):
                    final = self.target(self.root, entry['path'])
                    backup = self.target(self.old, entry['path'])
                    staged = self.target(self.new, entry['path'])
                    if backup.exists():
                        final.parent.mkdir(parents=True, exist_ok=True)
                        replace(backup, final)
                    elif not entry['existed'] and entry['new'] and not staged.exists():
                        final.unlink(missing_ok=True)
                        if final.parent.exists():
                            sync_directory(final.parent)
        self.cleanup()

    def cleanup(self):
        """Remove the folder with its identity last, so an interrupted cleanup is still recognised and finished.
        The journal goes first: once it is gone the card's files are final and the rest is only leftovers."""
        for name in ('journal.json', 'journal.part'):
            path = self.base / name
            if path.exists() or path.is_symlink():
                path.unlink()
        sync_directory(self.base)
        for entry in list(self.base.iterdir()):
            if entry.name in ('owner.json', 'owner.json.part'):
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        sync_directory(self.base)
        for name in ('owner.json', 'owner.json.part'):
            (self.base / name).unlink(missing_ok=True)
        os.rmdir(self.base)
        sync_directory(self.root)

    def owner(self):
        return ('builder SD transaction v2: %s %s\n' % (self.product.key, self.operation)).encode('ascii')

    def recognised(self, marker):
        """owner.json of this product, from this builder (v2, with a session) or an older one (v1)."""
        if marker.stat().st_size > 256:
            return False
        data = marker.read_bytes()
        key = re.escape(self.product.key.encode('ascii'))
        return (data == ('builder SD transaction v1: ' + self.product.key + '\n').encode('ascii')
                or re.fullmatch(b'builder SD transaction v2: ' + key + b' [0-9a-f]{32}\n', data) is not None)

    def residue(self):
        """A folder without owner.json is finished only at begin()'s start or cleanup's end: a partial marker and
        empty new/old folders, nothing else. Any file, journal or link there is unproven and kept (R175 F2)."""
        for entry in self.base.iterdir():
            if entry.is_symlink() or entry.name not in MARKERLESS:
                return False
            if entry.name == 'owner.json.part':
                if not entry.is_file() or not self.partial_marker(entry):
                    return False
            elif not entry.is_dir():
                return False
            else:
                for top, dirs, files in os.walk(entry):
                    if files or any(os.path.islink(os.path.join(top, name)) for name in dirs):
                        return False
        return True

    def partial_marker(self, path):
        """owner.json.part as begin() writes it, possibly cut short (a card can leave trailing zero bytes)."""
        if path.stat().st_size > 256:
            return False
        data = path.read_bytes().rstrip(b'\0')
        key = self.product.key.encode('ascii')
        for template in (b'builder SD transaction v1: ' + key + b'\n',
                         b'builder SD transaction v2: ' + key + b' ' + b'?' * 32 + b'\n'):
            if len(data) <= len(template) and all(byte == wanted or (wanted == ord('?') and byte in b'0123456789abcdef')
                                                  for byte, wanted in zip(data, template)):
                return True
        return False

    def contents_ours(self):
        """A marked folder holds only the marker, the journal and new/ and old/, as plain files and folders, and
        new/ and old/ hold staged files and backups of installer paths only: never a save or settings path, a link
        or anything but files and folders. Anything else is kept, with the folder (R175 F2, R175b F2)."""
        for entry in self.base.iterdir():
            kind = MARKED.get(entry.name)
            mode = entry.lstat().st_mode
            if kind is None or not (stat.S_ISDIR(mode) if kind == 'dir' else stat.S_ISREG(mode)):
                return False
            if kind == 'dir':
                for top, dirs, files in os.walk(entry):
                    rel = Path(top).relative_to(entry).parts
                    for name in dirs + files:
                        mode = os.lstat(os.path.join(top, name)).st_mode
                        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)) or any(
                                part.casefold() in NEVER_STAGED for part in rel + (name,)):
                            return False
        return True

    def check_owner(self):
        """This session still owns the update folder: nothing else recovered or replaced it since begin()."""
        marker = self.base / 'owner.json'
        if (not self.lease.held or self.base.is_symlink() or marker.is_symlink() or not marker.is_file()
                or marker.read_bytes() != self.owner()):
            raise OSError('The SD update folder changed during the copy')

    def begin(self):
        self._hold()
        with self._step():
            self._begin()

    def _begin(self):
        self._recover()
        self.base.mkdir()
        part = self.base / 'owner.json.part'
        with part.open('xb') as stream:
            stream.write(self.owner())
            stream.flush()
            os.fsync(stream.fileno())
        replace(part, self.base / 'owner.json')
        sync_directory(self.root)
        (self.new / '3ds').mkdir(parents=True)
        self.old.mkdir()

    def write_journal(self, entries, state):
        path = self.journal.with_suffix('.part')
        with path.open('w', encoding='utf-8', newline='\n') as stream:
            json.dump(dict(state=state, entries=entries), stream)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        replace(path, self.journal)

    def publish(self, removals=(), cancelled=lambda: False):
        with self._step():
            self._publish(removals, cancelled)

    def _publish(self, removals, cancelled):
        import texcache
        self.check_owner()
        names = {path.relative_to(self.new).as_posix() for path in self.new.rglob('*') if path.is_file()}
        install_record.check_retained_models(self.product, names,
            {name: texcache.checked_digest(self.target(self.new, name)) for name in names
             if name.rsplit('/', 1)[-1].casefold() == 'data.win'},
            previous=install_record.read(self.root, self.product),
            present=lambda name: self.target(self.root, name).is_file(),
            digest=lambda name: texcache.checked_digest(self.target(self.root, name)))
        removals = set(removals)
        # If no PC texture/receipt could be made for changed data, the old validity markers must go too.
        for name in names:
            if name.endswith('/data.win'):
                final, staged = self.target(self.root, name), self.target(self.new, name)
                if not final.is_file() or texcache.checked_digest(final) != texcache.checked_digest(staged):
                    for marker in ('complete', 'data-version.txt'):
                        old_marker = name[:-len('data.win')] + 'cache/' + marker
                        if old_marker not in names and self.target(self.root, old_marker).exists():
                            removals.add(old_marker)
        marker = install_record.relative_path(self.product)
        if marker in names:
            current = install_record.read(self.new, self.product)
            if current is None:
                raise ValueError('Invalid installer inventory path')
            # Build the final inventory before publication, while both the old
            # card set and the complete staged set are available. Do not copy
            # retained model binaries or sound packs into the transaction.
            install_record.write(self.new, self.product, [entry['path'] for entry in current['files']],
                cancelled, previous=install_record.read(self.root, self.product),
                present=lambda name: self.target(self.root, name).is_file(), removed=removals)
        entries = []
        for name in names | removals:
            final, staged = self.target(self.root, name), self.target(self.new, name)
            if name in names:
                sync_file(staged)
                sync_directory(staged.parent)
                if (not name.endswith(('/complete', '/data-version.txt', '/install.json'))
                        and final.is_file() and texcache.checked_digest(final) == texcache.checked_digest(staged)):
                    continue
            entries.append(dict(path=name, existed=final.exists(), new=name in names))
        def rank(entry):
            name = entry['path']
            if name == install_record.relative_path(self.product):
                return 5, name
            if name.endswith('/data-version.txt'):
                return 3, name
            if name.endswith('/complete'):
                return 2, name
            if '/cache/' in name or name.endswith('.dtx'):
                return 1, name
            if name.endswith(('.3dsx', '.cia')):
                return 4, name
            return 0, name
        entries.sort(key=rank)
        self.write_journal(entries, 'publishing')
        # Remove old validity markers before changing data or pages. They are restored on rollback.
        for entry in entries:
            if entry['existed'] and (entry['path'].endswith(('/complete', '/data-version.txt', '/install.json'))):
                backup = self.target(self.old, entry['path'])
                backup.parent.mkdir(parents=True, exist_ok=True)
                replace(self.target(self.root, entry['path']), backup)
        for entry in entries:
            if cancelled():
                raise InterruptedError('cancelled')
            final, backup = self.target(self.root, entry['path']), self.target(self.old, entry['path'])
            if entry['existed'] and not backup.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                replace(final, backup)
            if entry['new']:
                final.parent.mkdir(parents=True, exist_ok=True)
                replace(self.target(self.new, entry['path']), final)
        self.write_journal(entries, 'committed')
        self.recover()
