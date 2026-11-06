"""Find the user's copies of the game (wizard page 2) and verify one (page 3). Offline; built on verify_game.py.

Every probe is injectable (Steam roots, GOG folders, a registry reader), so the tests run on
fixture VDFs and registry exports instead of this PC's installs.
"""
from __future__ import annotations

import dataclasses
import os
import re
import sys

import products
from products import verify_game as vg


@dataclasses.dataclass
class Copy:
    store: str          # Search location: "Steam", "GOG", "Applications", "Folder" or a manual "folder".
    folder: str
    version: str        # not checked until verification
    note: str = ""
    platform: str = ""  # whose files the folder holds: "Windows", "macOS" (verify_game.Layout.name), "" when neither


@dataclasses.dataclass
class Probes:
    """Where discovery looks. None means "this PC" (verify_game's defaults)."""
    steam_roots: list | None = None
    gog_dirs: list | None = None
    registry: object = None             # callable(hive_name, key, value) -> str | None
    platform: str = sys.platform
    save_dir: str | None = None

    def pc_save_dir(self, game_key):
        if self.save_dir is not None:
            return self.save_dir
        import saves
        return saves.default_pc_save_dir(game_key, platform=self.platform)

    def roots(self):
        if self.steam_roots is not None:
            return list(self.steam_roots)
        return vg.default_steam_roots(registry=self.registry or vg._winreg_value, platform=self.platform)

    def gog_candidates(self, game):
        if self.gog_dirs is not None:
            return [d for d in self.gog_dirs if os.path.isdir(d)]
        if not game.gog_product:
            return []
        out = vg.default_gog_dirs(game, registry=self.registry or vg._winreg_value, platform=self.platform)
        return list(dict.fromkeys(out))


def find_copies(game_key, probes: Probes | None = None):
    """Offer known locations containing game data. Only verification determines edition and acceptance."""
    probes = probes or Probes()
    game = vg.GAMES[game_key]
    out, seen = [], set()
    candidates = [("Steam", d) for d in vg.steam_folders(game, probes.roots())]
    for folder in probes.gog_candidates(game):
        location = os.path.normpath(folder)
        source = 'GOG'
        if probes.platform == 'darwin' and os.path.basename(location).casefold() == 'applications':
            source = 'Applications'
        elif probes.platform == 'linux' and os.path.basename(os.path.dirname(location)).casefold() == 'games':
            source = 'Folder'
        candidates.append((source, folder))
    for source, folder in candidates:
        key = vg._norm(folder)
        if key in seen:
            continue
        seen.add(key)
        layout = vg.layout_for(game, folder)
        if layout is not None:
            out.append(Copy(source, folder, "Not checked yet", platform=layout.name))
    return out


@dataclasses.dataclass
class Verdict:
    accepted: bool
    result: vg.Result
    music_ok: bool
    message: str
    store_links: tuple

    @property
    def parts(self):
        return list(self.result.accepted_parts)

    @property
    def platform(self):
        """Whose files were checked: "Windows" or "macOS" (the GUI's label for the copy), "" when none were found."""
        return {"windows": "Windows", "macos": "macOS"}.get(self.result.layout or "", "")


def verify_copy(game_key, folder, probes: Probes | None = None, allow_list=None, macos_allow_list=None) -> Verdict:
    """Check game and music files against known official copies. A Mac copy (UNDERTALE.app) is checked against
    the macOS rows and music record; the Windows depot steps are only for native files the builder does not know."""
    probes = probes or Probes()
    product = products.PRODUCTS[game_key]
    game = product.game
    r = vg.verify(game_key, game_dir=folder, steam_roots=[], gog_dirs=[], platform=probes.platform,
                  allow_list=vg.ALLOW_LIST if allow_list is None else allow_list,
                  macos_allow_list=vg.MACOS_ALLOW_LIST if macos_allow_list is None else macos_allow_list)
    if not r.accepted:
        message = r.message
        # Unknown Mac files may be a native GOG copy; metadata is never proof of their edition.
        if r.layout == 'macos' and r.status == vg.UNKNOWN_VERSION:
            message += ("\nFor a GOG copy, choose a complete folder of the supported Windows GOG files, "
                        "with their original music. Keep your Mac installation unchanged.")
        if r.layout is None and native_data_files(folder):
            native = native_data_files(folder)
            file_platform = 'linux' if any(p.endswith('game.unx') for p in native) else 'darwin'
            message = windows_depot_message(game_key, file_platform)
        return Verdict(False, r, False, message, game.store_links)
    excluded = []
    if game_key == 'deltarune':
        import chapters
        checked, audio_failures = {}, []
        root_errors = chapters.audio_errors(folder, ['root'], checked)
        if root_errors:
            return Verdict(False, r, False, 'Missing or unreadable audio: %s. Restore the complete original game folder, then try again.' % root_errors[0], ())
        for part in list(r.accepted_parts):
            errors = chapters.audio_errors(folder, [part], checked) if part != 'root' else []
            if errors:
                audio_failures.extend(errors)
                r.accepted_parts.remove(part)
                r.refused_parts.append(part)
                excluded.append(part)
        if not any(p != 'root' for p in r.accepted_parts):
            return Verdict(False, r, False, 'Missing or unreadable audio: %s. Restore the complete original game folder, then try again.' % audio_failures[0], ())
    ok, note = products.music_check(product, r.data_dir or folder, r.version, platform=r.layout or "windows",
                                    parts=r.accepted_parts, store=r.store or "steam")
    if not ok:
        return Verdict(False, r, False, note, ())
    if excluded:
        playable = [p for p in r.accepted_parts if p != 'root']
        message = 'Ready to build: %s. Audio missing for %s; unavailable. Restore the complete original game folder, then try again.' % (
            ', '.join(vg._chapter_name(p) for p in playable),
            ', '.join(vg._chapter_name(p) for p in excluded))
        return Verdict(True, r, True, message + ' ' + note, ())
    return Verdict(True, r, True, r.message + " " + note, ())


