#!/usr/bin/env python3
"""Check game files against known official copies, offline, by size and SHA-256.
No account, purchase, or store installation record is consulted. Folder discovery
is only a convenience: a manually selected copy is checked in exactly the same way.
Windows data.win and supported macOS game.ios files have separate allow-lists.
Unknown, modified, mixed-edition and unsupported demo files are refused.

usage: verify_game.py undertale|deltarune [--game-dir DIR] [--steam-root DIR ...] [--gog-dir DIR ...] [--json]
Exit status: 0 accepted, 1 refused, 2 usage error. No game content is bundled.
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import sys
from typing import Iterable

# ---------------------------------------------------------------------------------------------------------------------
# names only: official releases. Each row: game, part (the data.win's folder, "root" for the game folder itself), size in bytes,
# SHA-256, store, version label. Only identifiers, sizes and digests; no game bytes. Measured from
# purchased Steam copies on 2026-10-16 (the same digests as platform/3ds/data_versions.inc, revision 1).
# GOG UNDERTALE 1.08 measured from the owner's read-only Windows install on 2026-10-22. The container is shared with
# other storefronts. Edition recognition depends only on the measured game files.
# DELTARUNE Chapter 6 (planned for 2027) is expected to re-patch older chapters: add the new rows, keep the old ones.
# Chapter audio validation also uses this fixed policy; unknown data is never accepted.
ALLOW_UNKNOWN_DELTARUNE = False
DELTARUNE_DEMO_APPID = "1690940"
# Measured Windows demo (1690940), combined Chapters 1+2, not the retail per-chapter product.
# The separate game key deliberately keeps these rows inactive until that variant is approved and implemented.
DELTARUNE_DEMO_ALLOW_LIST = [
    ("deltarune-demo", "root", 89903138, "4de4118ba4ad4243025e61337fe796532751032c0a04d0843d8b35f91ec2c220",
     "steam", "1.10 (Steam build 8272590)"),
]
DELTARUNE_DEMO_AUDIO = {
    "audiogroup1.dat": (15683508, "aa7593cf993cd19dc9fe30aa8d9eaf910a3072a481c6efa49d14a992c8b62d02"),
}

ALLOW_LIST = [
    ("undertale", "root", 62921978, "b718f8223a5bb31979ffeed10be6140c857b882fc0d0462b89d6287ae38c81c7",
     "steam", "1.08 (Steam build 4279148)"),
    ("undertale", "root", 62951906, "946c738c6d6182f683431320a0e32470bc3deb50f3e8887e61998df0c4e3abc8",
     "gog", "1.08 (GOG)"),
    ("deltarune", "root", 2953218, "82a7041a530407c5f17e439a97bdf53e4a24e30775a7ecbc2879369b9d2441d6",
     "steam", "v0.0.253 (Steam build 24484059)"),
    ("deltarune", "chapter1_windows", 13072876, "82c2bb61b8d78cd287120f6301588fecba34ec5a890bac711b7a8774c760ec70",
     "steam", "v0.0.253 (Steam build 24484059)"),
    ("deltarune", "chapter2_windows", 66949110, "047c5ab003e3e017a709c02757e119c81e0327760169512110fd276b19241e68",
     "steam", "v0.0.253 (Steam build 24484059)"),
    ("deltarune", "chapter3_windows", 126284402, "c1a0925343694ec9b9adcbf2f916a720b02fd1b999286cfe8fe6a52f3320f714",
     "steam", "v0.0.253 (Steam build 24484059)"),
    ("deltarune", "chapter4_windows", 132041918, "ed64789586238b52375e994e1c1cf13694dd2d0dab57d13e639b9c892e37d8f2",
     "steam", "v0.0.253 (Steam build 24484059)"),
    ("deltarune", "chapter5_windows", 165423612, "370dfd141d2955d5a1960122919b16e4092b52ffbb85fda541bc4680c6b3b85c",
     "steam", "v0.0.253 (Steam build 24484059)"),
]
# The macOS depot's files, in the same row format. Measured from a purchased Steam copy (Mac) on 2026-10-21:
# the same 1.08 game, a later (2019) build of its data file (platform/3ds/data_versions.inc, revision 2). The label is
# the key of the macOS record in music-versions.json.
MACOS_ALLOW_LIST = [
    ("undertale", "root", 62956178, "91a8acf1f40bd7c45d0bdb978de55187e7fb2cd76a1e2cda41c078dd44d3565e",
     "steam", "1.08 (Steam macOS)"),
]


@dataclasses.dataclass(frozen=True)
class Layout:
    """Where one store depot keeps the data file. Rows of one layout never match another layout's file."""
    key: str                   # "windows" or "macos": the music record's depot and the allow list used
    name: str                  # shown to the user
    resources: tuple           # folders from the install folder to the data file and music; () for the folder itself
    data_name: str             # the root data file's name there

    def data_dir(self, folder):
        """The folder holding the root data file and the music, or None when the bundle is not there. Bundle folder
        names are matched without regard to case, as macOS volumes usually do."""
        d = folder
        for name in self.resources:
            hit = os.path.join(d, name)
            if not os.path.isdir(hit):
                try:
                    hit = next((os.path.join(d, n) for n in sorted(os.listdir(d)) if n.casefold() == name.casefold()),
                               None)
                except OSError:
                    hit = None
                if hit is None or not os.path.isdir(hit):
                    return None
            d = hit
        return d

    def data_path(self, folder, part="root"):
        """The data file of `part`, or None when this layout has no place for it."""
        if self.key == "windows":
            return os.path.join(folder, "data.win") if part == "root" else os.path.join(folder, part, "data.win")
        d = self.data_dir(folder)
        return os.path.join(d, self.data_name) if d is not None and part == "root" else None


