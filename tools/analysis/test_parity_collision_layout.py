"""Reject reachable instructions/data in a retained collision slot's suffix."""
import importlib.util
from pathlib import Path

import unittest

spec = importlib.util.spec_from_file_location('collision_layout', Path(__file__).with_name('check_parity_collision_layout.py'))
layout = importlib.util.module_from_spec(spec)
spec.loader.exec_module(layout)


def body():
    # One conditional early return; final block jumps back into the body.
    # Mapping symbols classify the following literal pool as data.
    return [(0x1000, 'push', '{r4, lr}'),
            (0x1004, 'popeq', '{r4, pc}'),
            (0x1008, 'b', '1000 <dispatchCollisionEvents>'),
            (0x100c, 'nop', '{0}')]


class RetainedCollisionTail(unittest.TestCase):
    def test_unreachable_alignment_nop(self):
        result = layout.prove_retained_tail(body(), 0x1000, 0x1018, 0x1020)
        self.assertEqual(result['dead_suffix_start'], '0x100c')
        self.assertEqual(result['alignment_nop_bytes'], 4)


    def test_incoming_branch_to_nop_literal_or_retained_tail_fails(self):
        for target in (0x100c, 0x1010, 0x1018, 0x101c):
            with self.subTest(target=hex(target)):
                rows = body()+[(0x2000, 'bl', f'{target:x} <dispatchCollisionEvents+offset>')]
                with self.assertRaisesRegex(AssertionError, 'Branch into dead suffix'):
                    layout.prove_retained_tail(rows, 0x1000, 0x1018, 0x1020)


    def test_fallthrough_before_nop_fails(self):
        for mnemonic, operand in (('mov', 'r0, r1'), ('bne', '1000 <dispatchCollisionEvents>'),
                                  ('bl', '3000 <ordinary_call>'), ('popeq', '{r4, pc}')):
            with self.subTest(mnemonic=mnemonic):
                rows = body()
                rows[2] = (0x1008, mnemonic, operand)
                with self.assertRaisesRegex(AssertionError, 'Fallthrough into tail'):
                    layout.prove_retained_tail(rows, 0x1000, 0x1018, 0x1020)


    def test_extra_alignment_instruction_fails(self):
        with self.assertRaisesRegex(AssertionError, 'Unexpected trailing instructions'):
            layout.prove_retained_tail(body()+[(0x1010, 'nop', '{0}')], 0x1000, 0x1018, 0x1020)


if __name__ == '__main__':
    unittest.main()
