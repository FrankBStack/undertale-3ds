#!/usr/bin/env python3
"""Tests for verify_game.py with fake Steam and GOG trees (no game data needed): py -3 -I tools/release/test_verify_game.py"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import verify_game as vg  # noqa: E402

OWNER = "76561190000000001"
OTHER = "76561190000000002"


def blob(tag):
    return ("fake data.win " + tag).encode() * 3


def row(game, part, data, store="steam", label="test 1.0"):
    return (game, part, len(data), hashlib.sha256(data).hexdigest(), store, label)


UT = blob("ut")
DR = {p: blob("dr " + p) for p in vg.GAMES["deltarune"].parts}
ALLOW = [row("undertale", "root", UT)] + [row("deltarune", p, d) for p, d in DR.items()]


def write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(data, bytes) else "w", **({} if isinstance(data, bytes) else {"encoding": "utf-8"})) as f:
        f.write(data)


class Tree:
    """A Steam client at <tmp>/Steam with a second library at <tmp>/Lib."""

    def __init__(self, tmp, old_format=False):
        self.tmp = tmp
        self.root = os.path.join(tmp, "Steam")
        self.lib = os.path.join(tmp, "Lib")
        os.makedirs(os.path.join(self.lib, "steamapps"), exist_ok=True)
        lib_vdf = self.lib.replace("\\", "\\\\")
        if old_format:
            vdf = '"LibraryFolders"\n{\n\t"TimeNextStatsReport"\t"1"\n\t"1"\t"%s"\n}\n' % lib_vdf
        else:
            vdf = ('"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n\t"1"\n\t{\n\t\t"path"\t\t"%s"\n'
                   '\t\t"apps"\n\t\t{\n\t\t\t"391540"\t\t"1"\n\t\t}\n\t}\n}\n'
                   % (self.root.replace("\\", "\\\\"), lib_vdf))
        write(os.path.join(self.root, "steamapps", "libraryfolders.vdf"), vdf)
        self.users([OWNER])

    def users(self, ids):
        body = "".join('\t"%s"\n\t{\n\t\t"AccountName"\t\t"someone"\n\t\t"MostRecent"\t\t"1"\n\t}\n' % i for i in ids)
        write(os.path.join(self.root, "config", "loginusers.vdf"), '"users"\n{\n%s}\n' % body)

    def install(self, appid, installdir, files, owner=OWNER, flags=4, lib=None):
        lib = lib or self.lib
        write(os.path.join(lib, "steamapps", "appmanifest_%s.acf" % appid),
              '"AppState"\n{\n\t"appid"\t\t"%s"\n\t"StateFlags"\t\t"%d"\n\t"installdir"\t\t"%s"\n'
              '\t"buildid"\t\t"1"\n\t"LastOwner"\t\t"%s"\n}\n' % (appid, flags, installdir, owner))
        folder = os.path.join(lib, "steamapps", "common", installdir)
        for rel, data in files.items():
            write(os.path.join(folder, rel), data)
        return folder


def dr_files(parts=None, override=None):
    out = {}
    for p in parts or vg.GAMES["deltarune"].parts:
        out["data.win" if p == "root" else p + "/data.win"] = (override or {}).get(p, DR[p])
    return out


class NativeLinuxTests(unittest.TestCase):
    MESSAGE = ("{game}'s native Linux files are not supported. Use its Windows version from Steam or GOG. "
               "For Steam, choose Proton in Properties > Compatibility, let the download finish, "
               "then select the game folder again.")

    def verify(self, folder, **kwargs):
        return vg.verify('undertale', game_dir=str(folder), steam_roots=[], gog_dirs=[],
                         allow_list=ALLOW, macos_allow_list=MAC_ALLOW, **kwargs)

    def test_native_layouts_refused_with_exact_approved_next_step_on_all_hosts(self):
        for relative in ('game.unx', 'assets/game.unx'):
            for platform in ('linux', 'win32', 'darwin'):
                with self.subTest(relative=relative, platform=platform), tempfile.TemporaryDirectory() as tmp:
                    # Even whitelisted Windows bytes under a native name never qualify.
                    write(os.path.join(tmp, relative), UT)
                    with mock.patch.object(vg, 'check_versions', side_effect=AssertionError('no supported layout')):
                        result = self.verify(tmp, platform=platform)
                    self.assertEqual(result.status, vg.MISSING_FILES)
                    self.assertEqual(result.message, self.MESSAGE.format(game='UNDERTALE'))
                    self.assertEqual(result.accepted_parts, [])
                    self.assertIsNone(result.layout)

    def test_steam_auto_discovery_also_reports_the_native_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            tree.install('391540', 'Undertale', {'assets/game.unx': UT})
            result = vg.verify('undertale', steam_roots=[tree.root], gog_dirs=[],
                               allow_list=ALLOW, platform='linux')
            self.assertEqual(result.status, vg.MISSING_FILES)
            self.assertEqual(result.message, self.MESSAGE.format(game='UNDERTALE'))

    def test_generic_missing_data_message_still_handles_empty_folders_and_directories(self):
        for native_directory in (False, True):
            with self.subTest(native_directory=native_directory), tempfile.TemporaryDirectory() as tmp:
                if native_directory:
                    os.mkdir(os.path.join(tmp, 'game.unx'))
                result = self.verify(tmp, platform='linux')
                self.assertEqual(result.status, vg.MISSING_FILES)
                self.assertIn('has no data.win', result.message)
                self.assertNotIn('Proton', result.message)

    def test_supported_windows_layout_keeps_hash_checks(self):
        for owner, data, expected in [(OWNER, UT, vg.OK), (OTHER, UT, vg.OK),
                                      (OWNER, bytes(len(UT)), vg.UNKNOWN_VERSION)]:
            with self.subTest(owner=owner, expected=expected), tempfile.TemporaryDirectory() as tmp:
                tree = Tree(tmp)
                folder = tree.install('391540', 'Undertale', {'data.win': data,
                    'game.unx': UT, 'assets/game.unx': UT}, owner=owner)
                result = vg.verify('undertale', game_dir=folder, steam_roots=[tree.root],
                                   gog_dirs=[], allow_list=ALLOW, platform='linux')
                self.assertEqual((result.status, result.layout), (expected, 'windows'))
                self.assertNotIn('Proton', result.message)
                if expected != vg.OK:
                    self.assertEqual(result.accepted_parts, [])

    def test_supported_mac_layout_and_unrecorded_windows_copy_keep_their_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            folder = tree.install('391540', 'Undertale', {BUNDLE + 'game.ios': MAC, 'game.unx': UT})
            result = vg.verify('undertale', game_dir=folder, steam_roots=[tree.root], gog_dirs=[],
                               allow_list=ALLOW, macos_allow_list=MAC_ALLOW, platform='darwin')
            self.assertEqual((result.status, result.layout), (vg.OK, 'macos'))
            # Native data alongside a known Windows copy does not block acceptance.
            copy = Path(tmp) / 'unrecorded'
            write(str(copy / 'data.win'), UT)
            write(str(copy / 'game.unx'), UT)
            result = self.verify(copy, platform='linux')
            self.assertEqual((result.status, result.layout), (vg.OK, 'windows'))
            self.assertEqual(result.accepted_parts, ['root'])


class VdfTests(unittest.TestCase):
    def test_nested_escapes_comments(self):
        d = vg.parse_vdf('// c\n"a"\n{\n "b" "x\\"y\\\\z" // tail\n "C" { "d" "1" }\n bare val\n}\n')
        self.assertEqual(vg.vget(d, "A", "b"), 'x"y\\z')
        self.assertEqual(vg.vget(d, "a", "c", "D"), "1")
        self.assertEqual(vg.vget(d, "a", "bare"), "val")

    def test_malformed(self):
        for bad in ('"a" {', '"a" "b" }', '"a"', '"a" "unterminated'):
            with self.assertRaises(ValueError):
                vg.parse_vdf(bad)


class DigestTests(unittest.TestCase):
    def test_same_size_in_place_rewrite_with_restored_mtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.win"
            path.write_bytes(UT)
            stamp = path.stat()
            self.assertEqual(vg.check_versions(vg.GAMES["undertale"], tmp, ALLOW)["root"][0], "ok")
            path.write_bytes(UT[:-1] + bytes([UT[-1] ^ 1]))
            os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            self.assertEqual(path.stat().st_size, stamp.st_size)
            self.assertEqual(path.stat().st_mtime_ns, stamp.st_mtime_ns)
            self.assertEqual(path.stat().st_ino, stamp.st_ino)
            self.assertEqual(vg.check_versions(vg.GAMES["undertale"], tmp, ALLOW)["root"][0], "unknown")

    def test_same_size_replacement_with_restored_mtime_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.win"
            path.write_bytes(UT)
            stamp = path.stat()
            self.assertEqual(vg.data_digest(path), hashlib.sha256(UT).hexdigest())
            replacement = Path(tmp) / "replacement"
            altered = UT[:-1] + bytes([UT[-1] ^ 1])
            replacement.write_bytes(altered)
            os.utime(replacement, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
            os.replace(replacement, path)
            self.assertEqual(path.stat().st_size, stamp.st_size)
            self.assertEqual(path.stat().st_mtime_ns, stamp.st_mtime_ns)
            self.assertEqual(vg.data_digest(path), hashlib.sha256(altered).hexdigest())

    def test_same_metadata_never_substitutes_for_reading_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.win"
            path.write_bytes(UT)
            real = vg.sha256_file
            with mock.patch.object(vg, "sha256_file", wraps=real) as read:
                self.assertEqual(vg.data_digest(path), vg.data_digest(path))
            self.assertEqual(read.call_count, 2)

    def test_failed_recheck_does_not_reuse_previously_accepted_digest(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "data.win"
            path.write_bytes(UT)
            self.assertEqual(vg.check_versions(vg.GAMES["undertale"], tmp, ALLOW)["root"][0], "ok")
            with mock.patch.object(vg, "sha256_file", side_effect=PermissionError("fixture denied")):
                state, error = vg.check_versions(vg.GAMES["undertale"], tmp, ALLOW)["root"]
            self.assertEqual(state, "unreadable")
            self.assertIn("fixture denied", error)


class LibraryFolderTests(unittest.TestCase):
    """Library lists are search hints; acceptance still depends only on the selected file bytes."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.tmp = temporary.name
        self.tree = Tree(self.tmp)

    def verify(self):
        return vg.verify('undertale', steam_roots=[self.tree.root], gog_dirs=[], allow_list=ALLOW,
                         platform='win32')

    def test_ok_second_library(self):
        folder = self.tree.install('391540', 'Undertale', {'data.win': UT})
        result = self.verify()
        self.assertTrue(result.accepted, result.message)
        self.assertEqual(vg._norm(result.folder), vg._norm(folder))
        self.assertEqual(result.store, 'steam')

    def test_old_libraryfolders_format(self):
        self.tree = Tree(self.tmp, old_format=True)
        folder = self.tree.install('391540', 'Undertale', {'data.win': UT})
        result = self.verify()
        self.assertTrue(result.accepted, result.message)
        self.assertEqual(vg._norm(result.folder), vg._norm(folder))

    def test_library_in_steam_root(self):
        folder = self.tree.install('391540', 'Undertale', {'data.win': UT}, lib=self.tree.root)
        result = self.verify()
        self.assertTrue(result.accepted, result.message)
        self.assertEqual(vg._norm(result.folder), vg._norm(folder))

    def test_unlisted_library_is_ignored(self):
        folder = self.tree.install('391540', 'Undertale', {'data.win': UT}, lib=os.path.join(self.tmp, 'Unlisted'))
        self.assertEqual(self.verify().status, vg.NOT_FOUND)
        # A hand-picked copy outside the list is still accepted: discovery is never a gate.
        result = vg.verify('undertale', game_dir=folder, steam_roots=[], gog_dirs=[], allow_list=ALLOW)
        self.assertTrue(result.accepted, result.message)