WINDOWS = Layout("windows", "Windows", (), "data.win")
MACOS_UNDERTALE = Layout("macos", "macOS", ("UNDERTALE.app", "Contents", "Resources"), "game.ios")
ALLOW_LISTS = {"windows": ALLOW_LIST, "macos": MACOS_ALLOW_LIST}


@dataclasses.dataclass(frozen=True)
class Game:
    key: str
    title: str
    install_dirs: tuple        # steamapps/common/<name> spellings, for folder discovery
    gog_product: str | None
    store_links: tuple
    parts: tuple               # data.win folders, "root" first
    layouts: tuple = (WINDOWS,)  # depots recognised, in the order tried


GAMES = {
    "undertale": Game("undertale", "UNDERTALE", ("Undertale", "UNDERTALE"), "1456487183",
                      ("https://store.steampowered.com/app/391540/Undertale/", "https://www.gog.com/game/undertale"),
                      ("root",), (WINDOWS, MACOS_UNDERTALE)),
    "deltarune": Game("deltarune", "DELTARUNE", ("DELTARUNE", "Deltarune", "DELTARUNEdemo", "DELTARUNE Demo"),
                      None, ("https://store.steampowered.com/app/1671210/DELTARUNE/",),
                      ("root",) + tuple("chapter%d_windows" % i for i in range(1, 6))),
}

# ---------------------------------------------------------------------------------------------------------------------
# Valve KeyValues text (.vdf / .acf)

_TOKEN = re.compile(r'\s*(?:(//[^\n]*)|(")|(\{)|(\})|([^\s{}"]+))', re.S)


def parse_vdf(text: str) -> dict:
    """Parses Valve's text KeyValues into nested dicts. Keys are kept as written; use vget() for case-insensitive
    lookups. Later duplicate keys win, as in Steam. Raises ValueError on malformed input."""
    pos, n = 0, len(text)
    if text.startswith("\ufeff"):
        pos = 1

    def token():
        nonlocal pos
        while True:
            m = _TOKEN.match(text, pos)
            if not m or m.end() == pos and pos >= n:
                return None
            if m.group(1) is not None:          # comment
                pos = m.end()
                continue
            if m.group(2):                      # quoted string with \\ \" \n \t escapes
                i = m.end()
                out = []
                while i < n and text[i] != '"':
                    c = text[i]
                    if c == "\\" and i + 1 < n:
                        nxt = text[i + 1]
                        out.append({"n": "\n", "t": "\t", "\\": "\\", '"': '"'}.get(nxt, "\\" + nxt))
                        i += 2
                        continue
                    out.append(c)
                    i += 1
                if i >= n:
                    raise ValueError("unterminated string")
                pos = i + 1
                return ("s", "".join(out))
            pos = m.end()
            if m.group(3):
                return ("{", None)
            if m.group(4):
                return ("}", None)
            if m.group(5):
                return ("s", m.group(5))
            return None

    def block(top):
        d = {}
        while True:
            t = token()
            if t is None:
                if top:
                    return d
                raise ValueError("unexpected end of file")
            if t[0] == "}":
                if top:
                    raise ValueError("unbalanced }")
                return d
            if t[0] != "s":
                raise ValueError("expected a key")
            v = token()
            if v is None:
                raise ValueError("key without value")
            if v[0] == "{":
                d[t[1]] = block(False)
            elif v[0] == "s":
                d[t[1]] = v[1]
            else:
                raise ValueError("unexpected }")
    return block(True)


