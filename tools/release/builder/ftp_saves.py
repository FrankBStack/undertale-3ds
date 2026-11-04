"""Confirmed FTP save import; verified remote backups precede any replacement."""
from dataclasses import dataclass
from pathlib import Path
import ftplib
import hashlib
import tempfile
import time
import uuid

import ftp_delivery as network
import saves


class SavesChanged(network.TransferError):
    def __init__(self):
        super().__init__('The 3DS saves changed after they were checked. Nothing was replaced. Check the saves again, then retry.')


BACKUP_MISMATCH_MESSAGE = ("The 3DS didn't store a correct backup of its saves, so nothing was replaced and the 3DS "
                           "saves are as they were.\nIts SD card may be failing. Copy the card's saves folder to this "
                           "PC, then try again with another card.")


BACKUP_FOLDER_MESSAGE = "Couldn't make a new backup folder for the 3DS saves, so nothing was replaced. Try again."


class BackupMismatch(network.TransferError):
    def __init__(self):
        super().__init__(BACKUP_MISMATCH_MESSAGE)


class IncompleteImport(network.TransferError):
    """Replacing the live saves stopped partway. Says what each file holds now, where the backup is, how to finish
    and how to undo. The wizard hands it back to copy(resume=...) so its retry reuses the verified backup."""

    def __init__(self, cause, folder, backup, original, payloads, states):
        self.cause, self.folder, self.backup = cause, folder, backup
        self.original = original  # The 3DS saves as they were before this import (the backup's contents).
        self.incoming = {s.name.casefold(): data for s, data in payloads}
        self.states = states  # name -> 'new' | 'old' | 'waiting' | 'unsure' | 'removed'
        super().__init__(self.describe(wizard=False))

    def describe(self, *, wizard):
        def names(state):
            return ', '.join(n for n, s in self.states.items() if s == state)
        lines = ['Copying stopped while the 3DS saves were being replaced (%s).' % self.cause]
        for state, text in (('new', 'Now the PC save: %s.'), ('old', 'Still the old 3DS save: %s.'),
                            ('waiting', 'Not copied yet: %s.'),
                            ('unsure', 'May be missing: %s.'), ('removed', 'Removed (kept in the backup): %s.')):
            if names(state):
                lines.append(text % names(state))
        if self.backup:
            lines.append('Your previous 3DS saves are backed up in %s.' % self.backup)
        else:
            lines.append('There were no 3DS saves before this import.')
        # Saves this import brings that the card didn't have: an undo must delete them too (R171 F1).
        before = {name.casefold() for name in self.original.files}
        added = [n for n, s in self.states.items() if n.casefold() not in before and s in ('new', 'unsure')]
        if wizard:
            lines.append('Click Next to finish copying.')
        else:
            lines.append('To finish, run the same command again with --overwrite-saves. It backs up the saves as they '
                         'are now into a new folder and keeps this one.')
        if self.backup:
            lines.append('To put the old saves back instead, copy every file from %s into %s, replacing what is '
                         'there.' % (self.backup, self.folder))
            if added:
                lines.append('Then delete %s from %s.' % (', '.join(added), self.folder))
        elif added:
            lines.append('To go back to no saves instead, delete %s from %s.' % (', '.join(added), self.folder))
        return '\n'.join(lines)


def error_text(exc, *, connecting=False):
    """The wizard has Back/Next; the CLI keeps the approved retry instruction."""
    if isinstance(exc, SavesChanged):
        return 'The 3DS saves changed after they were checked. Nothing was replaced. Click Back, then Next, to check them again.'
    if isinstance(exc, IncompleteImport):
        return exc.describe(wizard=True)
    return network.error_text(exc, connecting=connecting)


@dataclass
class Snapshot:
    files: dict
    player_summary: str


