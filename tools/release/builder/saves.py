"""Wizard page 8: find, inspect, back up and copy PC saves to the 3DS SD card.

PC save folders (%LOCALAPPDATA%\\UNDERTALE and %LOCALAPPDATA%\\DELTARUNE on Windows) are strictly read-only.
Existing 3DS saves in sd:/3ds/<game>-3ds/saves/ are never overwritten without confirmation and are backed up to
saves/backup-<YYYYMMDD-HHMMSS>/ first.
"""
from __future__ import annotations

import dataclasses
import errno
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import time

import products

MAX_SAVE_BYTES = 65536
IGNORED_SAVE_NAMES = {"steam_autocloud.vdf", "desktop.ini", "thumbs.db", ".ds_store"}
IGNORED_SAVE_SUFFIXES = (".bak", ".tmp", ".part")
READ_ONLY_MESSAGE = ("The builder could not write to the SD card at %s. Check its free space and folder access. "
                     "If you use an SD adapter with a Lock switch, check that it is unlocked, then try again.")
NO_3DS_FOLDER_MESSAGE = ("Not a homebrew SD card (no 3ds folder).\n"
                         "Select your 3DS SD card root or create a 3ds folder.")


CASE_CLASH_MESSAGE = ("These PC save files differ only in capital letters: %s.\n"
                      "The 3DS SD card can't hold both, so nothing was copied. Keep one of them, then try again.")


def case_clashes(save_files) -> list[str]:
    """Names that one FAT folder can't hold together, because they differ only in capitals."""
    seen = {}
    for f in save_files:
        seen.setdefault(f.name.casefold(), []).append(f.name)
    return sorted(n for names in seen.values() if len(names) > 1 for n in names)


class DeliverError(Exception):
    pass


class ExistingSavesError(DeliverError):
    """The SD card already has 3DS saves and the caller did not ask to replace them. Nothing was changed."""


class SaveCancelled(DeliverError):
    pass


def _is_readonly_path(path, platform=sys.platform):
    try:
        st = os.stat(path)
    except OSError:
        return False
    if platform == "win32" and stat.S_ISDIR(st.st_mode):
        # On Windows, FILE_ATTRIBUTE_READONLY on a folder does not block writes (Explorer sets it on customized
        # folders). Real write-protection on a drive is caught when writing.
        return False
    return (st.st_mode & stat.S_IWRITE) == 0 or not os.access(path, os.W_OK)


def check_sd_writable(sd_root, extra_paths=(), platform=sys.platform):
    """Raises DeliverError if the SD card root (on POSIX) or any target file on it is read-only."""
    for p in (sd_root, os.path.join(sd_root, "3ds")) + tuple(extra_paths):
        if os.path.exists(p) and _is_readonly_path(p, platform=platform):
            raise DeliverError(READ_ONLY_MESSAGE % sd_root)


BACKUP_MISMATCH_MESSAGE = ("The SD card didn't store a correct backup of the 3DS saves, so nothing was replaced "
                           "and the 3DS saves are as they were.\nThe card may be failing. Copy its saves folder to "
                           "this PC, then try again with another card or card reader.")


class BackupMismatch(OSError):
    """An old-save backup read back different from the live save it copies (SCOURSOL4-001)."""


def write_error(sd_root, exc: OSError) -> DeliverError:
    if isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EACCES, errno.EROFS, errno.EPERM):
        return DeliverError(READ_ONLY_MESSAGE % sd_root)
    return DeliverError("Could not write to %s (%s).\nCheck the SD card connection and free space." % (sd_root, exc))


def default_pc_save_dir(game_key: str, env=None, platform=sys.platform) -> str:
    """Where the PC game stores saves. Strictly read-only when used by the builder."""
    env = os.environ if env is None else env
    folder = products.PRODUCTS[game_key].title if game_key in products.PRODUCTS else game_key.upper()
    if platform == "win32":
        base = env.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        return os.path.join(base, folder)
    if platform == "darwin":
        return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "com.tobyfox." + game_key)
    base = env.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, folder)


