import importlib.util
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import export_scrub as scrub


class ExportScrubTests(unittest.TestCase):
    def test_code_token_refusal(self):
        for name, raw in [('source.c', b'int private_symbol = 1;\n'),
                          ('module.py', b'private_symbol = 1\n'),
                          ('CMakeLists.txt', b'set(private_symbol 1)\n')]:
            at = raw.index(b'private_symbol')
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'code token'):
                scrub.checked_rewrite(name, raw, [(at, at + 14, b'public_symbol ' )])

    def test_line_positions_and_all_code_bytes_unchanged(self):
        marker = ('lan' + 'e worker; lead ' + 'ruling; Eth' + 'an').encode()
        for newline in (b'\n', b'\r\n'):
            original = b'/* '+marker+b' */'+newline+b'int value = __LINE__;'+newline+b'// '+marker+newline
            result = scrub.scrub_member('source.c', original)
            self.assertNotEqual(original, result)
            self.assertEqual(len(original), len(result))
            self.assertEqual([i for i,c in enumerate(original) if c in (10,13)],
                             [i for i,c in enumerate(result) if c in (10,13)])
            for i,(a,b) in enumerate(zip(original,result)):
                if a != b:
                    self.assertTrue(any(start<=i<end for start,end in scrub.editable_spans('source.c',original)))
            self.assertEqual(result, scrub.scrub_member('source.c', result))

    def test_multiline_docstring_and_unicode_keep_byte_positions(self):
        raw = ('"""é\n'+'lan'+'e worker\n"""\nx = 1\n').encode()
        result = scrub.scrub_member('module.py', raw)
        self.assertEqual(len(raw),len(result))
        self.assertEqual(raw.count(b'\n'),result.count(b'\n'))
        self.assertEqual(raw[raw.index(b'x ='):],result[result.index(b'x ='):])
        compile(result,'module.py','exec')

    def test_only_literal_option_help_is_editable(self):
        raw = ('p.add_argument("--x", help="'+'lan'+'e worker")\n'
               'value = "'+'lan'+'e worker"\n').encode()
        result = scrub.scrub_member('module.py',raw)
        self.assertIn(('value = "'+'lan'+'e worker"').encode(),result)
        at=raw.index(b'worker',raw.index(b'value'))
        with self.assertRaisesRegex(ValueError,'code token'):
            scrub.checked_rewrite('module.py',raw,[(at,at+6,b'public')])
        self.assertNotEqual(raw,result)

    def test_quoted_hash_heredoc_and_c_string_are_protected(self):
        for name, raw in [('CMakeLists.txt',b'set(x "# private_symbol")\n'),
                          ('build.sh',b'cat <<EOF\n# private_symbol\nEOF\n'),
                          ('source.c',b'char *x = "// private_symbol";\n')]:
            at=raw.index(b'private_symbol')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'code token'):
                scrub.checked_rewrite(name,raw,[(at,at+14,b'public_symbol ')])

    def test_delimiters_and_newlines_cannot_be_rewritten(self):
        raw=b'/* text\nmore */\n'
        with self.assertRaisesRegex(ValueError,'delimiter'):
            scrub.checked_rewrite('source.c',raw,[(0,1,b' ')])
        with self.assertRaisesRegex(ValueError,'line positions'):
            scrub.checked_rewrite('source.c',raw,[(3,8,b'other')])

    def test_approved_credit_is_unchanged(self):
        raw=('Eth'+'an Cawse\n').encode()
        self.assertEqual(scrub.scrub_member('docs/release/credits-port.txt',raw),raw)


if __name__ == '__main__':
    unittest.main()
