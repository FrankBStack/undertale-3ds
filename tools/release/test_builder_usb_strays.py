"""USB clutter is never game input. Synthetic Windows/Mac trees and loopback FTP only."""
import contextlib
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE / 'builder')]
import deliver
import discover
import gui
import products
from test_builder import write
from fake_ftpd import FakeFtpd
from gui_test_support import isolated_builder_host

WIN = b"fake Windows data.win" * 9
MAC = b"fake macOS game.ios" * 11
ALLOW = [("undertale", "root", len(WIN), hashlib.sha256(WIN).hexdigest(), "steam", "test 1.0")]
MAC_ALLOW = [("undertale", "root", len(MAC), hashlib.sha256(MAC).hexdigest(), "steam", "test 1.0 mac")]
RES = ("UNDERTALE.app", "Contents", "Resources")
# Exercise the depot spelling case difference with invented music names.
MUSIC = {"fixture_tune.ogg": b"ogg one" * 3, "fixture_other.ogg": b"ogg two" * 5}
WIN_SPELLING = {"fixture_tune.ogg": "fixture_Tune.ogg", "fixture_other.ogg": "fixture_other.ogg"}


def record(store, depot, names):
    files = [dict(name=n, size=len(MUSIC[n.lower()]), sha256=hashlib.sha256(MUSIC[n.lower()]).hexdigest())
             for n in names]
    return dict(store=store, depot=depot, data_sha256="0" * 64, count=len(files), files=files,
                credits=dict(size=len(b'names\n'), sha256=hashlib.sha256(b'names\n').hexdigest()))


MANIFEST = {"schema": 2, "game": "undertale", "releases": {"steam": {
    "windows": {"test 1.0": record("steam", "windows", sorted(WIN_SPELLING.values()))},
    "macos": {"test 1.0 mac": record("steam", "macos", sorted(MUSIC))}}}}


def mac_folder(folder, data=MAC, music=True):
    res = os.path.join(folder, *RES)
    write(os.path.join(res, "game.ios"), data)
    write(os.path.join(res, "credits.txt"), "names\n")
    write(os.path.join(res, "options.ini"), "[x]\n")
    write(os.path.join(folder, "UNDERTALE.app", "Contents", "MacOS", "Undertale"), b"\xcf\xfa\xed\xfe")
    if music:
        for name, blob in MUSIC.items():
            write(os.path.join(res, name), blob)
    return res


DIRS = ('.Spotlight-V100', '.Trashes', '.fseventsd', '__MACOSX', '.TemporaryItems',
        '$RECYCLE.BIN', 'System Volume Information', 'fixture_directory.ogg')
FILES = ('.DS_Store', 'Thumbs.db', 'desktop.ini', 'transfer.tmp', 'transfer.part',
         'fixture_other copy.ogg', 'custom.ogg', 'empty', 'empty.ogg')


@contextlib.contextmanager
def no_stray_opens(game, resources, data_name, music_names):
    active = [True]
    root = os.path.normcase(os.path.abspath(game)) + os.sep
    allowed = {os.path.normcase(os.path.abspath(resources / name))
               for name in [data_name, 'credits.txt', *music_names]}
    def guard(event, args):
        if active[0] and event == 'open' and isinstance(args[0], (str, bytes, os.PathLike)):
            path = os.path.normcase(os.path.abspath(os.fsdecode(args[0])))
            if path.startswith(root) and path not in allowed:
                raise AssertionError('opened a stray game-folder file')
    sys.addaudithook(guard)
    try:
        yield
    finally:
        active[0] = False


def clutter(folder, own_names):
    folder = Path(folder)
    for name in DIRS:
        write(str(folder / name / 'stray.ogg'), b'not music')
    for name in FILES:
        write(str(folder / name), b'' if name.startswith('empty') else b'not music')
    for name in own_names:
        write(str(folder / ('._' + name)), b'AppleDouble companion')
    try:
        (folder / 'dangling.ogg').symlink_to(folder / 'missing link target')
    except OSError:
        pass  # The tests also inject its directory entry on hosts without symlink privilege.


class IsolatedCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        host = isolated_builder_host(self.root / 'empty-host')
        host.__enter__()
        self.addCleanup(host.__exit__, None, None, None)