def sd_save_dir(sd_root: str, product: products.Product) -> str:
    return os.path.join(sd_root, *product.sd_save_dir().split("/"))


@dataclasses.dataclass
class SaveFile:
    name: str
    path: str
    size: int
    mtime: float
    date: str
    player_name: str | None = None
    lv: int | None = None
    corrupt: bool = False
    detail: str = ""
    # The exact bytes that passed the checks above. An import writes these, never the file as it is later.
    data: bytes | None = dataclasses.field(default=None, repr=False, compare=False)
    read_error: bool = False

    @property
    def valid(self) -> bool:
        return not self.corrupt

    @property
    def mtime_text(self) -> str:
        return self.date

    @property
    def summary(self) -> str:
        return self.detail


@dataclasses.dataclass
class SaveScan:
    folder: str
    files: list
    exists: bool = False
    error: str | None = None

    @property
    def valid_files(self) -> list:
        return [f for f in self.files if not f.corrupt]

    @property
    def corrupt_files(self) -> list:
        return [f for f in self.files if f.corrupt]

    @property
    def has_corrupt(self) -> bool:
        return any(f.corrupt for f in self.files)

    @property
    def player_summary(self) -> str | None:
        by_name = {f.name.lower(): f for f in self.valid_files}
        for key in ("file0", "undertale.ini", "dr.ini", "file9", "file8"):
            f = by_name.get(key)
            if f and f.player_name:
                return "%s, LV %d" % (f.player_name, f.lv) if f.lv is not None else f.player_name
        for f in self.valid_files:
            if f.player_name:
                return "%s, LV %d" % (f.player_name, f.lv) if f.lv is not None else f.player_name
        return None


@dataclasses.dataclass
class SaveCopyResult:
    copied: int
    bytes_copied: int
    backup_dir: str | None
    files: list
    backed_up: int = 0


def _parse_lv(raw: str) -> int | None:
    try:
        v = float(raw.strip().strip('"').strip())
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    lv = int(round(v))
    if abs(v - lv) > 1e-4 or not (1 <= lv <= 99):
        return None
    return lv


def _is_printable_text(text: str) -> bool:
    return all(c.isprintable() or c in "\r\n\t" for c in text)


def _clean_player_name(raw: str) -> str | None:
    s = raw.strip()
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    if not s or len(s) > 32 or not s.isprintable():
        return None
    return s


def _parse_ini_sections(lines: list[str]) -> dict | None:
    sections = {}
    cur = None
    saw_entry = False
    for raw in lines:
        s = raw.strip()
        if not s or s.startswith((";", "#")):
            continue
        if s.startswith("[") and s.endswith("]") and len(s) > 2:
            sec = s[1:-1].strip().lower()
            if not sec:
                return None
            cur = sections.setdefault(sec, {})
            saw_entry = True
            continue
        if "=" not in s:
            return None
        k, _, v = s.partition("=")
        k = k.strip().lower()
        v = v.strip()
        if not k:
            return None
        if len(v) >= 2 and v[0] == '"' and v[-1] == '"':
            v = v[1:-1]
        if cur is None:
            cur = sections.setdefault("", {})
        cur[k] = v
        saw_entry = True
    return sections if saw_entry else None


def _resolve_folder_and_game(first, second="undertale") -> tuple[str, str]:
    if isinstance(first, products.Product):
        return (second or ""), first.key
    if isinstance(second, products.Product):
        return (first or ""), second.key
    if (isinstance(first, str) and first in products.PRODUCTS
            and isinstance(second, str) and second not in products.PRODUCTS):
        return second, first
    return (first or ""), (second or "undertale")


