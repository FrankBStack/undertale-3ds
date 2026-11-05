"""Shared size/SHA-256 allowlist check. No game bytes are stored or uploaded."""
import hashlib
import json
from pathlib import Path
import re

TABLE = Path(__file__).resolve().parents[2] / "platform/3ds/data_versions.inc"


def load_table():
    text = TABLE.read_text(encoding="utf-8")
    revision = int(re.search(r"^#define DATA_VERSIONS_REVISION (\d+)$", text, re.M).group(1))
    rows = re.findall(r'DATA_VERSION\("([^"]+)", "([^"]+)", (\d+)ULL, "([0-9a-f]{64})"\)', text)
    return revision, {(game, part, int(size), digest) for game, part, size, digest in rows}


def check_file(path, game, part, revision, known, cache):
    path = Path(path)
    stat = path.stat()
    key = str(path.resolve())
    identity = [revision, stat.st_size, stat.st_mtime_ns]
    previous = cache.get(key, {})
    digest = previous.get("sha256", "") if isinstance(previous, dict) else ""
    cached = isinstance(previous, dict) and previous.get("identity") == identity and re.fullmatch(r"[0-9a-f]{64}", digest) is not None
    if not cached:
        sha = hashlib.sha256()
        with path.open("rb") as data:
            for block in iter(lambda: data.read(1024 * 1024), b""):
                sha.update(block)
        after = path.stat()
        if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise OSError("file changed while checking")
        digest = sha.hexdigest()
        cache[key] = {"identity": identity, "sha256": digest}
    return (game, part, stat.st_size, digest) in known, cached, digest


def check_folder(game, folder, cache_folder):
    revision, known = load_table()
    cache_file = Path(cache_folder) / "data_versions.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(cache, dict): cache = {}
    except (OSError, ValueError):
        cache = {}
    files = [("root", Path(folder) / "data.win")]
    if game == "deltarune":
        files += [(f"chapter{i}_windows", Path(folder) / f"chapter{i}_windows/data.win") for i in range(1, 6)]
    for part, path in files:
        # A build may intentionally use a subset of the chapters.
        if not path.exists(): continue
        try:
            good, cached, digest = check_file(path, game, part, revision, known, cache)
            if good:
                print(f"Data version: {game}/{part} known (table {revision}, {'cached' if cached else 'hashed'})")
            else:
                print(f"WARNING: Unknown data.win: {path} (SHA-256 {digest}). This file version has not been checked. "
                      "It may work; continuing is allowed. If it fails, verify your PC game files and copy data.win again.")
        except OSError as error:
            print(f"WARNING: Could not verify data.win: {path}: {error}. Continuing is allowed.")
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # Optional cache; the next build hashes again if it could not be saved.


# datarefuse (playblocker #8, maintainer 11-04: "we shouldnt accept modified game files, it should work with the steam and
# gog copies"): build.sh's gate for UNDERTALE. A data.win that isn't one of the table's UNDERTALE rows (Steam, its
# macOS file, GOG) stops the build. A known one gives its size, which build.sh passes to CMake (CTRPORT_DATA_SIZE):
# the 3DS build then knows only that row, so the console refuses any other data.win, another known copy included
# (the RomFS tables, offkill's object numbers among them, are made from this file).
BUILD_INPUT_REFUSED = 2
BUILD_INPUT_NO_DATA = 3


def build_input(game, data, cache_folder, out=None, err=None):
    """(exit code, size or None) for build.sh: 0 known, 2 refused (message on err), 3 no data folder found."""
    import sys
    out = out or sys.stdout
    err = err or sys.stderr
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import prepare  # prepare imports this module; import it only here
    folder = prepare.find_data(game, data)
    if not folder:
        return BUILD_INPUT_NO_DATA, None
    path = Path(folder) / "data.win"
    revision, known = load_table()
    cache_file = Path(cache_folder) / "data_versions.json"
    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        if not isinstance(cache, dict): cache = {}
    except (OSError, ValueError):
        cache = {}
    # Always a full hash (under a second on a PC), never the saved cache: its size/date match would let through a
    # same-size edit that kept the file's date. The fresh result still goes into the saved cache for check_folder.
    fresh = {}
    try:
        good, _, digest = check_file(path, game, "root", revision, known, fresh)
    except OSError as error:
        print(f"Refusing to build: could not read {path} ({error}).\n"
              "Check that the game folder is readable, verify the game files in Steam or GOG Galaxy, "
              "then build again.", file=err)
        return BUILD_INPUT_REFUSED, None
    cache.update(fresh)
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
    except OSError:
        pass  # Optional cache, as in check_folder.
    if not good:
        print(f"Refusing to build: {path} is not an unmodified Steam or GOG copy of {game.upper()} "
              f"(SHA-256 {digest}).\n"
              "Modified or translated game files aren't supported. Verify the game files in Steam or GOG Galaxy "
              "(or reinstall the game), then build again.", file=err)
        return BUILD_INPUT_REFUSED, None
    # The size of the row the hashed bytes matched, not a later stat of a file that may have changed since.
    size = next(row[2] for row in known if row[:2] == (game, "root") and row[3] == digest)
    print(f"Data version: {game}/root known (table {revision}, hashed); "
          f"verified build input: {size} bytes; other data.win files are unsupported", file=err)
    print(size, file=out)
    return 0, size


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="build.sh's data.win gate (prints the build input's size)")
    parser.add_argument("--build-input", choices=["undertale"], required=True)
    parser.add_argument("--data")
    parser.add_argument("--cache", required=True)
    args = parser.parse_args()
    raise SystemExit(build_input(args.build_input, args.data, args.cache)[0])
