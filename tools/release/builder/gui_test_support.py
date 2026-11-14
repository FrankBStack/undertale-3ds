"""Test-only host isolation and Tk startup policy. Never use a player's saves or cards."""
from contextlib import contextmanager
import functools
import inspect
import os
from pathlib import Path
import sys
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


def show_without_desktop_input(test, window):
    """Deiconify a test window for real geometry, but keep the desktop's keyboard and mouse away from it.

    Release suites run on a desktop that someone may be using. App schedules _bring_to_front (lift, topmost,
    focus -force) for its first idle pass, and on Windows a newly shown window can take the foreground by itself.
    Then an Escape, Alt+F4, wheel or click meant for another window acted on the test's window inside its
    root.update() calls: integrate21's polish flake was a prompt closed that way (TclError 'bad window path name' on
    the next fit, 11-09 and 11-12), more likely under load because each step keeps the window up for longer. This
    makes _bring_to_front a no-op for the rest of the test and, on Windows, disables the window before it maps
    (wm attributes -disabled: EnableWindow FALSE on Tk's wrapper, so it gets no keyboard or mouse input and cannot be
    activated by a click). Tk's own focus still works: focus_set, focus_force, focus_get and FocusIn behave as
    before, so tests of Tk focus and traversal keep checking them. Synthetic event_generate input is unaffected.
    """
    import gui
    bring = mock.patch.object(gui, '_bring_to_front', lambda root: None)
    bring.start()
    test.addCleanup(bring.stop)
    if sys.platform == 'win32':
        window.attributes('-disabled', True)
    window.deiconify()