def inspect_save_file(path: str, game_key: str = "undertale") -> SaveFile:
    """Reads a save file (read-only) and extracts its modified date, player name and LV."""
    path, game_key = _resolve_folder_and_game(path, game_key)
    name = os.path.basename(path)
    low = name.lower()
    try:
        st = os.stat(path)
        size, mtime = st.st_size, st.st_mtime
        date = time.strftime("%Y-%m-%d %H:%M", time.localtime(mtime))
        if size == 0:
            return SaveFile(name, path, 0, mtime, date, corrupt=True, detail="Corrupt (empty save file)")
        if size > MAX_SAVE_BYTES:
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (file is too large)")
        with open(path, "rb") as f:
            raw = f.read(MAX_SAVE_BYTES + 1)
    except OSError:
        return SaveFile(name, path, 0, 0.0, "unknown", corrupt=True,
                        detail="Could not read this file. Check folder access or choose another folder.",
                        read_error=True)
    # The file can change between stat and read; describe the bytes actually read.
    size = len(raw)
    if size == 0:
        return SaveFile(name, path, 0, mtime, date, corrupt=True, detail="Corrupt (empty save file)")
    if size > MAX_SAVE_BYTES:
        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (file is too large)")
    result = _inspect_bytes(name, path, size, mtime, date, raw)
    if not result.corrupt:
        result.data = raw
    return result


def _inspect_bytes(name, path, size, mtime, date, raw) -> SaveFile:
    low = name.lower()
    if b"\x00" in raw:
        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Save format not recognized. Choose another save folder, or Skip.")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Save format not recognized. Choose another save folder, or Skip.")
    if not _is_printable_text(text) or not text.strip():
        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Save format not recognized. Choose another save folder, or Skip.")

    lines = text.splitlines()

    if re.fullmatch(r"file[0-9]", low):
        if len(lines) < 2:
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (truncated save slot)")
        pname = _clean_player_name(lines[0])
        lv = _parse_lv(lines[1])
        if pname is None or lv is None:
            return SaveFile(name, path, size, mtime, date, corrupt=True,
                            detail="Save format not recognized. Choose another save folder, or Skip.")
        for extra in lines[2:]:
            s = extra.strip()
            if not s:
                continue
            try:
                if not math.isfinite(float(s)):
                    raise ValueError
            except ValueError:
                return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid save data)")
        return SaveFile(name, path, size, mtime, date, player_name=pname, lv=lv,
                        detail="Name: %s, LV %d" % (pname, lv))

    m_ch = re.fullmatch(r"filech([0-9]+)_([0-9]+)", low)
    if m_ch:
        ch = int(m_ch.group(1))
        if len(lines) < 2:
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (truncated chapter save)")
        pname = _clean_player_name(lines[0])
        if pname is None:
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (name could not be read)")
        return SaveFile(name, path, size, mtime, date, player_name=pname, detail="Chapter %d (Name: %s)" % (ch, pname))

    if low.endswith(".ini"):
        sections = _parse_ini_sections(lines)
        if sections is None:
            if re.fullmatch(r"(?:config|keyconfig)_[0-9]+\.ini", low):
                # DELTARUNE writes keyconfig_N.ini / config_N.ini as either INI sections or one number per line.
                nums = [ln.strip() for ln in lines if ln.strip()]
                if nums:
                    try:
                        if all(math.isfinite(float(x)) for x in nums):
                            return SaveFile(name, path, size, mtime, date, detail="Settings")
                    except ValueError:
                        pass
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid INI format)")
        if low == "undertale.ini":
            gen = sections.get("general", {})
            pname = _clean_player_name(gen["name"]) if "name" in gen else None
            if "name" in gen and pname is None:
                return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid name)")
            lv_raw = gen.get("love", gen.get("level"))
            lv = _parse_lv(lv_raw) if lv_raw is not None else None
            if lv_raw is not None and lv is None:
                return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid LV)")
            det = ("Name: %s, LV %d" % (pname, lv)) if (pname and lv is not None) else (
                ("Name: %s" % pname) if pname else (("LV %d" % lv) if lv is not None else "Save metadata"))
            return SaveFile(name, path, size, mtime, date, player_name=pname, lv=lv, detail=det)
        if low == "dr.ini":
            pname, lv = None, None
            for sec_name in sorted(sections):
                sec = sections[sec_name]
                if not sec_name.startswith("g"):
                    continue
                if "name" in sec:
                    cand_name = _clean_player_name(sec["name"])
                    if cand_name is None:
                        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid name)")
                    pname = pname or cand_name
                lv_raw = sec.get("level", sec.get("love"))
                if lv_raw is not None:
                    cand_lv = _parse_lv(lv_raw)
                    if cand_lv is None:
                        return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid LV)")
                    if lv is None:
                        lv = cand_lv
            det = ("Name: %s, LV %d" % (pname, lv)) if (pname and lv is not None) else (
                ("Name: %s" % pname) if pname else "Save metadata")
            return SaveFile(name, path, size, mtime, date, player_name=pname, lv=lv, detail=det)
        return SaveFile(name, path, size, mtime, date, detail="Settings")

    if low in ("system_information_962", "system_information_963"):
        if len(text.strip()) > 64:
            return SaveFile(name, path, size, mtime, date, corrupt=True, detail="Corrupt (invalid system file)")
        return SaveFile(name, path, size, mtime, date, detail="System data")

    return SaveFile(name, path, size, mtime, date, detail="Save data")


