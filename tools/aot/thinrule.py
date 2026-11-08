"""Whole rows for shrunken fine sprites (change thinrule, first update): per texture page item, the texel rows and columns
that hold bright detail their neighbours lack, and the neighbour that gives such a row its sample when a shrink would
skip it.

Usage: py -3 -I tools/aot/thinrule.py <data.win> [--out <file>] [--items N,N,...] [--min N]
       (build.sh writes the table through tools/aot/fontverdict.py's build mode, beside the item verdicts.)

Smart smoothing draws a fine sprite between 2/3 and 1 surface pixel a texel, neither axis above 1, sharp and nearest
(ctr_renderer.c, "Whole rows"), but only the items this table lists: fine items (the item verdicts' ITEM_FINE, or 0 =
decided on the console) 8 to 96 texels a side (itemverdict.in_range), less KEEP_BLUR_SPRITES. Any other draw keeps
today's blur.
Below 1 px a texel a row gets at most one sample, so a row one texel thick is skipped whenever no pixel centre falls in
it: Madjick's white hem blinks out as he breathes. Above 2/3 px skipped rows are at least 3 apart, so a skipped row's
neighbours are always drawn; the console gives a listed row its donor's pixel on the frames that would skip it, and
the donor (the neighbour with less of that detail) is what goes instead.

A row counts a texel when its premultiplied luminance is above both vertical neighbours' by more than BRIGHT (texels
beyond the item count as clear); it is listed when that count is at least --min and at least twice its lesser
neighbour's plus one. Columns the same way. Decoded colours (fontverdict.decode_page), so the rows are the same for
every store's packing of the same art.

Output file (little-endian): magic b"DTTR", u32 version 2, u32 data.win size, u32 GEN8 game ID, u64 GEN8 timestamp
(CtrPackKey, as the .dtiv), u32 entry count, u32 rescue byte count, u32 CRC-32 (zlib's) of the 32 bytes before it and
everything after it (the console uses no table that fails it); then the entries, 4 bytes each, by page, then
source y, then source x (the console's order): u16 item, u16 offset of its rescues (0xFFFF: none); then the rescue
bytes, per item u8 rows, u8 columns, its rows, its columns: bits 0-6 the row or column, bit 7 set when the donor is the
next one (else the one before).

Pure Python (the builder ships the embeddable Python, without numpy). Reads the game data; run with -I. Writes nothing
derived from the game into the repository: --out is a build output.
"""
import argparse
import concurrent.futures as cf
import os
import struct
import sys
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # -I leaves the script's folder off the path
import fontverdict as fv  # noqa: E402
import itemverdict as iv  # noqa: E402

MAGIC = b"DTTR"
VERSION = 2
HEADER = 36
NONE = 0xFFFF
BRIGHT = 64     # how much brighter than both neighbours a texel must be to count (premultiplied luminance, 0-255)
MIN_COUNT = 8   # texels a row must count to be listed
# Sprites whose in-range draws keep today's linear filtering (the before/after sheet found them worse sharp), by the
# SHA-1 of the sprite's name, as itemverdict.py names sprites: left out of the table.
KEEP_BLUR_SPRITES = (
    "f9e1387023e8618c75f407fa9887693314e71f3b",  # Glyde's wings (battle group 135): sharp, the shrink drops the
    "173561b641d1886d068fc7ed4713904cead4b21a",  # one-texel gaps between stripes and dots the outline; both wings blur
    # Asgore's fire (its orange particle sprite): sharp changes a few edge pixels, but each sharp flame ends the run of fine
    # draws held as one (asgdraw), 0.16 ms more drawing a frame on the Old 3DS.
    "ab3cbbc7d7ef63f0643946d1d086942fedb7f944",
)


