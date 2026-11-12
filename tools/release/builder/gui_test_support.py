"""Test-only host isolation and Tk startup policy. Never use a player's saves or cards."""
from contextlib import contextmanager
import functools
import inspect
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


@contextmanager
def isolated_builder_host(folder):
    """Use before constructing an app, including in standalone page harnesses.

    Default save lookups use an empty fixture home; default card discovery is disabled.
    Explicit roots remain available for discovery tests, but must be temporary fixtures.
    This only changes the current test process, and restores its settings on exit.
    """
    import deliver
    root = Path(folder).resolve()
    for name in ('home', 'local', 'roaming', 'config'):
        (root / name).mkdir(parents=True, exist_ok=True)
    home = str(root / 'home')
    env = dict(HOME=home, USERPROFILE=home, LOCALAPPDATA=str(root / 'local'),
               APPDATA=str(root / 'roaming'), XDG_CONFIG_HOME=str(root / 'config'),
               HOMEDRIVE=os.path.splitdrive(home)[0], HOMEPATH=os.path.splitdrive(home)[1])
    original = deliver.list_sd_cards
    signature = inspect.signature(original)
    temporary = Path(tempfile.gettempdir()).resolve()

    @functools.wraps(original)
    def fixture_cards(*args, **kwargs):
        bound = signature.bind_partial(*args, **kwargs)
        roots = bound.arguments.get('roots')
        if roots is None:
            return []  # Do not even ask the OS which drives or mounts exist.
        roots = list(roots)
        # macOS reaches its temporary folder through a link (/var), so the spelled path may use either form.
        spelled = {temporary, Path(os.path.abspath(tempfile.gettempdir()))}
        if any(not any(Path(os.path.abspath(path)).is_relative_to(base) for base in spelled) or
               not Path(path).resolve().is_relative_to(temporary) for path in roots):
            raise AssertionError('Card discovery tests must supply temporary fixture roots.')
        bound.arguments['roots'] = roots
        return original(*bound.args, **bound.kwargs)

    with mock.patch.dict(os.environ, env), mock.patch.object(deliver, 'list_sd_cards', fixture_cards):
        yield root


def tk_unavailable(error):
    message='Tk display unavailable: '+str(error)
    if os.environ.get('REQUIRE_BUILDER_TK')=='1':
        raise AssertionError('Tk startup is required for this release gate. '+message) from error
    raise unittest.SkipTest(message) from error
