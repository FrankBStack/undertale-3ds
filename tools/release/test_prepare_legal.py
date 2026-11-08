"""Pagination preserves legal text and the bundle retains original source bytes."""
import json
from pathlib import Path
import struct
import tempfile
import unittest

from tools.release.prepare_legal import console_text, paginate, prepare, reflow, split_bytes

ROOT = Path(__file__).resolve().parents[2]


class LegalPagesTests(unittest.TestCase):
    def rows(self, output, columns):
        return [output[i:i + columns + 1].split(b'\0')[0]
                for i in range(8, len(output), columns + 1)]

    def test_wraps_exact_columns_without_losing_paragraphs(self):
        output = paginate(b'abcd\nefghijk\n\nlast\n', 4, 2)
        self.assertEqual(output[:4], b'LGL1')
        self.assertEqual(struct.unpack('<I', output[4:8])[0], 3)
        self.assertEqual(self.rows(output, 4), [b'abcd', b'efgh', b'ijk', b'', b'last', b''])
        self.assertEqual(len(output), 8 + 3 * 2 * 5)

    def test_console_pages_have_no_character_the_reader_shows_as_a_question_mark(self):
        # ctr_legal.c's luiLine draws anything outside 32..126 as '?'. Every byte of every shipped page, not just the two
        # names this was found on.
        contract = json.loads((ROOT / 'docs/release/build-contract.json').read_text(encoding='utf-8'))
        for name in ('LICENSE', 'THIRD_PARTY_NOTICES'):
            pages = paginate((ROOT / name).read_bytes(), contract['legal_columns'], contract['legal_lines'])
            rows = self.rows(pages, contract['legal_columns'])
            self.assertEqual([r for r in rows if any(not 32 <= c <= 126 for c in r)], [], name)

    def test_console_pages_spell_the_two_names_in_ascii_and_change_nothing_else(self):
        contract = json.loads((ROOT / 'docs/release/build-contract.json').read_text(encoding='utf-8'))
        source = (ROOT / 'THIRD_PARTY_NOTICES').read_bytes()
        self.assertEqual(sorted({c for c in source.decode('utf-8') if ord(c) > 126}), ['\u00a9', '\u00f6'])
        columns = contract['legal_columns']
        rows = self.rows(paginate(source, columns, contract['legal_lines']), columns)
        joined = b''.join(rows).replace(b' ', b'')
        self.assertIn(b'KungligaTekniskaHogskolan', joined)
        self.assertIn(b'Copyright(c)2005-2020RichFelker', joined)
        spelled = source.replace('\u00f6'.encode(), b'o').replace('\u00a9'.encode(), b'(c)')
        # The text itself, whitespace aside: nothing lost, added or reordered.
        self.assertEqual(joined, b''.join(spelled.expandtabs(4).split()))
        # And outside those two lines, the same rows as the unchanged wrap of the same text.
        self.assertEqual(paginate(spelled, columns, contract['legal_lines']),
                         paginate(source, columns, contract['legal_lines']))

    def test_a_character_without_an_ascii_spelling_stops_the_build(self):
        # Not a silent '?' on the console when a notice is regenerated with a new name.
        for text in ('Copyright \u00e9'.encode(), 'a \u2014 b'.encode(), 'x\x7fy'.encode()):
            with self.assertRaises(ValueError):
                paginate(text, 38, 13)

    def test_bundle_keeps_the_real_characters(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'out'
            prepare(ROOT, out)
            self.assertEqual((out / 'THIRD_PARTY_NOTICES').read_bytes(), (ROOT / 'THIRD_PARTY_NOTICES').read_bytes())
            self.assertIn('H\u00f6gskolan'.encode(), (out / 'THIRD_PARTY_NOTICES').read_bytes())

    def test_reflow_joins_hard_wrapped_prose_only(self):
        long = 'The GNU Affero General Public License is a free, copyleft license'
        self.assertEqual(reflow(['  ' + long, 'for software and other kinds of works.', '', 'next']),
                         ['  ' + long + ' for software and other kinds of works.', '', 'next'])
        kept = [long, '  1. Definitions.', long, 'Licence: MIT', long, 'Copyright (c) 2020 Someone', long,
                '        Preamble', long, '====', 'short line', 'stays']
        self.assertEqual(reflow(kept), kept)

    def test_empty_file_and_utf8_boundaries(self):
        self.assertEqual(self.rows(paginate(b'', 4, 1), 4), [b''])
        rows = split_bytes('ab\u00a9cd', 3)
        self.assertEqual(rows, ['ab'.encode(), '\u00a9c'.encode(), b'd'])
        self.assertEqual(b''.join(self.rows(paginate('ab\u00a9cd'.encode(), 3, 2), 3)), b'ab(c)cd')
        for row in rows:
            row.decode('utf-8')

    def test_bad_dimensions_and_nuls_fail(self):
        for columns, lines in ((0, 22), (39, 22), (38, 23)):
            with self.assertRaises(ValueError):
                paginate(b'x', columns, lines)
        with self.assertRaises(ValueError):
            paginate(b'broken\0text', 38, 22)

    def test_original_texts_are_bundled_unchanged_and_not_rewritten(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'scratch') as directory:
            output = Path(directory) / 'legal'
            prepare(ROOT, output)
            before = {p.name: p.stat().st_mtime_ns for p in output.iterdir()}
            prepare(ROOT, output)
            self.assertEqual(before, {p.name: p.stat().st_mtime_ns for p in output.iterdir()})
            contract = json.loads((ROOT / 'docs/release/build-contract.json').read_text())
            for name in ('LICENSE', 'THIRD_PARTY_NOTICES'):
                self.assertEqual((output / name).read_bytes(), (ROOT / name).read_bytes())
                pages = (output / (name + '.pages')).read_bytes()
                count = struct.unpack('<I', pages[4:8])[0]
                self.assertEqual(len(pages), 8 + count * contract['legal_lines'] * (contract['legal_columns'] + 1))
                original = (ROOT / name).read_text(encoding='utf-8').expandtabs(4)
                # Wrapping changes whitespace only; every notice character survives.
                actual = b''.join(self.rows(pages, contract['legal_columns'])).decode()
                self.assertEqual(''.join(actual.split()), ''.join(console_text(original).split()))