def read_folder(ftp, folder, *, cancelled=lambda: False):
    """{name: bytes} of the ordinary files in one card folder; {} if it doesn't exist."""
    try:
        rows = list(ftp.mlsd(folder, facts=['type', 'size']))
    except ftplib.error_perm as exc:
        if not str(exc).startswith('550'):
            raise
        return {}
    files = {}
    for name, facts in rows:
        # Match SD import: back up existing ordinary save-folder files, including unknown files.
        if facts.get('type') != 'file' or name.startswith('.') or name.endswith(('.tmp', '.part', '.save-part', '.builder-part')):
            continue
        if '/' in name or '\\' in name or name in ('..', '.'):
            raise network.TransferError('A file in the 3DS saves folder has an unusual name. Copy the saves by SD card instead.')
        path = folder + '/' + name
        size = network.size(ftp, path)
        if size is None or size > saves.MAX_SAVE_BYTES:
            raise network.TransferError('A file in the 3DS saves folder is too large to back up over Wi-Fi. Nothing was replaced. Copy the saves by SD card instead.')
        buffer = bytearray()
        def take(block):
            network.check_cancel(cancelled)
            buffer.extend(block)
            if len(buffer) > saves.MAX_SAVE_BYTES:
                raise SavesChanged()
        ftp.retrbinary('RETR ' + path, take)
        if len(buffer) != size or network.size(ftp, path) != size:
            raise SavesChanged()
        files[name] = bytes(buffer)
    return files


def snapshot(ftp, product, *, cancelled=lambda: False):
    files = read_folder(ftp, network.remote_path(product.sd_save_dir()), cancelled=cancelled)
    if not files:
        return Snapshot({}, '')
    with tempfile.TemporaryDirectory(prefix='builder-saves-') as temporary:
        for name, data in files.items():
            (Path(temporary)/name).write_bytes(data)
        summary = saves.scan_saves(temporary, product.key).player_summary
    return Snapshot(files, summary)


def inspect(value, product, *, factory=network.ConsoleFTP, cancelled=lambda: False):
    ftp = network.connect(value, factory=factory)
    try:
        with network.friendly_errors():
            return snapshot(ftp, product, cancelled=cancelled)
    finally:
        ftp.close()


def check_published(ftp, product, payloads):
    """Read the saves folder again: every PC save must be there with the bytes that were checked, under any
    spelling of its name. Returns the names that aren't."""
    live = {name.casefold(): data for name, data in snapshot(ftp, product).files.items()}
    return [s.name for s, data in payloads if live.get(s.name.casefold()) != data]


def same_files(a, b):
    """Same files and bytes, matching names the way the card's FAT does (AUD-02): FILE0 and file0 are one file. Two
    names in one folder that differ only in capitals can't both be one FAT file, so they never match."""
    folded_a = {name.casefold(): data for name, data in a.items()}
    folded_b = {name.casefold(): data for name, data in b.items()}
    return len(folded_a) == len(a) and len(folded_b) == len(b) and folded_a == folded_b


def check_backup(ftp, backup, original, *, cancelled=lambda: False):
    """Read the published backup folder back: it must hold exactly the original saves, byte for byte, before any
    live save is staged or replaced (R181 F1). A transfer checks each upload before its rename, not after."""
    try:
        held = read_folder(ftp, backup, cancelled=cancelled)
    except network.Cancelled:
        raise
    except (OSError, EOFError, ftplib.Error) as exc:
        lost = network.delivery_error(exc)
        if lost is not exc:
            # The connection dropped (or the card is full): that is what the player is told, not a failing card.
            # Nothing live changed, and a later import makes and checks a new backup.
            raise lost from exc
        held = None  # Unreadable, refused, or grown past what a save can be: not a backup to trust.
    if held is not None and same_files(held, original):
        return
    for name in original:  # Nobody should restore from it. The live saves are untouched.
        try:
            network.delete_if_present(ftp, backup + '/' + name)
        except (OSError, EOFError, ftplib.Error):
            pass
    raise BackupMismatch()


# What the 3DS ftpd (v2.3.1) answers when a listed path isn't there: 550 and strerror(ENOENT). Its other 550s
# (an unreadable card, for one) can come from a folder that exists, so they never count as absence (R190c).
MISSING_PATH_REPLY = '550 no such file or directory'
LISTED_TYPES = ('file', 'dir', 'cdir', 'pdir')


