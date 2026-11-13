"""The callback adapter moves a complete function and rejects unknown output."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import redpix_compile as adapter


def function(name, body):
    return '\t.section\t.text.'+name+',"ax",%progbits\n\t.align 2\n'+name+':\n'+body+'\t.size\t'+name+', .-'+name+'\n'


ROW = function('packRow', '\tbl\tCtrPack_convertTileRedpix\n\tbx lr\n')
CONVERT = function('CtrPack_convertTile', '\tmov r0, #1\n\tbx lr\n')
OTHER = function('startThread', '\tbx lr\n')


class Order(unittest.TestCase):
    def test_complete_chunks_move_without_editing(self):
        before = 'prefix\n'+ROW+OTHER+CONVERT+'suffix\n'
        after, receipt = adapter.restore(before)
        self.assertEqual(after, 'prefix\n'+OTHER+CONVERT+ROW+'suffix\n')
        self.assertTrue(receipt['changed'])
        self.assertEqual(adapter.restore(after)[0], after)
        self.assertFalse(adapter.restore(after)[1]['changed'])

    def test_missing_or_duplicate_anchor_rejected(self):
        for text in (ROW, CONVERT, ROW+ROW+CONVERT, ROW+CONVERT+CONVERT):
            with self.subTest(text=text), self.assertRaises(AssertionError):
                adapter.restore(text)

    def test_unexpected_conversion_call_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'conversion call'):
            adapter.restore(ROW.replace('CtrPack_convertTileRedpix', 'other')+CONVERT)

    def test_nested_section_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'nested section'):
            adapter.restore(ROW.replace('\tbx lr', '\t.section .rodata\n\tbx lr')+CONVERT)

    def test_different_later_position_rejected(self):
        with self.assertRaisesRegex(AssertionError, 'callback order'):
            adapter.restore(CONVERT+OTHER+ROW)


if __name__ == '__main__':
    unittest.main()
