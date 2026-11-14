"""The frozen release source the game-over tests compare against (commit ecbcd6e1a), as committed excerpts.

test_gameoverscreen_handover (BASE) and test_gameoverscreen_nooptions (FREEZE) used to read it with
`git show ecbcd6e1a:platform/3ds/source/<name>`. That commit is private, so a public clone failed with git exit 128.
fixtures/gameover_ecbcd6e1a/<name>.excerpt now holds exactly the parts they take: the function bodies (body())
and the main.c spans, cut from that commit by excerpt() below. Our own source text, never game data.

frozen(name) checks each file against SHA256 below in every clone. Where the commit is present,
test_gameoverscreen_frozen re-cuts every file from git show and requires the same bytes, and every body() or span the
tests take to come out the same from the excerpt as from the whole file.
"""
import hashlib
from pathlib import Path

from gameoverscreen_host_fixture import body

FREEZE = 'ecbcd6e1a4590f085a11dfd72286d22c9b096913'
# One literal segment: import_closure treats any expression ending in .../fixtures as needing that whole directory.
DIR = Path(__file__).resolve().parent / 'fixtures/gameover_ecbcd6e1a'
assert DIR.name == 'gameover_' + FREEZE[:9]

# name: what the tests take of it. ('body', function) or ('span', first line start, the text the span ends before).
EXCERPTS = {
    'ctr_renderer.c': [('body', 'onAptEvent'), ('body', 'CtrRenderer_beginFrame')],
    'z_layout.c': [('body', 'lyUpFlip18'), ('body', 'lyOptRow18'), ('body', 'CtrLayout_optRow')],
    'z_battletouch.c': [('body', 'obRow'), ('body', 'obCursor'), ('body', 'CtrOptbattle_compose'),
                        ('body', 'btObRowGrey')],
    'z_menutime.c': [('body', 'CtrMenutime_open')],
    'z_upd1_options.c': [('body', 'Upd1_menuOpen')],
    'ctr_argui.c': [('body', 'arguiPaintScreen')],
    'main.c': [('span', '        bool openMenu =', '        } else if (menu.open)'),
               ('span', '        if (autopauseLeft < 0', '        if (autopauseLeft > 0')],
}

SHA256 = {
    'ctr_renderer.c': '5eca3a758c35336ab4eb9268f9260afb14ea2459b4ce44b10c799e04b48115b7',
    'z_layout.c': '6e025ef881639100f206a6998be2210678b88fe05263688e34309049668dacac',
    'z_battletouch.c': 'a4e677db5db59bad616b0aa81b1241bdb77e8e1e8c9e0612a9fde2434873f676',
    'z_menutime.c': '658c091cddde5d1702dea5e58cb61ccbb726763d31d433dc28108f885f5437c4',
    'z_upd1_options.c': '02f2f4c800a0299883404faceaab07abb4632c6f857de27f6fa5556b1f5c0948',
    'ctr_argui.c': 'e48ce00c287f16c2ec2e42156869ac89ae0949184e6bd092fc45765d5672a375',
    'main.c': 'b1d6129f554381fc6c2aa75e505dac7dd74f0461ca33d0ce6e955defb6099d5b',
}


def take(text, item):
    """What a test takes of text: a function's body, or a span up to (not including) its end marker."""
    kind, first, end = (item + (None,))[:3]
    if kind == 'body':
        return body(text, first)
    return text[text.index(first):text.index(end)]


def excerpt(name, text):
    """The fixture file for name, cut from the whole frozen file: each item, its span's end marker kept so the
    tests' index() still finds it, one blank line between items."""
    parts = []
    for item in EXCERPTS[name]:
        part = take(text, item)
        if item[0] == 'span':
            part += item[2]
        parts.append(part)
    return '\n\n'.join(parts) + '\n'


def frozen(name):
    """The frozen excerpt of platform/3ds/source/<name> at FREEZE, from the committed fixture."""
    data = (DIR / (name + '.excerpt')).read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == SHA256[name], f'{DIR / name}.excerpt: sha256 {digest}, recorded {SHA256[name]}'
    return data.decode()