def well_formed(entry, facts):
    """An MLSD row ftplib parsed from what ftpd writes: a name and the type fact asked for. ftplib turns a broken
    row into name '' with junk facts instead of raising, and a broken listing proves nothing."""
    kind = str(facts.get('type', '')).casefold()
    return bool(entry) and (kind in LISTED_TYPES or kind.startswith('os.'))


def name_is_free(ftp, folder, path):
    """True only when `path`, a child of `folder`, is shown not to exist: the folder's listing is well formed and
    doesn't name it under FAT rules (any capitals), and listing `path` itself gets ftpd's missing-path 550. Any doubt
    is False (R190b, R190c). A dropped connection still raises, so the player is told about the connection."""
    name = path.rsplit('/', 1)[1].casefold()
    try:
        for entry, facts in ftp.mlsd(folder, facts=['type']):
            if not well_formed(entry, facts) or entry.casefold() == name:
                return False
        try:
            list(ftp.mlsd(path, facts=['type']))
        except ftplib.error_perm as exc:
            return ' '.join(str(exc).split()).casefold() == MISSING_PATH_REPLY
        return False
    except (ftplib.error_perm, ftplib.error_temp, ftplib.error_reply, ftplib.error_proto):
        return False


def resumable(ftp, resume, folder, current, payloads, *, cancelled=lambda: False):
    """True when the card holds what a stopped import of these same PC bytes can leave, and its backup still holds
    the original saves byte for byte: then a retry finishes it without a second backup."""
    if not isinstance(resume, IncompleteImport) or resume.folder != folder:
        return False
    incoming = {s.name.casefold(): data for s, data in payloads}
    if incoming != resume.incoming:
        return False  # Other PC saves: an ordinary import with its own backup.
    original = {name.casefold(): data for name, data in resume.original.files.items()}
    for name, data in current.items():
        key = name.casefold()
        if data != original.get(key) and data != incoming.get(key):
            return False
    if resume.original.files:
        if not resume.backup or not same_files(read_folder(ftp, resume.backup, cancelled=cancelled),
                                               resume.original.files):
            return False
    return True