def native_data_files(folder):
    """Probe the known Linux assets and macOS bundle locations, without following directory links."""
    bases = [folder, os.path.join(folder, "assets")]
    try:
        bundles = [os.path.join(folder, n, "Contents", "Resources") for n in os.listdir(folder)
                   if n.lower().endswith(".app")]
    except OSError:
        return []
    if folder.lower().endswith(".app"):
        bundles.append(os.path.join(folder, "Contents", "Resources"))
    bases += bundles
    # Chapter data may sit below a native bundle's Resources directory.
    for base in list(bases):
        for part in vg.GAMES["deltarune"].parts:
            if part != "root":
                bases.append(os.path.join(base, part))
    return [os.path.join(b, name) for b in bases for name in ("game.unx", "game.ios")
            if os.path.isfile(os.path.join(b, name))]


def windows_depot_message(game_key, platform=sys.platform, store="steam"):
    """Short numbered steps; the full walk-through is docs/release/builder-platforms.md."""
    title = products.PRODUCTS[game_key].title
    head = "These %s game files for %s aren't supported by this builder.\n" % (
        "Linux" if platform == "linux" else "Mac", title)
    if store == 'gog':
        return ("This builder cannot use GOG's Mac or Linux game files yet.\n"
                "If you have the supported Windows GOG version, copy its complete folder with its original music "
                "and choose that folder here.\nKeep your Mac or Linux installation unchanged.")
    head += ("For GOG, choose a complete folder of the supported Windows GOG files, with their original music.\n"
             "For Steam, use these steps to download the Windows files:\n")
    if platform == "linux":
        return head + ("1. In Steam, right-click %s > Properties > Compatibility.\n"
                       "2. Tick 'Force the use of a specific Steam Play compatibility tool', choose Proton "
                       "Experimental.\n"
                       "3. Let Steam download the Windows version.\n"
                       "4. Manage > Browse local files, then choose that folder here.\n"
                       "Keep Proton selected while you build." % title)
    if game_key == "undertale":
        return head + ("1. Open steam://open/console in your browser and let Steam open it.\n"
                       "2. In Steam's Console, enter: download_depot 391540 391541\n"
                       "3. Wait for 'Depot download complete'.\n"
                       "4. In Finder, press Command-Shift-G and open\n"
                       "   ~/Library/Application Support/Steam/steamapps/content/app_391540/depot_391541\n"
                       "5. Choose that downloaded folder here. Keep all its files together.")
    return head + ("1. Open steam://open/console and enter: app_info_print 1671210\n"
                   "2. Find the depot whose oslist is windows, then enter: download_depot 1671210 <depot ID>\n"
                   "3. Choose the downloaded folder here. Keep all its files together.")


# ---------------------------------------------------------------------------------------------------------------------
# Registry exports (regedit's .reg text), for tests and for support: a user can export the Steam and GOG keys and the
# builder's --dry-run can read them instead of the live registry.

_HIVES = {"HKEY_LOCAL_MACHINE": "HKEY_LOCAL_MACHINE", "HKLM": "HKEY_LOCAL_MACHINE",
          "HKEY_CURRENT_USER": "HKEY_CURRENT_USER", "HKCU": "HKEY_CURRENT_USER"}


def _unescape_reg(s):
    return re.sub(r'\\(.)', r'\1', s)


def parse_reg_export(text):
    """{(hive, key lower-case): {value name lower-case: string}} from a .reg export. Only REG_SZ ("...") and dword
    values are kept, which is all the builder reads. A 64-bit export's WOW6432Node keys are also filed under the
    plain path, the way the 32-bit registry view shows them."""
    if text.startswith("﻿"):
        text = text[1:]
    out, cur = {}, None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            path = line[1:-1]
            hive, _, key = path.partition("\\")
            hive = _HIVES.get(hive.upper())
            cur = None
            if hive:
                cur = {}
                keys = [key]
                if "\\wow6432node\\" in key.lower():
                    keys.append(re.sub(r"(?i)\\wow6432node\\", r"\\", key, count=1))
                for k in keys:
                    out.setdefault((hive, k.lower()), {})
                cur = [out[(hive, k.lower())] for k in keys]
            continue
        if cur is None:
            continue
        m = re.match(r'^(@|"((?:[^"\\]|\\.)*)")=(.*)$', line)
        if not m:
            continue
        name = "" if m.group(1) == "@" else _unescape_reg(m.group(2))
        val = m.group(3)
        if val.startswith('"') and val.endswith('"'):
            v = _unescape_reg(val[1:-1])
        elif val.lower().startswith("dword:"):
            v = str(int(val[6:], 16))
        else:
            continue
        for d in cur:
            d[name.lower()] = v
    return out


def registry_from_export(text):
    """A registry reader with verify_game._winreg_value's signature, backed by a .reg export."""
    table = parse_reg_export(text)

    def read(hive_name, key, value):
        return table.get((hive_name, key.lower()), {}).get(value.lower())
    return read


def read_reg_file(path):
    with open(path, "rb") as f:
        data = f.read()
    for enc in ("utf-16", "utf-8-sig") if data[:2] in (b"\xff\xfe", b"\xfe\xff") else ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")