def vget(d, *keys):
    """Case-insensitive nested lookup; None when any step is missing."""
    for k in keys:
        if not isinstance(d, dict):
            return None
        hit = None
        for kk, vv in d.items():
            if kk.lower() == k.lower():
                hit = vv
        d = hit
    return d


def read_vdf(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return parse_vdf(f.read())


# ---------------------------------------------------------------------------------------------------------------------
# Platform probes, injectable for tests

def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(p)))


def _winreg_value(hive_name, key, value):
    try:
        import winreg
    except ImportError:
        return None
    hive = getattr(winreg, hive_name)
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(hive, key, 0, winreg.KEY_READ | view) as k:
                return str(winreg.QueryValueEx(k, value)[0])
        except OSError:
            continue
    return None


def default_steam_roots(registry=_winreg_value, home=None, platform=sys.platform):
    """Steam client folders: the registry's on Windows, then the usual install paths on each system."""
    roots = []
    if platform == "win32":
        for hive, key, value in (("HKEY_CURRENT_USER", r"Software\Valve\Steam", "SteamPath"),
                                 ("HKEY_LOCAL_MACHINE", r"SOFTWARE\Valve\Steam", "InstallPath")):
            v = registry(hive, key, value)
            if v:
                roots.append(v)
        roots += ["C:/Program Files (x86)/Steam", "C:/Program Files/Steam"]
    home = home or os.path.expanduser("~")
    if platform == "darwin":
        roots.append(os.path.join(home, "Library", "Application Support", "Steam"))
    elif platform != "win32":
        roots += [os.path.join(home, ".steam", "steam"), os.path.join(home, ".local", "share", "Steam"),
                  os.path.join(home, ".var", "app", "com.valvesoftware.Steam", ".local", "share", "Steam"),
                  os.path.join(home, "snap", "steam", "common", ".local", "share", "Steam")]
    out, seen = [], set()
    for r in roots:
        if os.path.isdir(os.path.join(r, "steamapps")):
            key = _norm(os.path.realpath(r))
            if key not in seen:
                seen.add(key)
                out.append(r)
    return out


def default_gog_dirs(game: Game, registry=_winreg_value, platform=sys.platform, home=None):
    """Candidate GOG folders to look at when the user did not pick one."""
    if not game.gog_product:
        return []
    out = []
    if platform == "win32":
        path = registry("HKEY_LOCAL_MACHINE", r"SOFTWARE\GOG.com\Games\%s" % game.gog_product, "path")
        if path:
            out.append(path)
    home = home or os.path.expanduser("~")
    if platform == "win32":
        out += ["C:/GOG Games/Undertale", "C:/Program Files (x86)/GOG Galaxy/Games/Undertale"]
    elif platform == "darwin":
        out += ["/Applications"]
    else:
        out += [os.path.join(home, "GOG Games", "Undertale", "game"), os.path.join(home, "Games", "undertale")]
    return [d for d in dict.fromkeys(out) if os.path.isdir(d)]


# ---------------------------------------------------------------------------------------------------------------------
# Results

OK, NOT_FOUND, UNKNOWN_VERSION, MISSING_FILES, UNREADABLE = (
    "ok", "not_found", "unknown_version", "missing_files", "unreadable")


@dataclasses.dataclass
class Result:
    status: str
    game: str
    folder: str | None = None
    store: str | None = None
    version: str | None = None
    accepted_parts: list = dataclasses.field(default_factory=list)
    refused_parts: list = dataclasses.field(default_factory=list)
    message: str = ""
    details: list = dataclasses.field(default_factory=list)
    layout: str | None = None      # "windows" or "macos": whose files were checked (Layout.key)
    data_dir: str | None = None    # the folder holding them and the music; the install folder for Windows

    @property
    def accepted(self):
        return self.status == OK


def _chapter_name(part):
    return "the launcher" if part == "root" else "Chapter " + part[len("chapter")] if part.startswith("chapter") else part


# ---------------------------------------------------------------------------------------------------------------------
# Version check

def sha256_file(path, block=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(block), b""):
            h.update(chunk)
    return h.hexdigest()


def data_digest(path):
    """Read current bytes on every verification or receipt request.

    Size, timestamps and file identity cannot prove unchanged contents on every
    supported filesystem. Rehash rather than reuse an earlier acceptance when
    an in-place edit or replacement preserves those attributes.
    """
    return sha256_file(path)