def copy(value, product, scan, expected, *, overwrite=False, factory=network.ConsoleFTP,
         cancelled=lambda: False, progress=lambda event: None, resume=None):
    if scan.has_corrupt or not scan.valid_files:
        raise network.TransferError('No readable PC saves to copy, so nothing was copied. Choose another folder or skip.')
    clash = saves.case_clashes(scan.valid_files)
    if clash:
        raise network.TransferError(saves.CASE_CLASH_MESSAGE % ', '.join(clash))
    try:
        # The bytes the preview checked. They are what is sent, even if the PC file changes during the import.
        payloads = saves.validated_payloads(scan, product.key)
    except saves.DeliverError as exc:
        raise network.TransferError(str(exc)) from None
    if expected.files and not overwrite:
        raise network.TransferError('Existing 3DS saves were found. Nothing was copied. Add --overwrite-saves to back them up and replace them.')
    ftp = network.connect(value, factory=factory)
    folder = network.remote_path(product.sd_save_dir())
    transfer = network.Transfer(ftp, cancelled=cancelled, progress=progress, install=False)
    try:
        current = snapshot(ftp, product, cancelled=cancelled)
        from deliver import CopyItem
        with tempfile.TemporaryDirectory(prefix='builder-save-copy-') as temporary:
            if resume is not None and resumable(ftp, resume, folder, current.files, payloads, cancelled=cancelled):
                original, backup = resume.original, resume.backup  # Verified just now; no second backup.
            else:
                if current.files != expected.files:
                    raise SavesChanged()
                original = expected
                backup = folder + '/backup-' + time.strftime('%Y%m%d-%H%M%S') + '-' + uuid.uuid4().hex[:8]
                if expected.files:
                    # The folder must be new: check_backup deletes from it on a mismatch, so it must never be an
                    # older backup that happens to have the same name (R190 LOW 3). Some ftpd versions (v2.3.1)
                    # answer MKD with 250 for a folder that already exists, so prove the name is free first.
                    if not name_is_free(ftp, folder, backup):
                        raise network.TransferError(BACKUP_FOLDER_MESSAGE)
                    try:
                        ftp.mkd(backup)
                    except ftplib.error_perm as exc:
                        if not str(exc).startswith('550'):
                            raise
                        raise network.TransferError(BACKUP_FOLDER_MESSAGE) from None
                    transfer.folders.add(backup)
                items = []
                for name, data in expected.files.items():
                    source = Path(temporary)/name
                    source.write_bytes(data)
                    items.append(CopyItem(str(source), backup+'/'+name, len(data)))
                transfer.send(items)
                if expected.files:
                    check_backup(ftp, backup, expected.files, cancelled=cancelled)
                else:
                    backup = None
            baseline = current.files  # What is being replaced, as checked above.
            staged = []
            outgoing = Path(tempfile.mkdtemp(prefix='pc-', dir=temporary))  # Never one of the card's names.
            for source, data in payloads:
                network.check_cancel(cancelled)
                path = folder+'/'+source.name
                part = path+'.save-part'
                local = outgoing/source.name
                local.write_bytes(data)
                transfer.total += 2*len(data)
                transfer.upload(CopyItem(str(local), part, len(data)))  # Read back and hash-checked.
                staged.append((path, part, source.name))
            # Ensure the save we confirmed is still the save being replaced.
            if snapshot(ftp, product, cancelled=cancelled).files != baseline:
                raise SavesChanged()
            network.check_cancel(cancelled)
            # From here on live files change. Track each one, so any failure says exactly what the card holds.
            live = {name.casefold(): name for name in baseline}
            incoming = {s.name.casefold() for s, _ in payloads}
            # What each file holds now, by its bytes: a retry's card can already hold PC saves (R171 F2).
            now = {name.casefold(): data for name, data in baseline.items()}
            states = {}
            for source, data in payloads:
                held = now.get(source.name.casefold())
                states[source.name] = 'waiting' if held is None else 'new' if held == data else 'old'
            states.update((name, 'old') for name in baseline if name.casefold() not in incoming)
            states.update((name, 'removed') for name in original.files
                          if name.casefold() not in incoming and name.casefold() not in now)
            try:
                for path, part, name in staged:
                    # The 3DS card is FAT: names match whatever their capitals, so FILE0 on the card and file0 from
                    # the PC are one file. Replace the card's own spelling, and never delete a name just written.
                    states[name] = 'unsure'
                    old = live.get(name.casefold())
                    network.delete_if_present(ftp, folder+'/'+old if old else path)
                    ftp.rename(part, path)
                    states[name] = 'new'
                for name in baseline:
                    if name.casefold() not in incoming:
                        states[name] = 'unsure'
                        ftp.delete(folder+'/'+name)
                        states[name] = 'removed'
                wrong = check_published(ftp, product, payloads)  # Publishing is done: Cancel no longer applies.
                if wrong:
                    states.update((name, 'unsure') for name in wrong)
                    raise network.TransferError("the saves on the 3DS don't match the PC saves after copying")
            except (OSError, EOFError, ftplib.Error) as exc:
                if isinstance(exc, ftplib.Error) and str(exc)[:3] in ('452', '552'):
                    cause = 'the 3DS SD card is full'
                elif network.delivery_error(exc) is not exc:
                    cause = 'the connection to the 3DS was lost'
                else:
                    cause = str(exc) or type(exc).__name__
                raise IncompleteImport(cause, folder, backup, original, payloads, states) from exc
            return saves.SaveCopyResult(len(staged), sum(len(data) for _, data in payloads), backup,
                                        [s.name for s in scan.valid_files], len(original.files))
    except (OSError, EOFError, ftplib.Error) as exc:
        translated = network.delivery_error(exc)
        if translated is exc:
            raise
        raise translated from exc
    finally:
        ftp.close()