def validated_payloads(scan: SaveScan, game_key: str) -> list:
    """(SaveFile, bytes) for each valid file: the bytes that were checked, so the import writes what the preview
    showed even if the PC file changed since. A scan made by hand without bytes is checked again here."""
    out = []
    for sf in scan.valid_files:
        data = sf.data
        if data is None:
            fresh = inspect_save_file(sf.path, game_key)
            if fresh.read_error:
                raise DeliverError("The builder could not read %s from the PC save folder. "
                                   "Check access to that folder, then try again." % sf.name)
            if fresh.corrupt:
                raise DeliverError("Can't read %s, so no saves were copied.\n"
                                   "Choose another folder or skip." % sf.name)
            data = fresh.data
        out.append((sf, data))
    return out


def _is_save_candidate(name: str, game_key: str = "undertale") -> bool:
    low = name.lower()
    if low in IGNORED_SAVE_NAMES or low.startswith(".") or low.endswith(IGNORED_SAVE_SUFFIXES):
        return False
    if game_key == "deltarune":
        return bool(re.fullmatch(r"filech[0-9]+_[0-9]+", low)
                    or low in ("dr.ini", "config.ini", "true_config.ini")
                    or re.fullmatch(r"(?:config|keyconfig)_[0-9]+\.ini", low))
    return bool(re.fullmatch(r"file[0-9]", low)
                or low in ("undertale.ini", "config.ini", "true_config.ini",
                           "system_information_962", "system_information_963"))


def scan_saves(folder, game_key="undertale") -> SaveScan:
    """Lists and inspects every save file in `folder` without writing anything."""
    folder, game_key = _resolve_folder_and_game(folder, game_key)
    if not folder:
        return SaveScan("", [], exists=False)
    try:
        if not stat.S_ISDIR(os.stat(folder).st_mode):
            return SaveScan(folder, [], exists=False)
        names = sorted(os.listdir(folder))
    except FileNotFoundError:
        return SaveScan(folder, [], exists=False)
    except OSError:
        return SaveScan(folder, [], exists=True,
                        error="The builder could not read the PC save folder %s. "
                              "Check access, choose another folder, or Skip." % folder)
    files = []
    for name in names:
        if not _is_save_candidate(name, game_key):
            continue
        p = os.path.join(folder, name)
        try:
            if not stat.S_ISREG(os.stat(p).st_mode):
                continue
        except OSError:
            pass  # Inspect it too: a listed save that cannot be read is not an empty folder.
        files.append(inspect_save_file(p, game_key))
    return SaveScan(folder, files, exists=True)


