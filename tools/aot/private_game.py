"""Private inputs for host runtime launches; a runtime may cache beside data.win.

Copy bundle files, never links, saves, settings or an existing cache. Callers supply
their run/work directory. The source game folder is only read.
"""
from contextlib import contextmanager
from pathlib import Path
import re
import shutil
import tempfile


def require_private_work(data_win, work):
    source = Path(data_win).resolve()
    folder = source.parent
    # game_change can reach another chapter relative to this folder.
    bundle = folder.parent if re.fullmatch(r'chapter[1-5]_windows', folder.name) else folder
    work = Path(work).resolve()
    if work == bundle or bundle in work.parents:
        raise ValueError('Runtime work must be outside the source game folder')
    return source, bundle, work


@contextmanager
def runtime_input(data_win, work):
    source, bundle, work = require_private_work(data_win, work)
    work.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='runtime-input-', dir=work) as temporary:
        target = Path(temporary) / bundle.name
        target.mkdir()
        # UNDERTALE and each DELTARUNE chapter read these bundle files. Do not
        # recursively copy the install: it can contain a player's saves.
        def copy_bundle(src, dst):
            for item in src.iterdir():
                if item.is_symlink():
                    continue
                if item.is_dir() and (re.fullmatch(r'chapter[1-5]_windows', item.name) or
                                      item.name.lower() in ('mus', 'music', 'audio', 'sound', 'sounds', 'snd', 'lang')):
                    child = dst / item.name
                    child.mkdir()
                    copy_bundle(item, child)
                elif item.is_file() and (item.name in ('data.win', 'game.ios') or
                        item.name.casefold() == 'credits.txt' or item.suffix.lower() == '.ogg' or
                        re.fullmatch(r'audiogroup[0-9]+\.dat', item.name) or
                        src.name.casefold() == 'lang' and re.fullmatch(r'lang_[a-zA-Z_]+\.json', item.name)):
                    shutil.copyfile(item, dst / item.name)
        copy_bundle(bundle, target)
        yield target / source.relative_to(bundle)
