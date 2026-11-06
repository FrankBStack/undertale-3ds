"""Private, GPU-ready Smart artwork, derived only from the builder's own data.win.

No pixels are source assets. Unsupported/missing input removes stale output. A full
hash is computed on every invocation, including a font-table cache hit.
"""
import hashlib
from pathlib import Path
import struct
import zlib

MAGIC = b'DTTA'
HEADER = struct.Struct('<4sHHIIIIQ64sI6HBB4sHII')
SUPPORTED = frozenset((
    'b718f8223a5bb31979ffeed10be6140c857b882fc0d0462b89d6287ae38c81c7',
    '946c738c6d6182f683431320a0e32470bc3deb50f3e8887e61998df0c4e3abc8',
))
SPRITE = ('d63f002f4800de4cd9ab670f6806151f221343a1',)


def morton(x, y):
    return ((y >> 3) * 32 * 64 + (x >> 3) * 64 + (x & 1) +
            ((y & 1) << 1) + ((x & 2) << 1) + ((y & 2) << 2) +
            ((x & 4) << 2) + ((y & 4) << 3))


def compress(src):
    """Greedy byte-oriented CtrLz stream; no third-party codec dependency."""
    def length(n):
        return bytes([255]) * (n // 255) + bytes([n % 255])
    out, last = bytearray(), {}
    pos = anchor = 0
    n = len(src)
    while pos <= n - 8:
        key = bytes(src[pos:pos + 8])
        cand = last.get(key)
        last[key] = pos
        if cand is None or pos - cand > 65535:
            pos += 1
            continue
        size = 8
        while pos + size < n and src[cand + size] == src[pos + size]:
            size += 1
        lit, match = pos - anchor, size - 4
        out.append((min(lit, 15) << 4) | min(match, 15))
        if lit >= 15:
            out += length(lit - 15)
        out += src[anchor:pos]
        out += struct.pack('<H', pos - cand)
        if match >= 15:
            out += length(match - 15)
        end = pos + size
        for p in range(max(pos + 1, end - 4), min(end, n - 7)):
            last[bytes(src[p:p + 8])] = p
        pos = anchor = end
    if anchor < n:
        lit = n - anchor
        out.append(min(lit, 15) << 4)
        if lit >= 15:
            out += length(lit - 15)
        out += src[anchor:]
    return bytes(out)


def texels(win):
    import fontverdict as fv
    import itemverdict as iv
    ptrs, items = iv.tpag_items(win)
    ids = iv.sprite_frames(win, ptrs, SPRITE)
    if len(ids) != 1:
        raise ValueError('inkart: unsupported frame mapping')
    index, = ids
    item = items[index]
    if (item['sw'], item['sh']) != (251, 172):
        raise ValueError('inkart: unsupported dimensions')
    off, size = fv.texture_blobs(win)[item['page']]
    w, h, rgba = fv.decode_page(win.d[off:off + size], 100000)
    page = fv.Page(w, h, rgba, h)
    modes = []
    for exact in (False, True):
        out = bytearray(65536)
        for y in range(item['sh']):
            for x in range(item['sw']):
                fmt, value = page.stored(exact, item['sx'] + x, item['sy'] + y)
                v = fv.decoded_rgba(fmt, value)
                if v & 255 == 0:
                    v = 0
                if v not in (0, 255, 0xffffffff):
                    raise ValueError('inkart: texel cannot be represented exactly')
                out[morton(x + 1, y + 1)] = 255 if v == 0xffffffff else 15 if v == 255 else 0
        modes.append(bytes(out))
    if modes[0] != modes[1]:
        raise ValueError('inkart: colour modes differ')
    return index, item, modes[0]


def build(game, data, romfs):
    """Always hash; never accept an output solely because size/mtime match."""
    import data_versions
    import fontverdict as fv
    dest = Path(romfs) / 'fonts' / 'undertale.dtta'
    temp = dest.with_suffix('.dtta.part')
    # Delete before reading inputs: a failed/unsupported invocation cannot reuse art.
    dest.unlink(missing_ok=True)
    temp.unlink(missing_ok=True)
    if game != 'undertale' or not data or not Path(data, 'data.win').is_file():
        return None
    path = Path(data, 'data.win')
    revision, known = data_versions.load_table()
    good, _, digest = data_versions.check_file(path, game, 'root', revision, known, {})
    if not good or digest not in SUPPORTED:
        print('inkart: unsupported input; stock art')
        return None
    win = fv.Win(str(path))
    # Detect replacement between hashing and derivation; derivation uses these bytes.
    if hashlib.sha256(win.d).hexdigest() != digest:
        raise ValueError('inkart: data changed during build')
    index, item, atlas = texels(win)
    payload = compress(atlas)
    header = HEADER.pack(MAGIC, 1, HEADER.size, HEADER.size + len(payload), len(payload),
                         win.size, win.game_id, win.timestamp, digest.encode('ascii'), index,
                         item['sx'], item['sy'], item['sw'], item['sh'], 256, 256,
                         9, 3, bytes((0, 0, 251, 172)), 0, zlib.crc32(payload), 0)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(header + payload)
    temp.replace(dest)
    print(f'inkart: {HEADER.size + len(payload)} B package; 65536 B LA4; full SHA-256 checked')
    return index