def luminance(px):
    r, g, b, a = px
    return (a * (r * 299 + g * 587 + b * 114) // 1000) // 255 if a else 0


def counts(lum, w, h, rows):
    """Per row (rows) or column: texels brighter than both neighbours across it by more than BRIGHT."""
    out = []
    for r in range(h if rows else w):
        c = 0
        for k in range(w if rows else h):
            if rows:
                v, a, b = lum[r][k], lum[r - 1][k] if r else 0, lum[r + 1][k] if r + 1 < h else 0
            else:
                v, a, b = lum[k][r], lum[k][r - 1] if r else 0, lum[k][r + 1] if r + 1 < w else 0
            if v > max(a, b) + BRIGHT:
                c += 1
        out.append(c)
    return out


def rescues(u, minimum):
    """The listed rows of one axis as rescue bytes: the row, and bit 7 when its donor is the next row."""
    out = []
    n = len(u)
    for r in range(n):
        nb = ([(u[r - 1], 0, r - 1)] if r else []) + ([(u[r + 1], 1, r + 1)] if r + 1 < n else [])
        if not nb or u[r] < minimum:
            continue
        lo = min(nb)
        if u[r] >= 2 * lo[0] + 1:
            out.append(r | (0x80 if lo[1] else 0))
    return out


def item_rescues(page, item, minimum):
    x0, y0, w, h = item["sx"], item["sy"], item["sw"], item["sh"]
    lum = [[luminance(page.px(x0 + x, y0 + y)) for x in range(w)] for y in range(h)]
    return rescues(counts(lum, w, h, True), minimum), rescues(counts(lum, w, h, False), minimum)


def page_job(path, page_id, off, size, look, minimum):
    with open(path, "rb") as f:
        f.seek(off)
        blob = f.read(size)
    dims = iv.page_dims(blob)
    dec = fv.decode_page(blob, dims[1]) if dims else None
    if dec is None:
        return page_id, []
    page = fv.Page(dec[0], dec[1], dec[2], dec[1])
    out = []
    for i, item in look:
        rows, cols = item_rescues(page, item, minimum)
        if rows or cols:
            out.append((i, rows, cols))
    return page_id, out


def fine_items(table):
    """The items an item verdict table (itemverdict.analyse's 10-byte entries) leaves fine, or to the console (0)."""
    out = set()
    for i, e in enumerate(table):
        if (e[0] == 0 and e[5] == 0) or (e[0] | e[5]) & iv.ITEM_FINE:
            out.add(i)
    return out


def item_verdicts(path, jobs=None):
    """UNDERTALE's item verdict table as the .dtiv holds it (GOG's profile applied, as itemverdict.write does)."""
    win, table, _ = iv.analyse(path, quiet=True, jobs=jobs, game="undertale")
    if win.gog_smart:
        import gog_smart
        table, _ = gog_smart.item_overrides(win, table)
    return table


def analyse(path, minimum=MIN_COUNT, only=None, jobs=None, fine=None):
    """(win, [(item, rows, columns)]) for the in-range items in fine (all in range when None), less KEEP_BLUR_SPRITES,
    in the console's order (page, source y, source x)."""
    win = fv.Win(path)
    blobs = fv.texture_blobs(win)
    ptrs, items = iv.tpag_items(win)
    keep = set(iv.sprite_frames(win, ptrs, KEEP_BLUR_SPRITES)) if KEEP_BLUR_SPRITES else set()
    by_page = {}
    for i, it in enumerate(items):
        if it is None or it["page"] < 0 or it["page"] >= len(blobs) or not iv.in_range(it) or i in keep:
            continue
        if (only is not None and i not in only) or (fine is not None and i not in fine):
            continue
        by_page.setdefault(it["page"], []).append((i, it))
    found = {}
    jobs = jobs or iv.default_jobs()
    work = [(path, p, blobs[p][0], blobs[p][1], look, minimum) for p, look in sorted(by_page.items())]
    if jobs <= 1 or len(work) <= 1:
        results = [page_job(*w) for w in work]
    else:
        try:
            with cf.ProcessPoolExecutor(min(jobs, len(work))) as ex:
                results = list(ex.map(page_job, *zip(*work)))
        except (ImportError, OSError, RuntimeError):
            results = [page_job(*w) for w in work]
    for _, out in results:
        for i, rows, cols in out:
            found[i] = (rows, cols)
    listed = [i for look in by_page.values() for i, _ in look]
    listed.sort(key=lambda i: (items[i]["page"], items[i]["sy"], items[i]["sx"], i))
    return win, [(i,) + found.get(i, ([], [])) for i in listed]


def write(path, win, table):
    entries, data = bytearray(), bytearray()
    for i, rows, cols in table:
        if i > 0xFFFF or len(rows) > 255 or len(cols) > 255 or len(data) >= NONE:
            raise SystemExit(f"thinrule: item {i} doesn't fit the table")
        if rows or cols:
            entries += struct.pack("<HH", i, len(data))
            data += bytes([len(rows), len(cols)]) + bytes(rows) + bytes(cols)
        else:
            entries += struct.pack("<HH", i, NONE)
    head = MAGIC + struct.pack("<IIIQII", VERSION, win.size, win.game_id, win.timestamp, len(table), len(data))
    payload = bytes(entries + data)
    out = head + struct.pack("<I", zlib.crc32(head + payload)) + payload
    with open(path, "wb") as f:
        f.write(out)
    return len(out)


def check(blob):
    """Whether a table file passes the console's checks short of the data.win key: magic, version, sizes, CRC-32."""
    if len(blob) < HEADER or blob[:4] != MAGIC:
        return False
    version, count, size, crc = struct.unpack_from("<I", blob, 4)[0], *struct.unpack_from("<III", blob, 24)
    return (version == VERSION and 0 < count < 0x10000 and size < 0x10000 and len(blob) == HEADER + 4 * count + size
            and zlib.crc32(blob[:32] + blob[HEADER:]) == crc)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("data_win")
    ap.add_argument("--out")
    ap.add_argument("--items", help="only these TPAG indices (comma separated), for checks")
    ap.add_argument("--min", type=int, default=MIN_COUNT, help=f"texels a row must count (default {MIN_COUNT})")
    ap.add_argument("--jobs", type=int)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--all", action="store_true", help="every in-range item, not only the fine ones (checks)")
    args = ap.parse_args()
    only = {int(x) for x in args.items.split(",")} if args.items else None
    t0 = time.time()
    fine = None
    if not args.all:
        fine = fine_items(item_verdicts(args.data_win, args.jobs))
    win, table = analyse(args.data_win, args.min, only, args.jobs, fine)
    size = write(args.out, win, table) if args.out else None
    if not args.quiet:
        if only is not None:
            for i, rows, cols in table:
                print(i, "rows", [(r & 0x7F, (r & 0x7F) + (1 if r & 0x80 else -1)) for r in rows],
                      "columns", [(c & 0x7F, (c & 0x7F) + (1 if c & 0x80 else -1)) for c in cols])
        print(f"thinrule: {len(table)} items ({sum(1 for t in table if t[1] or t[2])} with rescues), "
              f"{sum(len(t[1]) + len(t[2]) for t in table)} rescues"
              + (f", {size} B" if size is not None else "") + f" in {time.time() - t0:.1f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
