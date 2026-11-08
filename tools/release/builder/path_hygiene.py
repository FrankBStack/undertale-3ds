"""Host metadata and interrupted-copy files are never game or builder inputs."""
import os
from pathlib import Path


NAMES = frozenset(('.ds_store', 'thumbs.db', 'desktop.ini', '.spotlight-v100', '.fseventsd',
                   '.trashes', 'system volume information', '__macosx', '$recycle.bin', '.temporaryitems', 'icon\r'))
SUFFIXES = ('.tmp', '.part', '.bak')


def is_junk(path):
    """Match every component, case-insensitively, on Windows and Unix paths.

    AppleDouble companions are excluded by name even when empty. Never treat an
    arbitrary empty file as metadata: an empty required game file must still fail.
    Keep other dot names, which can be legitimate source inputs.
    """
    return any(part.startswith('._') or part in NAMES or part.endswith(SUFFIXES)
               for part in os.fspath(path).replace('\\', '/').casefold().split('/'))


def iter_paths(root):
    """Like rglob('*'), but prune metadata directories before visiting their contents."""
    for directory, dirs, files in os.walk(root):
        dirs[:] = sorted(name for name in dirs if not is_junk(name))
        for name in dirs + sorted(name for name in files if not is_junk(name)):
            yield Path(directory) / name
