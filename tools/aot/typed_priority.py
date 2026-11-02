"""Typed region priorities (gmlaot.py --typed-priority): the order DELTARUNE New's chapter modules keep typed regions in.

A chapter module is bigger than its region, so the module linker leaves the last typed files out
(platform/3ds/aot/aot_module_link.cmake). Without a priority list the files go loops first, by function rank. That
rank says how much a whole function was worth to compile, not what one region saves: a region that never runs in
play can keep out one that runs every frame. The list orders the regions by the time each saved in our own
playthroughs (typed-stats span times: generated code minus typed code), best first.

The file holds code entry names and region start addresses only, no bytecode and no game text, one section per
chapter folder. A section is used only when the chapter's data.win has the SHA-256 the section names, so another
version of the game falls back to rank order rather than to a list made for different code:

    # comment
    [chapter4_windows] <sha256 of chapter4_windows/data.win>
    <code entry name> 05F0

Listed regions come first, in list order; the rest follow in rank order as before. A listed region that the build
doesn't make (its rules refused it) is skipped.
"""
import hashlib
import re

_SECTION = re.compile(r"\[(\S+)\]\s+([0-9a-f]{64})$")
_REGION = re.compile(r"(\S+)\s+([0-9A-Fa-f]{1,8})$")


def load(path):
    """{chapter folder: (data.win SHA-256, [(code entry, region start), ...])}; raises ValueError on a bad line."""
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
                cur = out[m.group(1)] = (m.group(2), [])
                continue
            m = _REGION.match(line)
            if m is None or cur is None:
                raise ValueError("%s:%d: not a section or a region: %r" % (path, n, line))
            cur[1].append((m.group(1), int(m.group(2), 16)))
    return out


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def order(path, folder, data_win, report):
    """{(code entry, region start): place} for folder's section of path, or {} when it has none or the data.win's
    SHA-256 differs. Adds a line to report either way."""
    sections = load(path)
    if folder not in sections:
        report.append("typed priority: no section for %s; rank order" % folder)
        return {}
    sha, regions = sections[folder]
    if file_sha256(data_win) != sha:
        report.append("typed priority: %s's data.win is not the one the list was made from; rank order" % folder)
        return {}
    report.append("typed priority: %s: %d regions listed" % (folder, len(regions)))
    return {r: i for i, r in enumerate(regions)}


def merged(path, games, report):
    """{(folder, code entry, region start): place} over every (folder, data.win) of a run: a chapter run compiles the
    chapter's data.win and the launcher's, and each applies its own section (the launcher's has none)."""
    out = {}
    for folder, data_win in games:
        for (entry, start), place in order(path, folder, data_win, report).items():
            out[(folder, entry, start)] = place
    return out


def write(path, sections, header=()):
    """Writes {folder: (sha, [(code entry, start), ...])} in the format load reads (folders in sorted order)."""
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for line in header:
            f.write("# %s\n" % line if line else "#\n")
        for folder in sorted(sections):
            sha, regions = sections[folder]
            f.write("[%s] %s\n" % (folder, sha))
            for entry, start in regions:
                f.write("%s %04X\n" % (entry, start))