def layout_for(game: Game, folder: str):
    """The depot layout of an install folder: the first of game.layouts whose root data file is there (Windows first,
    so Windows files copied next to the Mac bundle are checked as Windows files), or None."""
    for layout in game.layouts:
        path = layout.data_path(folder)
        if path and os.path.isfile(path):
            return layout
    return None


def check_versions(game: Game, folder: str, allow_list: Iterable = ALLOW_LIST, layout: Layout = WINDOWS):
    """Per part: ("ok", label) / ("unknown", None) / ("missing", None) / ("unreadable", error). Only `layout`'s files
    are read, and only against `allow_list`, which must be that layout's rows."""
    index = {}
    for g, part, size, digest, store, label in allow_list:
        if g == game.key:
            index.setdefault(part, {})[(size, digest)] = (store, label)
    out = {}
    for part in game.parts:
        path = layout.data_path(folder, part)
        if not path or not os.path.isfile(path):
            out[part] = ("missing", None)
            continue
        try:
            size = os.path.getsize(path)
            known = index.get(part, {})
            if not any(s == size for s, _ in known):    # cheap reject before hashing
                out[part] = ("unknown", None)
                continue
            digest = data_digest(path)
        except OSError as e:
            out[part] = ("unreadable", str(e))
            continue
        hit = known.get((size, digest))
        out[part] = ("ok", hit) if hit else ("unknown", None)
    return out


# ---------------------------------------------------------------------------------------------------------------------
# Folder discovery (never installation proof)

def steam_libraries(root):
    """Libraries the Steam client at `root` knows: the root itself plus each path in libraryfolders.vdf (both the
    current format, "libraryfolders" { "0" { "path" ... } }, and the old one, "LibraryFolders" { "1" "D:\\..." })."""
    libs = [root]
    for vdf in (os.path.join(root, "steamapps", "libraryfolders.vdf"), os.path.join(root, "config", "libraryfolders.vdf")):
        if not os.path.isfile(vdf):
            continue
        try:
            data = read_vdf(vdf)
        except (OSError, ValueError):
            continue
        top = vget(data, "libraryfolders")
        if not isinstance(top, dict):
            continue
        for k, v in top.items():
            if not k.isdigit():
                continue
            path = vget(v, "path") if isinstance(v, dict) else v
            if isinstance(path, str) and path:
                libs.append(path)
    out, seen = [], set()
    for lib in libs:
        key = _norm(lib)
        if key not in seen:
            seen.add(key)
            out.append(lib)
    return out


def steam_folders(game: Game, roots):
    """Existing default game folders, using only Steam's library folder list."""
    out = []
    candidates = (os.path.join(lib, "steamapps", "common", name)
                  for root in roots for lib in steam_libraries(root) for name in game.install_dirs)
    for folder in candidates:
        if not os.path.isdir(folder):
            continue
        for previous in out:
            try:
                if os.path.samefile(folder, previous):
                    break
            except OSError:
                continue  # A removed or inaccessible search candidate cannot block the search.
        else:
            out.append(folder)
    return out


def install_folder(game: Game, folder: str):
    """Normalize a selection of the Mac bundle, Contents or Resources to its containing folder."""
    if os.path.isfile(os.path.join(folder, 'data.win')):
        return folder
    parts = os.path.normpath(folder).split(os.sep)
    for layout in game.layouts:
        for depth in range(len(layout.resources), 0, -1):
            want = [n.casefold() for n in layout.resources[:depth]]
            if len(parts) > depth and [n.casefold() for n in parts[-depth:]] == want:
                up = os.path.normpath(folder)
                for _ in range(depth):
                    up = os.path.dirname(up)
                if layout_for(game, up) is layout:
                    return up
    return folder


def verify(game_key, game_dir=None, steam_roots=None, gog_dirs=None, allow_list=ALLOW_LIST,
           platform=sys.platform, macos_allow_list=MACOS_ALLOW_LIST):
    game = GAMES[game_key]
    lists = {"windows": list(allow_list), "macos": list(macos_allow_list)}
    if game_dir:
        # A hand-picked folder never needs any store probe.
        candidates = [install_folder(game, os.fspath(game_dir))]
    else:
        roots = default_steam_roots(platform=platform) if steam_roots is None else steam_roots
        candidates = steam_folders(game, roots)
        candidates += default_gog_dirs(game, platform=platform) if gog_dirs is None else gog_dirs
    if not candidates:
        return Result(NOT_FOUND, game.key, message=(
            "%s wasn't found in the usual folders. Choose your game folder to check its files." % game.title))
    results = [_verify_folder(game, folder, lists) for folder in dict.fromkeys(candidates)]
    rank = {OK: 0, UNKNOWN_VERSION: 1, UNREADABLE: 2, MISSING_FILES: 3, NOT_FOUND: 4}
    return min(results, key=lambda r: rank[r.status])


