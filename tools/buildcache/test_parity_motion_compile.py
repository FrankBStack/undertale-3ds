"""Retained slot fails closed for ambiguous bodies, pools and compiler sections."""
import unittest
import sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import parity_motion_compile as adapter


class MotionBodyTests(unittest.TestCase):
    def setUp(self):
        self.old = ('prefix\n' + adapter.SYMBOL + ':\n.LFB1:\n'
                    '\t.loc 1 9 view .LVU7\n\tbl cos\n\tpop {r4, pc}\n'
                    '.L2:\n\t.word 42\n.LFE1:\n'
                    '\t.size ' + adapter.SYMBOL + ', .-' + adapter.SYMBOL + '\nsuffix\n')
        self.new = (adapter.SYMBOL + ':\n\t.loc 2 5\n\tb .L3\n.L3:\n'
                    '\tpop {r4, pc}\n\t.word 9\n'
                    '\t.size ' + adapter.SYMBOL + ', .-' + adapter.SYMBOL + '\n')

    def test_only_bounded_body_and_local_labels_change(self):
        result, receipt = adapter.rewrite(self.old, self.new)
        self.assertTrue(result.startswith('prefix\n' + adapter.SYMBOL + ':\n'))
        self.assertTrue(result.endswith('\nsuffix\n'))
        self.assertIn('\tb .LPM_3\n.LPM_3:\n', result)
        self.assertNotIn('\t.loc 2 5', result)
        self.assertIn('.set .LVU7, 0', result)
        self.assertIn('\t.org ' + adapter.SYMBOL + '+248, 0', result)
        self.assertEqual(receipt['slot_bytes'], 248)

    def test_relocated_old_pool_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Non-numeric'):
            adapter.rewrite(self.old.replace('.word 42', '.word external'), self.new)

    def test_duplicate_entry_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'duplicate'):
            adapter.rewrite(self.old + self.old, self.new)

    def test_nested_section_is_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'Nested'):
            adapter.rewrite(self.old, self.new.replace('\tb .L3', '\t.section .data\n\tb .L3'))

    def command(self):
        return ['cc', '-DENABLE_WAD16', '-DPLATFORM_3DS', '-O2', '-DNDEBUG', '-c', 'src/instance.c', '-o', 'instance.o']

    def test_every_missing_required_flag_fails_without_compiling_old_body(self):
        for flag in ('-DENABLE_WAD16', '-DPLATFORM_3DS', '-O2', '-DNDEBUG'):
            with self.subTest(flag=flag), patch.object(adapter, 'run') as run:
                command = self.command();command.remove(flag)
                with self.assertRaisesRegex(AssertionError, 'refusing old motion'):
                    adapter.main([adapter.MARKER]+command)
                run.assert_not_called()

    def test_conflicting_optimization_fails(self):
        with patch.object(adapter, 'run') as run, self.assertRaisesRegex(AssertionError, 'only -O2'):
            adapter.main([adapter.MARKER]+self.command()+['-Os'])
        run.assert_not_called()

    def test_other_translation_units_delegate(self):
        command = [arg.replace('instance.c', 'other.c') for arg in self.command()]
        with patch.object(adapter, 'run', return_value=7) as run:
            self.assertEqual(adapter.main(['cache', adapter.MARKER]+command), 7)
            run.assert_called_once_with(['cache']+command)


if __name__ == '__main__':
    unittest.main()
