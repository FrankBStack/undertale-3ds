"""Installer payload inventory, published last. Never an instruction to delete files.

Paths are SD-root relative; no host paths, saves, settings or runtime-created files.
FTP carries the local payload's expected hashes: large remote files retain the
existing size-only verification policy. Runtime caches may change after boot.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

import products

MAX_BYTES = 8 * 1024 * 1024
PROTECTED = {'saves', 'settings.ini', 'log.txt', 'install.json', 'crash.txt', 'hang.txt'}


class ModelInputMismatch(ValueError):
    """Publishing shared data would strand a retained personal executable."""


def check_retained_models(product, names, data_hashes, *, previous, present, digest):
    """Check before publication; a retained executable keeps its original input binding.

    Inventory hashes describe the copy used for the previous install, even if its
    data.win has since been damaged. Legacy installs without a record use the
    actual destination data. Never delete an executable or weaken its runtime gate.
    Installed CIA titles cannot be inspected through the SD filesystem.
    """
    replacing = {name.casefold() for name in names}
    retained = []
    for model in products.TARGETS:
        stem = products.package_stem(product, model)
        for name in (product.sd_app_dir() + '/' + stem + '.3dsx', 'cia/' + stem + '.cia'):
            if name.casefold() not in replacing and present(name):
                retained.append(name)
    if not retained or not data_hashes:
        return
    record = validated(previous, product)
    old_hashes = {entry['path'].casefold(): entry['sha256'] for entry in record['files']} if record else {}
    for name, incoming in data_hashes.items():
        expected = old_hashes.get(name.casefold())
        from_record = expected is not None
        if expected is None and present(name):
            expected = digest(name)
        if expected != incoming:
            if from_record:
                reason = 'The other model on this card was made from a different copy of the game.'
            elif expected:
                reason = ('The data.win on this card does not match this copy. '
                          'It may be damaged or from a different copy of the game.')
            else:
                reason = "The builder couldn't check which copy of the game the other model on this card was made from."
            raise ModelInputMismatch(reason + '\nBuild both models from this copy, including any .cia you use, '
                'then try again. Or remove only these files:\n' + '\n'.join(retained) +
                '\nDo NOT delete the ' + product.sd_data_dir + ' folder: it also contains your saves and settings. '
                'Keep ' + product.sd_save_dir() + '/ and ' + product.sd_data_dir + '/settings.ini. '
                'If you installed a .cia with FBI, install the matching rebuilt .cia too, or uninstall that title '
                'before changing copies. Nothing has been replaced.')


def relative_path(product):
    return product.sd_data_dir + '/install.json'


def managed_path(product, name):
    if not isinstance(name, str) or any(c in name for c in '\\:\0\r\n'):
        return False
    path = PurePosixPath(name)
    if path.is_absolute() or path.as_posix() != name or '..' in path.parts:
        return False
    if any(part.casefold() in PROTECTED or part.casefold().endswith(('.part', '.builder-part'))
           for part in path.parts):
        return False
    if name.startswith(product.sd_data_dir + '/'):
        return True
    return len(path.parts) == 2 and path.parts[0] == 'cia' and path.suffix.casefold() == '.cia'


def target(root, name):
    root = Path(root).resolve()
    path = root.joinpath(*PurePosixPath(name).parts)
    if not path.resolve().is_relative_to(root):
        raise OSError('Installer destination outside card')
    # Neither a file nor a parent directory may redirect writes outside the card.
    current = path
    while current != root:
        if current.is_symlink():
            raise OSError('Symlink in installer destination')
        current = current.parent
    return path


def validated(record, product):
    """Accept only bounded, explicit installer ownership; never infer it from a folder."""
    try:
        if (record['schema'] != 1 or record['game'] != product.key
                or not isinstance(record['version'], str) or not record['version']
                or not isinstance(record['files'], list) or len(record['files']) > 50000):
            return None
        seen = set()
        for entry in record['files']:
            name = entry['path']
            if (not managed_path(product, name) or name.casefold() in seen
                    or type(entry['size']) is not int or entry['size'] < 0
                    or not isinstance(entry['sha256'], str)
                    or not re.fullmatch('[0-9a-f]{64}', entry['sha256'])):
                return None
            seen.add(name.casefold())
        return record
    except (OSError, ValueError, KeyError, TypeError):
        return None


def parse(data, product):
    """The same validation for a local record and bounded FTP read-back."""
    if len(data) > MAX_BYTES:
        return None
    try:
        return validated(json.loads(data), product)
    except (ValueError, TypeError, RecursionError):
        return None


def read(root, product):
    """An existing record for update detection; corrupt/foreign records are untrusted."""
    try:
        path = target(root, relative_path(product))
        with path.open('rb') as stream:
            return parse(stream.read(MAX_BYTES + 1), product)
    except OSError:
        return None


def invalidate(root, product):
    """A previous completion record must not describe a partial new installation."""
    target(root, relative_path(product)).unlink(missing_ok=True)


def write(root, product, names, cancelled=lambda: False, *, previous=None, present=None, removed=()):
    """Hash new payloads and retain known, still-present prior files' expected hashes.

    Retained files are not recopied or silently re-certified: their original
    expected hashes still expose corruption to the install-record checker.
    """
    entries = []
    seen = set()
    for name in sorted(set(names)):
        if cancelled():
            raise InterruptedError('cancelled')
        if not managed_path(product, name) or name.casefold() in seen:
            raise ValueError('Invalid installer inventory path')
        seen.add(name.casefold())
        path = target(root, name)
        before = path.stat()
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                if cancelled():
                    raise InterruptedError('cancelled')
                digest.update(block)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise OSError('Installer payload changed during inventory')
        entries.append(dict(path=name, size=after.st_size, sha256=digest.hexdigest()))
    prior = validated(previous, product)
    removed = {name.casefold() for name in removed}
    if prior:
        present = present or (lambda name: target(root, name).is_file())
        for entry in prior['files']:
            if cancelled():
                raise InterruptedError('cancelled')
            key = entry['path'].casefold()
            if key not in seen and key not in removed and present(entry['path']):
                entries.append(dict(path=entry['path'], size=entry['size'], sha256=entry['sha256']))
                seen.add(key)
    entries.sort(key=lambda entry: entry['path'])
    record = dict(schema=1, game=product.key, version=products.release_contract.read()['version'], files=entries)
    data = (json.dumps(record, indent=2) + '\n').encode('utf-8')
    if len(entries) > 50000 or len(data) > MAX_BYTES:
        raise ValueError('Installer inventory too large')
    final = target(root, relative_path(product))
    temporary = target(root, relative_path(product) + '.part')
    final.parent.mkdir(parents=True, exist_ok=True)
    try:
        with temporary.open('wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if cancelled():
            raise InterruptedError('cancelled')
        os.replace(temporary, final)
    finally:
        temporary.unlink(missing_ok=True)
    return record