class UsbStrays(IsolatedCase):
    def test_windows_and_every_bundle_pick_ignore_all_clutter(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(products, 'read_music_manifest', return_value=MANIFEST):
            base = Path(tmp)
            for platform in ('windows', 'macos'):
                game = base / platform
                if platform == 'macos':
                    resources = Path(mac_folder(str(game)))
                    locations = [game, game / 'UNDERTALE.app/Contents', resources]
                    picks = [game, game / 'UNDERTALE.app', game / 'UNDERTALE.app/Contents', resources]
                else:
                    resources = game
                    write(str(game / 'data.win'), WIN)
                    write(str(game / 'credits.txt'), 'names\n')
                    for name, blob in MUSIC.items():
                        write(str(game / WIN_SPELLING[name]), blob)
                    locations, picks = [game], [game]
                before = gui.source_manifest(str(game), products.PRODUCTS['undertale'])
                for folder in locations:
                    clutter(folder, [p.name for p in folder.iterdir()])
                listing = os.listdir

                def entries(folder):
                    names = listing(folder)
                    if Path(folder) in locations and 'dangling.ogg' not in names:
                        names.append('dangling.ogg')
                    return names

                music_names = list(MUSIC) if platform == 'macos' else list(WIN_SPELLING.values())
                with no_stray_opens(game, resources, 'game.ios' if platform == 'macos' else 'data.win', music_names), \
                        mock.patch.object(products.os, 'listdir', side_effect=entries):
                    for pick in picks:
                        with self.subTest(platform=platform, pick=str(pick)):
                            verdict = discover.verify_copy('undertale', str(pick),
                                discover.Probes(steam_roots=[], gog_dirs=[], platform='darwin'), ALLOW, MAC_ALLOW)
                            self.assertTrue(verdict.accepted, verdict.message)
                            log = []
                            self.assertTrue(products.music_check(products.PRODUCTS['undertale'], str(resources),
                                verdict.result.version, platform=verdict.result.layout, log=log.append)[0])
                            self.assertEqual(log, ["Skipped extra music files. Only the game's original music is used."])
                            self.assertEqual(gui.source_manifest(verdict.result.folder, products.PRODUCTS['undertale']), before)
                            sd = base / ('card-' + platform + '-' + str(len(str(pick))))
                            (sd / '3ds').mkdir(parents=True)
                            items = deliver.plan_sd_copy(str(sd), products.PRODUCTS['undertale'], [], verdict.result.folder)
                            self.assertEqual(sorted(Path(item.dst).name for item in items),
                                ['credits.txt', 'data.win', 'fixture_Tune.ogg', 'fixture_other.ogg'])
                            deliver.copy_items(str(sd), items)
                            copied = [p.relative_to(sd / '3ds/undertale-3ds').as_posix()
                                      for p in (sd / '3ds/undertale-3ds').rglob('*') if p.is_file()]
                            self.assertEqual(sorted(copied), ['credits.txt', 'data.win', 'fixture_Tune.ogg', 'fixture_other.ogg'])
                for replacement in ('missing', 'empty', 'changed', 'directory'):
                    path = resources / 'fixture_other.ogg'
                    path.unlink()
                    if replacement == 'empty':
                        path.touch()
                    elif replacement == 'changed':
                        path.write_bytes(b'x' + MUSIC['fixture_other.ogg'][1:])
                    elif replacement == 'directory':
                        path.mkdir()
                    verdict = discover.verify_copy('undertale', str(game),
                        discover.Probes(steam_roots=[], gog_dirs=[]), ALLOW, MAC_ALLOW)
                    self.assertFalse(verdict.accepted, (platform, replacement))
                    self.assertIn('fixture_other.ogg', verdict.message)
                    if path.is_dir():
                        path.rmdir()
                    elif path.exists():
                        path.unlink()
                    path.write_bytes(MUSIC['fixture_other.ogg'])

    def test_deltarune_walk_prunes_host_junk_without_changing_game_selection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for folder in (root, root / 'mus', root / 'chapter1_windows'):
                folder.mkdir(exist_ok=True)
                write(str(folder / ('music.ogg' if folder.name == 'mus' else 'data.win')), b'game fixture')
                clutter(folder, [p.name for p in folder.iterdir() if p.is_file()])
                # DELTARUNE retains its existing walk, not UNDERTALE's music manifest policy.
                for name in ('custom.ogg', 'fixture_other copy.ogg'):
                    (folder / name).unlink()
            walk = os.walk
            def with_broken_link(*args, **kwargs):
                for folder, dirs, names in walk(*args, **kwargs):
                    yield folder, dirs, names if 'dangling.ogg' in names else names + ['dangling.ogg']
            with mock.patch.object(products.os, 'walk', side_effect=with_broken_link):
                names = [rel for _, rel, _ in products.sd_files(products.PRODUCTS['deltarune'], str(root), ['chapter1_windows'])]
            self.assertEqual(sorted(names), ['chapter1_windows/data.win', 'data.win', 'mus/music.ogg'])


class UsbFTP(IsolatedCase):
    def setUp(self):
        super().setUp()
        self.card = self.root / 'card'
        (self.card / '3ds').mkdir(parents=True)
        (self.card / 'Nintendo 3DS').mkdir()
        self.server = FakeFtpd(self.card)
        self.addCleanup(self.server.close)
        self.address = '127.0.0.1:%d' % self.server.port

    def test_ftp_send_contains_only_manifest_game_files_and_generated_metadata(self):
        import ftp_delivery
        game = self.root / 'game'
        mac_folder(str(game))
        for folder in (game, game / 'UNDERTALE.app/Contents', game / 'UNDERTALE.app/Contents/Resources'):
            clutter(folder, [p.name for p in folder.iterdir()])
        save = deliver.save_files
        def save_without_texture_tools(*args, **kwargs):
            return save(*args, **kwargs, textures=False, data_version=False)
        logs = []
        with mock.patch.object(products, 'read_music_manifest', return_value=MANIFEST), \
                mock.patch.object(deliver, 'save_files', side_effect=save_without_texture_tools):
            ftp_delivery.send_product(self.address, products.PRODUCTS['undertale'], [], str(game),
                                      str(self.root / 'work'), log=logs.append)
        names = sorted(p.relative_to(self.card).as_posix() for p in self.card.rglob('*') if p.is_file())
        self.assertEqual(names, ['3ds/undertale-3ds/credits.txt', '3ds/undertale-3ds/data.win',
                                '3ds/undertale-3ds/fixture_Tune.ogg', '3ds/undertale-3ds/fixture_other.ogg',
                                '3ds/undertale-3ds/install.json'])
        self.assertIn("Skipped extra music files. Only the game's original music is used.", logs)


if __name__ == '__main__':
    unittest.main()
