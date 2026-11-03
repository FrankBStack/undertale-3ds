"""Typed region priorities (gmlaot.py --typed-priority): the order DELTARUNE New's chapter modules keep typed regions in.

A chapter module is bigger than its region, so the module linker leaves the last typed files out
(platform/3ds/aot/aot_module_link.cmake). Without a priority list the files go loops first, by function rank. That
rank says how much a whole function was worth to compile, not what one region saves: a region that never runs in
play can keep out one that runs every frame. The list orders the regions by the time each saved in our own
playthroughs (typed-stats span times: generated code minus typed code), best first.

The file holds code entry names and region start addresses only, no bytecode, no game text and no hashes, one section
per chapter folder:

    # comment
    [chapter4_windows]
    <code entry name> 05F0

A section is used only when the chapter's data.win has the SHA-256 that MADE_FROM below records for that list and
folder (the data the list was measured on), so another version of the game, or a section with no recorded version,
falls back to rank order rather than to a list made for different code.

Listed regions come first, in list order; the rest follow in rank order as before. A listed region that the build
doesn't make (its rules refused it) is skipped.
"""
import hashlib
import os
import re

# {list file name: {chapter folder: SHA-256 of the data.win that section was measured on}}. The hashes gate the lists;
# they live here so that the lists in tools/aot/selection stay names-only.
MADE_FROM = {
    "typed-priority-deltarune-n3ds.txt": {
        # DELTARUNE (Steam) chapter3_windows/data.win: the Knight scenes' tyv runs of 2026-10-29.
        "chapter3_windows": "c1a0925343694ec9b9adcbf2f916a720b02fd1b999286cfe8fe6a52f3320f714",
    },
}

_SECTION = re.compile(r"\[(\S+)\]$")
_REGION = re.compile(r"(\S+)\s+([0-9A-Fa-f]{1,8})$")


def load(path):
    """{chapter folder: [(code entry, region start), ...]}; raises ValueError on a bad line."""
    out = {}
    cur = None
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = _SECTION.match(line)
            if m:
                if m.group(1) in out:
                    raise ValueError("%s:%d: section %s again" % (path, n, m.group(1)))
                cur = out[m.group(1)] = []
                continue
            m = _REGION.match(line)
            if m is None or cur is None:
                raise ValueError("%s:%d: not a section or a region: %r" % (path, n, line))
            cur.append((m.group(1), int(m.group(2), 16)))
    return out


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def order(path, folder, data_win, report, made_from=None):
    """{(code entry, region start): place} for folder's section of path, or {} when it has none, MADE_FROM (or
    made_from, same shape) records no data version for it, or the data.win's SHA-256 differs. Adds a line to report
    either way."""
    sections = load(path)
    if folder not in sections:
        report.append("typed priority: no section for %s; rank order" % folder)
        return {}
    regions = sections[folder]
    sha = (MADE_FROM if made_from is None else made_from).get(os.path.basename(path), {}).get(folder)
    if sha is None:
        report.append("typed priority: no data version recorded for %s's section; rank order" % folder)
        return {}
    if file_sha256(data_win) != sha:
        report.append("typed priority: %s's data.win is not the one the list was made from; rank order" % folder)
        return {}
    report.append("typed priority: %s: %d regions listed" % (folder, len(regions)))
    return {r: i for i, r in enumerate(regions)}


def merged(path, games, report, made_from=None):
    """{(folder, code entry, region start): place} over every (folder, data.win) of a run: a chapter run compiles the
    chapter's data.win and the launcher's, and each applies its own section (the launcher's has none)."""
    out = {}
    for folder, data_win in games:
        for (entry, start), place in order(path, folder, data_win, report, made_from).items():
            out[(folder, entry, start)] = place
    return out


def write(path, sections, header=()):
    """Writes {folder: [(code entry, start), ...]} in the format load reads (folders in sorted order). Record each
    folder's data.win SHA-256 in MADE_FROM under the list's file name."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in header:
            f.write("# %s\n" % line if line else "#\n")
        for folder in sorted(sections):
            f.write("[%s]\n" % folder)
            for entry, start in sections[folder]:
                f.write("%s %04X\n" % (entry, start))
