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

    def test_line_numbers_and_all_code_bytes_unchanged(self):
        marker = ('lan' + 'e worker; lead ' + 'ruling; Eth' + 'an').encode()
        for newline in (b'\n', b'\r\n'):
            original = b'/* '+marker+b' */'+newline+b'int value = __LINE__;'+newline+b'// '+marker+newline
            result = scrub.scrub_member('source.c', original)
            self.assertNotEqual(original, result)
            self.assertEqual([c for c in original if c in (10,13)],
                             [c for c in result if c in (10,13)])
            self.assertEqual(original.split(newline)[1], result.split(newline)[1])
            self.assertIn(b'change worker; review decision; maintainer', result)
            self.assertEqual(result, scrub.scrub_member('source.c', result))

    def test_multiline_docstring_and_unicode_keep_line_numbers(self):
        raw = ('"""é\n'+'lan'+'e worker\n"""\nx = 1\n').encode()
        result = scrub.scrub_member('module.py', raw)
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

    def test_public_readmes_disclosures_and_notices_are_unchanged(self):
        raw = ('Most of the code was written with AI models (mainly Cla' + 'ude).\n'
               "Hi, I'm Eth" + "an.\n").encode()
        for name in ('README.md', 'docs/CONTRIBUTING.md', 'engine/README.md',
                     'tools/release/templates/README-undertale.md',
                     'LICENSE', 'THIRD_PARTY_NOTICES', 'vendor/component/NOTICE.txt',
                     'docs/release/credits-port.txt'):
            with self.subTest(name=name):
                self.assertEqual(scrub.scrub_member(name, raw), raw)
        self.assertEqual(scrub.scrub_files({'README.md': raw}), {'README.md': raw})

    def test_neutral_wording_keeps_parentheses_and_has_no_blank_holes(self):
        raw = ('# textcase (lan' + 'e codeclose, lever 1)\n'
               '# Cla' + 'ude and Eth' + 'an reviewed this.\n').encode()
        result = scrub.scrub_member('build.cmake', raw)
        self.assertEqual(result, b'# textcase (change codeclose, lever 1)\n'
                                 b'# assistant and maintainer reviewed this.\n')
        self.assertNotIn(b'   ', result)

    def test_blank_padding_is_rejected_including_at_an_edit_boundary(self):
        for raw, replacement in ((b'// alpha\n', b'     '),
                                 (b'//  alpha\n', b' beta')):
            at = raw.index(b'alpha')
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, 'inserted a run of 3\\+ spaces'):
                scrub.checked_rewrite('source.c', raw, [(at, at + 5, replacement)])

    def test_existing_indentation_is_not_new_blank_padding(self):
        raw = ('    # lan' + 'e worker\nvalue = 1\n').encode()
        result = scrub.scrub_member('module.py', raw)
        self.assertEqual(result, b'    # change worker\nvalue = 1\n')
        at = raw.index(b'worker')
        self.assertIn(b'  ', scrub.checked_rewrite('module.py', raw, [(at, at + 6, b' work')]))

    def test_variable_length_comment_edit_cannot_inject_code_or_delimiters(self):
        raw = b'/* alpha */\nint value = __LINE__;\n'
        at = raw.index(b'alpha')
        with self.assertRaisesRegex(ValueError, 'delimiter'):
            scrub.checked_rewrite('source.c', raw, [(at, at + 5, b'*/ int injected; /*')])


if __name__ == '__main__':
    unittest.main()