def scan_sd_saves(sd_root: str, product: products.Product) -> SaveScan:
    existing_sd_save_files(sd_root, product)  # Check containment and inventory before reading saves.
    return scan_saves(sd_save_dir(sd_root, product), product.key)


SAVE_LIST_ERROR = ("The 3DS saves folder could not be checked. "
                   "Check that the SD card can be read, then check the saves again.")


def prove_folder_absent(folder, list_names):
    """A missing-path reply alone is insufficient: a readable parent must omit the name.

    Adapters raise FileNotFoundError only for their exact missing-path result.
    Native SD and FTP callers use the same FAT case comparison and parent walk.
    """
    folder = str(folder).replace('\\', '/').rstrip('/')
    parent, _, name = folder.rpartition('/')
    if not name or ':' in name:
        return False
    parent = parent or '/'
    if parent.endswith(':'):
        parent += '/'
    try:
        names = list_names(parent)
    except FileNotFoundError:
        return prove_folder_absent(parent, list_names)
    return all(isinstance(item, str) and item and '/' not in item and '\\' not in item
               and item.casefold() != name.casefold() for item in names)


def existing_sd_save_files(sd_root: str, product: products.Product) -> list[str]:
    d = sd_save_dir(sd_root, product)
    require_sd_save_path(sd_root, d)
    out = []
    try:
        names = sorted(os.listdir(d))
    except FileNotFoundError as exc:
        try:
            if prove_folder_absent(d, os.listdir):
                return []
        except OSError:
            pass
        raise DeliverError(SAVE_LIST_ERROR) from exc
    except OSError as exc:
        raise DeliverError(SAVE_LIST_ERROR) from exc
    for name in names:
        p = os.path.join(d, name)
        require_sd_save_path(sd_root, p)
        low = name.lower()
        if low in IGNORED_SAVE_NAMES or low.startswith(".") or low.endswith((".tmp", ".part")):
            continue
        try:
            if stat.S_ISREG(os.stat(p).st_mode):
                out.append(p)
        except OSError as exc:
            raise DeliverError("The SD card saves could not all be checked. No saves were replaced. "
                               "Check the card connection, then check again.") from exc
    return out


def require_sd_save_path(sd_root, path):
    """Use the installer's containment rule, also rejecting Windows reparse points."""
    import cleanup
    import install_record
    try:
        relative = os.path.relpath(path, sd_root).replace('\\', '/')
        current = install_record.target(sd_root, relative)
        # Only the card's own folders are checked. How the computer reaches the card (/media on some Linux
        # systems, /var and /tmp on macOS are links) is the installer's resolved root, as for the game files.
        root = Path(sd_root).resolve()
        while current != root:
            try:
                if cleanup.reparse(current.lstat()):
                    raise OSError('linked save path')
            except FileNotFoundError:
                pass
            current = current.parent
    except (OSError, ValueError) as exc:
        raise DeliverError('This card has a saves path that points to another folder. '
                           'No saves were replaced. Choose a card with ordinary folders for the game and saves.') from exc


def has_existing_sd_saves(sd_root: str, product: products.Product) -> bool:
    return bool(existing_sd_save_files(sd_root, product))


def _remove_stale(path):
    if os.path.lexists(path):
        try:
            os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
        except OSError:
            pass
        os.remove(path)


def _copy_file(src, dst):
    """Copies the bytes and the modified time, flushed to the card. Unlike shutil.copy2 it never carries a read-only
    bit over: a read-only save on the SD card would block the 3DS game's own saves and every later import."""
    _remove_stale(dst)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
        fo.flush()
        os.fsync(fo.fileno())
    st = os.stat(src)
    os.utime(dst, (st.st_atime, st.st_mtime))


def _same_bytes(a, b):
    """True when both files hold the same bytes, read back from the card."""
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            block = fa.read(1 << 16)
            if block != fb.read(len(block) or 1):
                return False
            if not block:
                return True


