"""Synthetic and negative fixtures for the approved bounded pool adapter."""
from pathlib import Path
import re
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colexact_compile as adapter


def group(label, word):
    return '\t.section\t.rodata.str1.4\n\t.align\t2\n.LC'+str(label)+':\n\t.ascii\t"'+word+r'\000"'+'\n'


CODE = '\t.section\t.text.fixture,"ax",%progbits\nfixture:\n\tbx lr\n\t.word .LC11\n'
FIRST = group(11, 'distance_to_point')
SECOND = group(12, 'distance_to_object')
ANCHOR = group(13, 'ini_section_exists')
LAST = group(14, 'unchanged_string')
CANONICAL = FIRST+SECOND+ANCHOR+CODE+LAST
DIGEST = adapter.fingerprint(['"'+x+r'\000"' for x in (*adapter.KEYS, adapter.ANCHOR, 'unchanged_string')])


class PoolTest(unittest.TestCase):
    def restore(self, text):
        return adapter.restore_pool(text, DIGEST, 4)

    def test_moves_only_complete_groups_and_preserves_labels_and_code(self):
        actual, receipt = self.restore(ANCHOR+CODE+FIRST+SECOND+LAST)
        self.assertEqual(actual, CANONICAL)
        self.assertTrue(receipt['changed'])
        self.assertEqual(receipt['labels']['distance_to_point'], '.LC11')

    def test_idempotent(self):
        actual, receipt = self.restore(CANONICAL)
        self.assertEqual(actual, CANONICAL)
        self.assertFalse(receipt['changed'])

    def test_each_missing_anchor_fails(self):
        for block in (FIRST, SECOND, ANCHOR):
            with self.subTest(block=block), self.assertRaisesRegex(AssertionError, 'missing/duplicate'):
                self.restore(CANONICAL.replace(block, ''))

    def test_duplicate_fails(self):
        with self.assertRaisesRegex(AssertionError, 'missing/duplicate'):
            self.restore(CANONICAL+FIRST)

    def test_foreign_directive_in_moved_group_fails(self):
        with self.assertRaisesRegex(AssertionError, 'unqualified'):
            self.restore(CANONICAL.replace(FIRST, FIRST+'\t.word 123\n'))

    def test_other_string_change_fails(self):
        with self.assertRaisesRegex(AssertionError, 'unexpected canonical'):
            self.restore(CANONICAL.replace('unchanged_string', 'changed_string'))

    def test_other_pool_order_change_fails(self):
        with self.assertRaisesRegex(AssertionError, 'unexpected canonical'):
            self.restore(LAST+FIRST+SECOND+ANCHOR+CODE)

    def test_text_limit_groups_restore_the_original_canonical_pool(self):
        write = group(21, 'file_text_open_write')
        error = group(22, r'Too many open text files!\012').split('\n', 1)[1]
        seed = group(23, 'random_set_seed')
        read = group(24, 'file_text_open_read')
        decode = group(25, 'base64_decode')
        canonical = FIRST+SECOND+ANCHOR+CODE+write+error+seed+read+decode+LAST
        changed = FIRST+SECOND+ANCHOR+CODE+seed+write+error+decode+read+LAST
        strings = lambda text: adapter.pool_strings(adapter.re.split(r'(?=^[ \t]*\.section[ \t]+)', text, flags=adapter.re.M))
        expected = adapter.fingerprint(strings(canonical))
        observed = adapter.fingerprint(strings(changed))
        # The real adapter accepts only the one measured complete-TU ordering.
        # Substitute a synthetic fingerprint here; no engine strings are copied.
        with mock.patch.object(adapter, 'TEXT_LIMIT_POOL', observed, create=True):
            actual, receipt = adapter.restore_pool(changed, expected, 9)
        self.assertEqual(actual, canonical)
        self.assertEqual(receipt['after_sha256'], expected)
        actual, receipt = adapter.restore_pool(canonical, expected, 9)
        self.assertEqual(actual, canonical)
        self.assertFalse(receipt['text_limit_restored'])

    def test_text_limit_group_with_code_is_refused(self):
        write = group(21, 'file_text_open_write') + '\t.word 123\n'
        error = group(22, r'Too many open text files!\012').split('\n', 1)[1]
        seed = group(23, 'random_set_seed')
        read = group(24, 'file_text_open_read')
        decode = group(25, 'base64_decode')
        changed = FIRST+SECOND+ANCHOR+CODE+seed+write+error+decode+read+LAST
        strings = adapter.pool_strings(adapter.re.split(r'(?=^[ \t]*\.section[ \t]+)', changed, flags=adapter.re.M))
        with mock.patch.object(adapter, 'TEXT_LIMIT_POOL', adapter.fingerprint(strings), create=True):
            with self.assertRaisesRegex(AssertionError, 'unqualified'):
                adapter.restore_pool(changed, DIGEST, 9)

    def test_text_limit_normalization_does_not_accept_other_pool_orders(self):
        write = group(21, 'file_text_open_write')
        error = group(22, r'Too many open text files!\012').split('\n', 1)[1]
        seed = group(23, 'random_set_seed')
        read = group(24, 'file_text_open_read')
        decode = group(25, 'base64_decode')
        for tail in (read+decode+seed+write+error, write+error+seed+decode+read):
            with self.subTest(tail=tail), self.assertRaisesRegex(AssertionError, 'unexpected canonical'):
                adapter.restore_pool(FIRST+SECOND+ANCHOR+CODE+tail+LAST, DIGEST, 9)

    def test_guard_and_delegate(self):
        args = ['delegate', adapter.MARKER, 'gcc', '-c', '/engine/src/vm_builtins.c', '-o', 'vm.o',
            '-DENABLE_WAD16', '-DCTRPORT_BBOX_ROUND', '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT']
        self.assertTrue(adapter.selected(args[2:]))
        for flag in ('-DENABLE_WAD16', '-DCTRPORT_BBOX_ROUND', '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT'):
            with self.subTest(flag=flag), mock.patch.object(adapter, 'run', return_value=7) as run:
                command = [a for a in args if a != flag]
                self.assertEqual(adapter.main(command), 7)
                run.assert_called_once_with(['delegate']+command[2:])

    def test_room_pair_preserves_code_labels_and_canonical_pool(self):
        room, keyboard = group(15, 'room_get_name'), group(16, 'keyboard_set_map')
        canonical = CANONICAL + room + keyboard
        digest = adapter.fingerprint(adapter.pool_strings(re.split(
            r'(?=^[ \t]*\.section[ \t]+)', canonical, flags=re.M)))
        actual, receipt = adapter.restore_pool(CANONICAL + keyboard + CODE + room, digest, 6)
        self.assertEqual(actual, CANONICAL + room + CODE + keyboard)
        self.assertTrue(receipt['room_pair_restored'])
        self.assertEqual(actual.count(CODE), 2)
        self.assertIn('.LC15:\n\t.ascii\t"room_get_name', actual)
        self.assertIn('.LC16:\n\t.ascii\t"keyboard_set_map', actual)
        actual, receipt = adapter.restore_pool(canonical, digest, 6)
        self.assertEqual(actual, canonical)
        self.assertFalse(receipt['room_pair_restored'])

    def test_room_pair_rejects_missing_duplicate_or_foreign_directives(self):
        room, keyboard = group(15, 'room_get_name'), group(16, 'keyboard_set_map')
        for addition, reason in ((room, 'missing room'), (room+room+keyboard, 'duplicate room'),
                (room+'\t.word 9\n'+keyboard, 'unqualified room')):
            with self.subTest(addition=addition), self.assertRaisesRegex(AssertionError, reason):
                self.restore(CANONICAL + addition)

    def test_room_pair_does_not_waive_the_complete_pool_digest(self):
        room, keyboard = group(15, 'room_get_name'), group(16, 'keyboard_set_map')
        with self.assertRaisesRegex(AssertionError, 'unexpected canonical'):
            adapter.restore_pool(CANONICAL + keyboard + room, '0'*64, 6)

    def test_dr_restores_only_room_pair_and_keeps_distance_order(self):
        room, keyboard = group(15, 'room_get_name'), group(16, 'keyboard_set_map')
        canonical = ANCHOR + CODE + FIRST + SECOND + LAST + room + keyboard
        digest = adapter.fingerprint(adapter.pool_strings(re.split(
            r'(?=^[ \t]*\.section[ \t]+)', canonical, flags=re.M)))
        actual, receipt = adapter.restore_dr_pool(
            ANCHOR + CODE + FIRST + SECOND + LAST + keyboard + room, digest, 6)
        self.assertEqual(actual, canonical)
        self.assertTrue(receipt['room_pair_restored'])
        self.assertEqual(receipt['game'], 'deltarune')
        self.assertEqual(adapter.restore_dr_pool(canonical, digest, 6)[0], canonical)
        for changed in (canonical.replace('unchanged_string', 'changed_string'),
                canonical.replace(FIRST + SECOND, SECOND + FIRST)):
            with self.subTest(changed=changed), self.assertRaisesRegex(AssertionError, 'unexpected canonical DR'):
                adapter.restore_dr_pool(changed, digest, 6)
        for changed in (canonical.replace(room, ''), canonical.replace(room, room + room),
                canonical.replace(room, room + '\t.word 99\n')):
            with self.subTest(changed=changed), self.assertRaises(AssertionError):
                adapter.restore_dr_pool(changed, digest, 6)

    def test_dr_selection_requires_qualified_release_flags_and_delegates_other_commands(self):
        command = ['gcc', '-c', '/engine/src/vm_builtins.c', '-o', 'vm.o', '-DENABLE_WAD17',
            '-DPLATFORM_3DS', '-D__3DS__', '-O2', '-DNDEBUG',
            '-DCTRPORT_BBOX_ROUND', '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT']
        self.assertTrue(adapter.selected_dr(command))
        self.assertFalse(adapter.selected(command))
        for changed in ([a for a in command if a != flag] for flag in command[5:]):
            with self.subTest(changed=changed), mock.patch.object(adapter, 'run', return_value=7) as run:
                self.assertEqual(adapter.main(['delegate', adapter.MARKER, *changed]), 7)
                run.assert_called_once_with(['delegate', *changed])
        self.assertFalse(adapter.selected_dr(command + ['-DUSE_FLOAT_REALS']))


if __name__ == '__main__':
    unittest.main()