class HashOnlyTests(unittest.TestCase):
    def verify(self, folder, allow=ALLOW, game='undertale', **kwargs):
        return vg.verify(game, game_dir=folder, steam_roots=[], gog_dirs=[], allow_list=allow,
                         macos_allow_list=MAC_ALLOW, **kwargs)

    def test_copied_windows_steam_and_gog_without_any_record(self):
        for store in ('steam', 'gog'):
            with self.subTest(store=store), tempfile.TemporaryDirectory() as tmp:
                write(os.path.join(tmp, 'data.win'), UT)
                result = self.verify(tmp, [row('undertale', 'root', UT, store=store)])
                self.assertTrue(result.accepted, result.message)
                self.assertEqual(result.store, store)

    def test_copied_app_in_fake_downloads_without_steam_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = os.path.join(tmp, 'Downloads')
            write(os.path.join(folder, BUNDLE + 'game.ios'), MAC)
            for pick in (folder, os.path.join(folder, 'UNDERTALE.app'),
                         os.path.join(folder, BUNDLE.rstrip('/'))):
                with mock.patch.object(vg, 'default_steam_roots', side_effect=AssertionError('store probe')), \
                     mock.patch.object(vg, 'default_gog_dirs', side_effect=AssertionError('store probe')):
                    result = vg.verify('undertale', game_dir=pick, allow_list=ALLOW,
                                       macos_allow_list=MAC_ALLOW, platform='darwin')
                self.assertTrue(result.accepted, result.message)
                self.assertEqual(result.layout, 'macos')

    def test_one_changed_byte_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, 'data.win'), UT[:-1] + bytes([UT[-1] ^ 1]))
            result = self.verify(tmp)
            self.assertEqual(result.status, vg.UNKNOWN_VERSION)
            self.assertEqual(result.accepted_parts, [])

    def test_store_files_are_never_opened_for_search_or_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp)
            folder = tree.install('391540', 'Undertale', {'data.win': UT}, owner=OTHER, flags=6)
            for path in (os.path.join(tree.root, 'config', 'config.vdf'),
                         os.path.join(folder, 'goggame-1456487183.info'),
                         os.path.join(folder, 'goggame-1456487183.hashdb'),
                         os.path.join(tmp, 'galaxy-2.0.db')):
                write(path, 'poison')
            real_open = open
            opened = []
            def guarded(path, *args, **kwargs):
                name = os.path.basename(os.fspath(path)).lower()
                opened.append(name)
                if name in ('loginusers.vdf', 'config.vdf') or name.startswith(('appmanifest_', 'goggame-')) or name.endswith('.db'):
                    raise AssertionError('opened forbidden store file: ' + name)
                return real_open(path, *args, **kwargs)
            with mock.patch('builtins.open', side_effect=guarded):
                result = vg.verify('undertale', steam_roots=[tree.root], gog_dirs=[], allow_list=ALLOW)
                self.assertTrue(result.accepted, result.message)
                self.assertTrue(self.verify(folder).accepted)
            self.assertIn('libraryfolders.vdf', opened)

    def test_missing_manifest_and_login_file_do_not_refuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            tree = Tree(tmp, old_format=True)
            folder = tree.install('391540', 'Undertale', {'data.win': UT})
            os.remove(os.path.join(tree.lib, 'steamapps', 'appmanifest_391540.acf'))
            os.remove(os.path.join(tree.root, 'config', 'loginusers.vdf'))
            result = vg.verify('undertale', steam_roots=[tree.root], gog_dirs=[], allow_list=ALLOW)
            self.assertTrue(result.accepted, result.message)
            self.assertEqual(vg._norm(folder), vg._norm(result.folder))

    def test_malformed_library_list_only_reduces_discovery(self):
        for text in ('"libraryfolders" "bad"', '"libraryfolders" {',
                     '"libraryfolders" { "1" { "path" { "bad" "value" } } }'):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as tmp:
                tree = Tree(tmp)
                folder = tree.install('391540', 'Undertale', {'data.win': UT})
                write(os.path.join(tree.root, 'steamapps', 'libraryfolders.vdf'), text)
                result = vg.verify('undertale', steam_roots=[tree.root], gog_dirs=[], allow_list=ALLOW)
                self.assertEqual(result.status, vg.NOT_FOUND)
                self.assertTrue(self.verify(folder).accepted)

    def test_gog_registry_is_only_a_folder_hint(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, 'data.win'), UT)
            dirs = vg.default_gog_dirs(vg.GAMES['undertale'], registry=lambda *args: tmp, platform='win32')
            self.assertIn(tmp, dirs)
            self.assertTrue(self.verify(tmp).accepted)
            write(os.path.join(tmp, 'data.win'), b'unknown')
            self.assertFalse(self.verify(tmp).accepted)

    def test_all_deltarune_chapters_need_only_known_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, data in dr_files().items(): write(os.path.join(tmp, rel), data)
            result = self.verify(tmp, game='deltarune')
            self.assertTrue(result.accepted, result.message)
            self.assertEqual(result.accepted_parts, list(vg.GAMES['deltarune'].parts))

    def test_unknown_chapter_is_refused_even_with_known_free_chapters(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, data in dr_files(override={'chapter3_windows': b'changed'}).items():
                write(os.path.join(tmp, rel), data)
            result = self.verify(tmp, game='deltarune')
            self.assertEqual(result.status, vg.UNKNOWN_VERSION)
            self.assertEqual(result.accepted_parts, [])

    def test_deltarune_missing_chapters_are_not_claimed_as_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rel, data in dr_files(parts=('root', 'chapter3_windows')).items():
                write(os.path.join(tmp, rel), data)
            result = self.verify(tmp, game='deltarune')
            self.assertTrue(result.accepted, result.message)
            self.assertEqual(result.accepted_parts, ['root', 'chapter3_windows'])
            os.remove(os.path.join(tmp, 'chapter3_windows', 'data.win'))
            self.assertEqual(self.verify(tmp, game='deltarune').status, vg.MISSING_FILES)

    def test_mixed_editions_including_free_parts_are_refused(self):
        for part in ('chapter1_windows', 'chapter3_windows'):
            with self.subTest(part=part), tempfile.TemporaryDirectory() as tmp:
                for rel, data in dr_files().items(): write(os.path.join(tmp, rel), data)
                allow = [r[:-1] + ('different edition',) if r[0] == 'deltarune' and r[1] == part else r for r in ALLOW]
                result = self.verify(tmp, allow, game='deltarune')
                self.assertEqual(result.status, vg.UNKNOWN_VERSION)
                self.assertIn('different editions', result.message)

    def test_demo_refused_by_content_without_store_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            demo = b'synthetic combined demo'
            write(os.path.join(tmp, 'data.win'), demo)
            with mock.patch.object(vg, 'DELTARUNE_DEMO_ALLOW_LIST', [row('deltarune-demo', 'root', demo)]):
                result = self.verify(tmp, game='deltarune')
            self.assertFalse(result.accepted)
            self.assertIn("demo isn't supported", result.message)

    def test_cli_output_has_no_record_requirement(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(os.path.join(tmp, 'data.win'), UT)
            real = vg.verify
            with mock.patch.object(vg, 'verify', side_effect=lambda *a, **kw: real(*a, **kw, allow_list=ALLOW)), \
                 contextlib.redirect_stdout(io.StringIO()) as output:
                code = vg.main(['verify_game.py', 'undertale', '--game-dir', tmp])
            self.assertEqual(code, 0)
            self.assertIn('supported official copy', output.getvalue())
            self.assertNotIn('account', output.getvalue())


MAC = blob("ut mac")
MAC_ALLOW = [row("undertale", "root", MAC, label="test 1.0 mac")]
BUNDLE = "UNDERTALE.app/Contents/Resources/"


class MacTests(unittest.TestCase):
    """UNDERTALE's macOS depot: game.ios in the bundle, its own allow-list, without store records."""

    def setUp(self):
        self.td = tempfile.TemporaryDirectory()
        self.t = Tree(self.td.name)

    def tearDown(self):
        self.td.cleanup()

    def run_ut(self, **kw):
        return vg.verify("undertale", steam_roots=[self.t.root], gog_dirs=[], allow_list=ALLOW,
                         macos_allow_list=MAC_ALLOW, platform="darwin", **kw)

    def test_mac_layout_accepted(self):
        folder = self.t.install("391540", "Undertale", {BUNDLE + "game.ios": MAC})
        r = self.run_ut()
        self.assertEqual(r.status, vg.OK, r.message)
        self.assertEqual((r.layout, r.version, r.store), ("macos", "test 1.0 mac", "steam"))
        self.assertEqual(vg._norm(r.data_dir), vg._norm(os.path.join(folder, *BUNDLE.split("/")[:3])))

    def test_bundle_name_case(self):
        self.t.install("391540", "Undertale", {"undertale.app/Contents/Resources/game.ios": MAC})
        self.assertEqual(self.run_ut().status, vg.OK)

    def test_pick_inside_bundle(self):
        folder = self.t.install("391540", "Undertale", {BUNDLE + "game.ios": MAC})
        for pick in ("UNDERTALE.app", "UNDERTALE.app/Contents", "UNDERTALE.app/Contents/Resources"):
            r = self.run_ut(game_dir=os.path.join(folder, *pick.split("/")))
            self.assertEqual(r.status, vg.OK, (pick, r.message))
            self.assertEqual(vg._norm(r.folder), vg._norm(folder))

    def test_windows_file_in_mac_layout_refused(self):
        self.t.install("391540", "Undertale", {BUNDLE + "game.ios": UT})
        r = self.run_ut()
        self.assertEqual((r.status, r.layout), (vg.UNKNOWN_VERSION, "macos"))

    def test_mac_file_as_data_win_refused(self):
        self.t.install("391540", "Undertale", {"data.win": MAC})
        r = self.run_ut()
        self.assertEqual((r.status, r.layout), (vg.UNKNOWN_VERSION, "windows"))

    def test_windows_files_next_to_bundle_checked_as_windows(self):
        self.t.install("391540", "Undertale", {"data.win": UT, BUNDLE + "game.ios": MAC})
        r = self.run_ut()
        self.assertEqual((r.status, r.layout, r.version), (vg.OK, "windows", "test 1.0"))

    def test_same_hash_only_rule(self):
        self.t.install("391540", "Undertale", {BUNDLE + "game.ios": MAC}, owner=OTHER)
        self.assertEqual(self.run_ut().status, vg.OK)
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        write(os.path.join(td.name, BUNDLE + "game.ios"), MAC)
        self.assertEqual(self.run_ut(game_dir=td.name).status, vg.OK)

    def test_deltarune_has_no_mac_layout(self):
        self.t.install("1671210", "DELTARUNE", {BUNDLE + "game.ios": MAC})
        r = vg.verify("deltarune", steam_roots=[self.t.root], gog_dirs=[], allow_list=ALLOW,
                      macos_allow_list=MAC_ALLOW + [row("deltarune", "root", MAC)], platform="darwin")
        self.assertEqual(r.status, vg.MISSING_FILES)

    def test_real_rows_are_separate(self):
        win = {(s, d) for g, p, s, d, _, _ in vg.ALLOW_LIST}
        mac = {(s, d) for g, p, s, d, _, _ in vg.MACOS_ALLOW_LIST}
        self.assertTrue(mac)
        self.assertFalse(win & mac)


class DiscoveryTests(unittest.TestCase):
    def test_registry_and_linux_roots(self):
        with tempfile.TemporaryDirectory() as td:
            reg_root = os.path.join(td, "RegSteam")
            os.makedirs(os.path.join(reg_root, "steamapps"))
            roots = vg.default_steam_roots(registry=lambda h, k, v: reg_root if v == "SteamPath" else None,
                                           platform="win32")
            self.assertEqual(roots[0], reg_root)
            lin = os.path.join(td, ".local", "share", "Steam")
            os.makedirs(os.path.join(lin, "steamapps"))
            self.assertEqual([vg._norm(r) for r in vg.default_steam_roots(home=td, platform="linux")], [vg._norm(lin)])

    def test_allow_list_covers_compat_table(self):
        """Every version the 3DS build knows (platform/3ds/data_versions.inc) is an official release here."""
        import re
        inc = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "platform", "3ds", "data_versions.inc")
        with open(inc, encoding="utf-8") as f:
            text = f.read()
        rows = set(re.findall(r'DATA_VERSION\("([^"]+)", "([^"]+)", (\d+)ULL, "([0-9a-f]{64})"\)', text))
        mine = {(g, p, str(s), d) for g, p, s, d, _, _ in vg.ALLOW_LIST + vg.MACOS_ALLOW_LIST}
        self.assertTrue(rows)
        self.assertLessEqual(rows, mine)


if __name__ == "__main__":
    unittest.main()