def _write_checked(dst, data, mtime):
    """Writes the checked bytes, flushed to the card, then reads the copy back: the staged file must be exactly
    the bytes that passed the checks. Never carries a read-only bit (see _copy_file)."""
    _remove_stale(dst)
    with open(dst, "wb") as fo:
        fo.write(data)
        fo.flush()
        os.fsync(fo.fileno())
    os.utime(dst, (mtime, mtime))
    with open(dst, "rb") as fi:
        if fi.read(len(data) + 1) != data:
            raise OSError(errno.EIO, "the copy on the SD card does not match the PC save", dst)


def _unique_backup_dir(dst_dir: str, now=None) -> str:
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now) if isinstance(now, (int, float)) else (
        now if isinstance(now, time.struct_time) else time.localtime()))
    base = os.path.join(dst_dir, "backup-" + stamp)
    cand = base
    n = 2
    while os.path.exists(cand):
        cand = "%s-%d" % (base, n)
        n += 1
    return cand


def copy_pc_saves(sd_root: str, product: products.Product, pc_scan_or_folder, overwrite: bool = False,
                  now=None, *, progress=lambda phase, done, total, name: None,
                  cancelled=lambda: False) -> SaveCopyResult:
    """Copies verified PC saves to sd:/<sd_data_dir>/saves/, backing up any existing 3DS saves first."""
    if not os.path.isdir(os.path.join(sd_root, "3ds")):
        raise DeliverError(NO_3DS_FOLDER_MESSAGE)
    pc_scan = (scan_saves(pc_scan_or_folder, product.key)
               if isinstance(pc_scan_or_folder, str) else pc_scan_or_folder)
    if pc_scan.error:
        raise DeliverError(pc_scan.error)
    unreadable = [sf.name for sf in pc_scan.files if sf.read_error]
    if unreadable:
        raise DeliverError("The builder could not read %s from the PC save folder. "
                           "Check access to that folder, then try again." % ", ".join(unreadable))
    if pc_scan.has_corrupt:
        bad = ", ".join(f.name for f in pc_scan.corrupt_files)
        raise DeliverError("Can't read %s, so no saves were copied.\n"
                           "Choose another folder or skip." % bad)
    if not pc_scan.valid_files:
        raise DeliverError("No PC save files were found in %s.\n"
                           "Choose another folder or skip save import." % pc_scan.folder)
    clash = case_clashes(pc_scan.valid_files)
    if clash:
        raise DeliverError(CASE_CLASH_MESSAGE % ", ".join(clash))
    payloads = validated_payloads(pc_scan, product.key)

    dst_dir = sd_save_dir(sd_root, product)
    existing = existing_sd_save_files(sd_root, product)
    if existing and not overwrite:
        sd_scan = scan_sd_saves(sd_root, product)
        who = sd_scan.player_summary or ", ".join(os.path.basename(p) for p in existing)
        raise ExistingSavesError("Existing 3DS saves were found in %s (%s).\n"
                                 "Nothing was copied." % (dst_dir, who))

    target_paths = ([dst_dir] + existing + [os.path.join(dst_dir, f.name) for f in pc_scan.valid_files])
    target_paths += [os.path.join(dst_dir, f.name) + '.part' for f in pc_scan.valid_files]
    for path in target_paths:
        require_sd_save_path(sd_root, path)
    checker = getattr(sys.modules.get("deliver"), "check_sd_writable", check_sd_writable)
    checker(sd_root, target_paths)

    need = sum(len(data) for _, data in payloads)
    if existing:
        try:
            need += sum(os.path.getsize(p) for p in existing)
        except OSError:
            pass
    free = shutil.disk_usage(sd_root).free
    if need > free:
        need_mb = max(1, -(-need // 10**6))
        raise DeliverError("This card has %d MB free; %d MB needed.\n"
                           "Free up space on the SD card and try again." % (free // 10**6, need_mb))

    backup_dir = None
    staged = []
    changing = False
    bytes_copied = 0
    done = 0
    def tick(phase, name='', count=0):
        nonlocal done
        if cancelled():
            raise SaveCancelled('Copy cancelled. The 3DS saves were not replaced.')
        done += count
        progress(phase, done, need, name)
    try:
        tick('Checking saves')
        require_sd_save_path(sd_root, dst_dir)
        os.makedirs(dst_dir, exist_ok=True)
        if existing:
            backup_dir = _unique_backup_dir(dst_dir, now=now)
            require_sd_save_path(sd_root, backup_dir)
            os.makedirs(backup_dir, exist_ok=True)
            for old_path in existing:
                tick('Backing up 3DS saves', os.path.basename(old_path))
                b_dst = os.path.join(backup_dir, os.path.basename(old_path))
                b_tmp = b_dst + ".part"
                for path in (old_path, b_tmp, b_dst):
                    require_sd_save_path(sd_root, path)
                _copy_file(old_path, b_tmp)
                # Read the backup back before any live save is replaced: it may be the only copy left (SCOURSOL4-001).
                if not _same_bytes(old_path, b_tmp):
                    raise BackupMismatch(errno.EIO, "the backup does not match the 3DS save", b_tmp)
                os.replace(b_tmp, b_dst)
                if not _same_bytes(old_path, b_dst):
                    raise BackupMismatch(errno.EIO, "the backup does not match the 3DS save", b_dst)
                tick('Backing up 3DS saves', os.path.basename(old_path), os.path.getsize(b_dst))

        # Stage every incoming file before replacing any, so a failed copy (card pulled, card full) leaves the 3DS
        # saves exactly as they were instead of a mix of PC and 3DS files.
        incoming_names = {f.name.lower() for f in pc_scan.valid_files}
        for sf, data in payloads:
            tick('Copying PC saves', sf.name)
            tmp = os.path.join(dst_dir, sf.name) + ".part"
            require_sd_save_path(sd_root, tmp)
            staged.append(tmp)
            _write_checked(tmp, data, sf.mtime)
            tick('Checking PC saves', sf.name, len(data))

        tick('Finishing the copy')  # Cancel is safe until publishing starts, as on the Wi-Fi path.
        # Recheck the whole live inventory before publication; an unreadable card
        # or a new link must not turn a previous preview into permission to replace.
        if existing_sd_save_files(sd_root, product) != existing:
            raise DeliverError('The 3DS saves changed while copying. No saves were replaced. Check them again.')
        changing = True
        for (sf, data), tmp in zip(payloads, staged):
            require_sd_save_path(sd_root, tmp)
            require_sd_save_path(sd_root, os.path.join(dst_dir, sf.name))
            os.replace(tmp, os.path.join(dst_dir, sf.name))
            bytes_copied += len(data)

        if existing:
            for old_path in existing:
                if os.path.basename(old_path).lower() not in incoming_names and os.path.exists(old_path):
                    require_sd_save_path(sd_root, old_path)
                    os.remove(old_path)
    except (OSError, SaveCancelled) as e:
        for tmp in staged:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
        if isinstance(e, SaveCancelled):
            if backup_dir:
                shutil.rmtree(backup_dir, ignore_errors=True)
            raise
        if isinstance(e, BackupMismatch) and not changing:
            # Nothing live was touched. A backup that can't be trusted is removed so nobody restores from it.
            shutil.rmtree(backup_dir, ignore_errors=True)
            raise DeliverError(BACKUP_MISMATCH_MESSAGE) from e
        err = write_error(sd_root, e)
        if changing:
            message = ("Save copying stopped before it finished. Do not start the game yet. Reconnect the SD card "
                       "and copy the same PC saves again to finish.")
            if backup_dir:
                message += " Your previous 3DS saves are backed up in %s." % backup_dir
            err = DeliverError(message + "\nReason: " + str(e))
        raise err from e

    return SaveCopyResult(copied=len(pc_scan.valid_files), bytes_copied=bytes_copied, backup_dir=backup_dir,
                          files=[f.name for f in pc_scan.valid_files], backed_up=len(existing))