def _verify_folder(game, folder, lists):
    res = Result(MISSING_FILES, game.key, folder)
    layout = layout_for(game, folder) if os.path.isdir(folder) else None
    if layout is None:
        if any(os.path.isfile(os.path.join(folder, *relative))
               for relative in (('game.unx',), ('assets', 'game.unx'))):
            res.message = ("%s's native Linux files are not supported. Use its Windows version from Steam or GOG. "
                           "For Steam, choose Proton in Properties > Compatibility, let the download finish, "
                           "then select the game folder again." % game.title)
        else:
            res.message = ("This folder has no data.win%s. Choose the folder with %s's game files." % (
                " or UNDERTALE.app" if game.key == "undertale" else "", game.title))
        return res
    res.layout, res.data_dir = layout.key, layout.data_dir(folder)
    versions = check_versions(game, folder, lists.get(layout.key, ()), layout)
    unreadable = [p for p, (state, _) in versions.items() if state == "unreadable"]
    if unreadable:
        res.status = UNREADABLE
        res.message = "Could not read %s's game files. Check folder access and try again." % game.title
        res.details = ["%s: %s" % (layout.data_path(folder, p), versions[p][1]) for p in unreadable]
        return res
    present = [p for p in game.parts if versions[p][0] != "missing"]
    unknown = [p for p in present if versions[p][0] == "unknown"]
    if unknown:
        res.status = UNKNOWN_VERSION
        res.refused_parts = unknown
        res.message = ("These game files don't match an official release supported by this builder. "
                       "Restore the original game files or try a newer builder.")
        if game.key == 'deltarune':
            res.message += ' Files to check: ' + ', '.join(_chapter_name(p) for p in unknown) + '.'
        if (game.key == "deltarune" and "root" in unknown and layout is WINDOWS
                and check_versions(dataclasses.replace(game, key="deltarune-demo"), folder,
                                   DELTARUNE_DEMO_ALLOW_LIST, layout)["root"][0] == "ok"):
            res.message = ("The DELTARUNE demo isn't supported by this builder. "
                           "Choose the full game's folder instead.")
        return res
    if game.key == "deltarune" and not any(p != "root" for p in present):
        res.message = "No chapter files were found. Restore the original game files, then try again."
        return res
    if "root" not in present:
        res.message = "Some game files are missing. Restore the original game files, then try again."
        return res
    editions = {versions[p][1] for p in present}
    if len(editions) != 1:
        res.status = UNKNOWN_VERSION
        res.refused_parts = present
        res.message = "These game files come from different editions. Choose one complete copy of the game."
        return res
    res.store, res.version = editions.pop()
    res.accepted_parts = present
    res.status = OK
    res.message = "%s's game files match a supported official copy." % game.title
    return res


# ---------------------------------------------------------------------------------------------------------------------

def main(argv):
    args = argv[1:]
    if not args or args[0] not in GAMES:
        print(__doc__)
        return 2
    game, rest = args[0], args[1:]
    game_dir, roots, gog, as_json = None, None, None, False
    i = 0
    while i < len(rest):
        a = rest[i]
        if a == "--json":
            as_json = True
            i += 1
            continue
        if i + 1 >= len(rest):
            print(__doc__)
            return 2
        v = rest[i + 1]
        if a == "--game-dir":
            game_dir = v
        elif a == "--steam-root":
            roots = (roots or []) + [v]
        elif a == "--gog-dir":
            gog = (gog or []) + [v]
        else:
            print(__doc__)
            return 2
        i += 2
    r = verify(game, game_dir=game_dir, steam_roots=roots, gog_dirs=gog)
    if as_json:
        print(json.dumps(dataclasses.asdict(r) | {"accepted": r.accepted}, indent=2))
    else:
        print(("OK: " if r.status == OK else "REFUSED: ") + r.message)
        if r.folder:
            print("  folder: %s" % r.folder)
        for d in r.details:
            print("  " + d)
        if r.accepted_parts or r.refused_parts:
            print("  accepted: %s" % (", ".join(r.accepted_parts) or "-"))
            print("  refused: %s" % (", ".join(r.refused_parts) or "-"))
    return 0 if r.accepted else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
