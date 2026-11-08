"""Prove that the autouse safety boundary engages without an opt-in from a GUI test."""
import os
from pathlib import Path
from unittest import mock

import deliver
import discover
import saves


def test_autouse_guard_redirects_default_saves_before_app_construction(builder_host_safety):
    for host in ('win32', 'darwin', 'linux'):
        for game in ('undertale', 'deltarune'):
            folder = Path(discover.Probes(platform=host).pc_save_dir(game))
            assert folder.is_relative_to(builder_host_safety)
            assert not saves.scan_saves(str(folder), game).files
    for name in ('LOCALAPPDATA', 'APPDATA', 'HOME', 'USERPROFILE', 'XDG_CONFIG_HOME'):
        assert Path(os.environ[name]).is_relative_to(builder_host_safety)


def test_autouse_guard_never_asks_the_os_for_drives_or_mounts():
    with mock.patch.object(deliver, '_drive_type', side_effect=AssertionError('real drive probe')), \
         mock.patch.object(deliver, 'mount_types', side_effect=AssertionError('real mount probe')):
        for host in ('win32', 'darwin', 'linux'):
            assert deliver.list_sd_cards(platform=host) == []


def test_autouse_guard_refuses_nonfixture_card_roots():
    import pytest
    with pytest.raises(AssertionError, match='temporary fixture roots'):
        deliver.list_sd_cards(platform='darwin', roots=[str(Path.cwd().anchor)])
