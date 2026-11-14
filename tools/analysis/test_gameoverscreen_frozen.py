"""The committed excerpts of frozen commit ecbcd6e1a are exactly what git show gave (gameoverscreen_frozen).

In every clone each excerpt file must match its recorded sha256. Where the private commit is present (the dev repo),
each file must be byte-for-byte the excerpt cut from git show again, and every body() or span the game-over tests take
must come out the same from the excerpt as from the whole file. A public clone has no such commit: that part skips.
"""
from pathlib import Path
import subprocess, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from gameoverscreen_host_fixture import ROOT
import gameoverscreen_frozen as gf


def whole(name):
    """The whole file at the frozen commit, or None when this clone does not have that commit."""
    have = subprocess.run(['git', 'cat-file', '-e', gf.FREEZE + '^{commit}'], cwd=ROOT, stdin=subprocess.DEVNULL,
                          capture_output=True, timeout=20)
    if have.returncode:
        return None
    return subprocess.check_output(['git', 'show', gf.FREEZE + ':platform/3ds/source/' + name], cwd=ROOT,
                                   stdin=subprocess.DEVNULL, timeout=20).decode()


class FrozenExcerpts(unittest.TestCase):
    def test_every_excerpt_matches_its_recorded_sha256(self):
        self.assertEqual(sorted(gf.SHA256), sorted(gf.EXCERPTS))
        for name in gf.EXCERPTS:
            self.assertTrue(gf.frozen(name))

    def test_excerpts_are_what_git_show_gives_at_the_frozen_commit(self):
        if whole('main.c') is None:
            self.skipTest(f'commit {gf.FREEZE[:9]} is not in this clone (a public clone): the recorded sha256 stands')
        for name, items in gf.EXCERPTS.items():
            text = whole(name)
            data = (gf.DIR / (name + '.excerpt')).read_bytes()
            self.assertEqual(data, gf.excerpt(name, text).encode(), name)
            for item in items:
                self.assertEqual(gf.take(data.decode(), item), gf.take(text, item), (name, item))

    def test_a_changed_excerpt_is_refused(self):
        name = 'z_menutime.c'
        recorded = gf.SHA256[name]
        try:
            gf.SHA256[name] = '0' * 64
            with self.assertRaises(AssertionError):
                gf.frozen(name)
        finally:
            gf.SHA256[name] = recorded


if __name__ == '__main__':
    unittest.main()
