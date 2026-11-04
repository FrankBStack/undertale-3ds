"""The collision redirect must fail closed and preserve unrelated assembly."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('drhitbox_compile', Path(__file__).with_name('drhitbox_compile.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class RedirectTests(unittest.TestCase):
    def fixture(self):
        return ('header\nCollision_compatRectHitsInstance:\n bx lr\n'
                'builtin_collision_rectangle_compat:\n.L1:\n bl Collision_compatRectHitsInstance\n'
                ' bx lr\nbuiltin_collision_rectangle_list_compat:\n.L2:\n'
                ' bl Collision_compatRectHitsInstance(PLT)\n bx lr\nfooter\n')

    def test_only_two_call_operands_change(self):
        before = self.fixture()
        after, receipt = adapter.rewrite(before, 'collision_compat.c')
        self.assertEqual(after.replace('DrHitbox_rectHits', adapter.OLD), before)
        self.assertEqual(receipt['redirected_calls'], 2)
        self.assertIn('Collision_compatRectHitsInstance:\n bx lr', after)

    def test_missing_or_extra_call_refused(self):
        for before in [self.fixture().replace(' bl '+adapter.OLD+'\n', ''),
                       self.fixture()+' bl '+adapter.OLD+'\n']:
            with self.assertRaises(AssertionError):
                adapter.rewrite(before, 'collision_compat.c')

    def test_wrong_caller_refused(self):
        with self.assertRaises(AssertionError):
            adapter.rewrite(self.fixture().replace('builtin_collision_rectangle_compat:', 'unrelated:'),
                            'collision_compat.c')

    def test_bridge_appends_without_rewriting_retained_body(self):
        before = '.section .text.Collision_computeBBox\nCollision_computeBBox:\n bx lr\n'
        after, receipt = adapter.rewrite(before, 'runner.c')
        self.assertTrue(after.startswith(before))
        self.assertEqual(receipt['bridge_bytes'], 4)
        self.assertIn('.pushsection .text.late.drhitbox_bridge,', after)
        self.assertIn(' b Collision_computeBBox\n', after)

    def test_missing_bbox_or_duplicate_bridge_refused(self):
        for before in ['', 'Collision_computeBBox:\nDrHitbox_sharedBBox:\n']:
            with self.assertRaises(AssertionError):
                adapter.rewrite(before, 'runner.c')


if __name__ == '__main__':
    unittest.main()
