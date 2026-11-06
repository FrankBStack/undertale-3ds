"""Synthetic assembly and compiler-delegation fixtures for retained RNG slots."""
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rngexact_compile as adapter


def body(name):
    symbol = 'builtin_' + name
    return (symbol + ':\n\t.cfi_startproc\n.LFB_' + name + ':\n'
        '\t.loc 1 10 0 view .LVU_' + name + '\n\tmov r0, #7\n'
        '.Lpool_' + name + ': @ literal pool\n\t.word .LC_' + name + '\n'
        '\t.word external_' + name + ' @ keep relocation\n'
        '.LFE_' + name + ':\n\t.cfi_endproc\n\t.size ' + symbol + ', .-' + symbol + '\n')


ASSEMBLY = '\t.text\nunchanged_before:\n\tbx lr\n' + ''.join(body(n) for n in adapter.SLOTS) + 'unchanged_after:\n\tbx lr\n'


class EntryTest(unittest.TestCase):
    def test_branches_labels_words_views_and_sizes(self):
        text, receipt = adapter.rewrite(ASSEMBLY)
        self.assertTrue(text.startswith('\t.text\nunchanged_before:\n\tbx lr\n'))
        self.assertTrue(text.endswith('unchanged_after:\n\tbx lr\n'))
        for name, size in adapter.SLOTS.items():
            with self.subTest(name=name):
                symbol = 'builtin_' + name
                slot = text.split(symbol + ':\n', 1)[1].split('\t.size ' + symbol, 1)[0]
                self.assertTrue(slot.startswith('\tb RNGExact_' + name + '\n'))
                self.assertEqual(re.findall(r'(?m)^\s*b\s+(\S+)', slot), ['RNGExact_' + name])
                self.assertEqual(re.findall(r'(?m)^(\.L\w+):', slot), ['.LFB_' + name, '.Lpool_' + name, '.LFE_' + name])
                self.assertIn('.set .LVU_' + name + ', 0\n', slot)
                self.assertIn('\t.word .LC_' + name + '\n\t.word external_' + name + '\n', slot)
                self.assertIn('\t.space %d-(.-%s), 0\n' % (size, symbol), slot)
                self.assertNotIn('.cfi_', slot)
                self.assertNotIn('mov r0', slot)
                self.assertEqual(receipt[symbol]['bytes'], size)
                self.assertEqual(receipt[symbol]['retained_words'], 2)

    def test_deterministic(self):
        self.assertEqual(adapter.rewrite(ASSEMBLY), adapter.rewrite(ASSEMBLY))

    def test_missing_or_duplicate_symbol(self):
        for name in adapter.SLOTS:
            for text in (ASSEMBLY.replace(body(name), ''), ASSEMBLY + body(name)):
                with self.subTest(name=name), self.assertRaisesRegex(AssertionError, 'missing/duplicate'):
                    adapter.rewrite(text)

    def test_nested_section(self):
        for directive in ('.section .text.other', '.pushsection .rodata'):
            with self.subTest(directive=directive), self.assertRaisesRegex(AssertionError, 'nested RNG section'):
                adapter.rewrite(ASSEMBLY.replace('builtin_random:\n', 'builtin_random:\n\t' + directive + '\n'))

    def test_duplicate_local_label(self):
        with self.assertRaisesRegex(AssertionError, 'duplicate local label'):
            adapter.rewrite(ASSEMBLY.replace('.LFB_random:\n', '.LFB_random:\n.LFB_random:\n'))

    def test_unselected_compile_delegates(self):
        for source, flags in (('/engine/src/other.c', ['-DCTRPORT_LAYERFIX_RELEASE_LAYOUT']),
                              ('/engine/src/vm_builtins.c', []),
                              ('/engine/src/other.c', [])):
            args = ['cache', adapter.MARKER, 'gcc', '-c', source, '-o', 'vm.o'] + flags
            with self.subTest(source=source, flags=flags), mock.patch.object(adapter, 'run', return_value=7) as run, mock.patch('sys.stderr') as stderr:
                self.assertEqual(adapter.main(args), 7)
                run.assert_called_once_with(['cache'] + args[2:])
                message = ''.join(call.args[0] for call in stderr.write.call_args_list)
                if source.endswith('/vm_builtins.c'):
                    self.assertIn('delegated without rewrite', message)
                    self.assertIn('release_define=False, vm_builtins_sources=1', message)
                else:
                    stderr.write.assert_not_called()
                    self.assertEqual(message, '')

    def test_duplicate_builtin_sources_are_reported(self):
        command = ['gcc', '-c', '/a/vm_builtins.c', '/b/vm_builtins.c',
                   '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT', '-o', 'vm.o']
        with mock.patch.object(adapter, 'run', return_value=7) as run, mock.patch('sys.stderr') as stderr:
            self.assertEqual(adapter.main([adapter.MARKER] + command), 7)
            run.assert_called_once_with(command)
            message = ''.join(call.args[0] for call in stderr.write.call_args_list)
            self.assertIn('release_define=True, vm_builtins_sources=2', message)

    def test_compile_pipeline_and_pre310_write_api(self):
        # Simulate the pre-3.10 Path.write_text API, which rejects newline=.
        write_text = Path.write_text
        def old_write_text(path, data, encoding=None, errors=None):
            return write_text(path, data, encoding=encoding, errors=errors)
        scratch = Path(__file__).resolve().parents[2] / 'scratch'
        scratch.mkdir(exist_ok=True)
        # (game, delegate): UT with colexact; DR alone; DR with auditfixg's DR pool adapter (sonrev3 R227-1).
        for game, delegate in (('16', ['/tools/colexact_compile.py']), ('17', ['cache']),
                               ('17', ['cache', '/tools/colexact_compile.py'])):
            with self.subTest(game=game, delegate=delegate), tempfile.TemporaryDirectory(dir=scratch) as tmp:
                obj = Path(tmp) / 'vm.o'
                pool = any(a.endswith('/colexact_compile.py') for a in delegate)
                command = ['gcc', '-c', '/engine/src/vm_builtins.c', '-o', str(obj),
                    '-DENABLE_WAD' + game, '-DCTRPORT_LAYERFIX_RELEASE_LAYOUT',
                    '-MMD', '-MP', '-MF', 'dep.d', '-MT', 'target', '-MQ', 'quoted']
                calls = []
                def run(args):
                    calls.append(args)
                    if len(calls) == 1:
                        # The pool adapter asserts a -c compile; the plain DR path asks for -S.
                        self.assertEqual(('-c' in args, '-S' in args), (pool, not pool))
                        self.assertEqual(args[:len(delegate)], delegate)
                        name = 'colexact1.s' if pool else 'rng0.s'
                        (obj.parent / name).write_text(ASSEMBLY, encoding='utf-8')
                    return 0
                with mock.patch.object(adapter, 'run', side_effect=run), mock.patch.object(Path, 'write_text', old_write_text):
                    self.assertEqual(adapter.main(delegate + [adapter.MARKER] + command), 0)
                self.assertEqual((obj.parent / 'rng1.s').read_bytes(), adapter.rewrite(ASSEMBLY)[0].encode('utf-8'))
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[-1][-6:], ['-x', 'assembler', '-c', str(obj.parent / 'rng1.s'), '-o', str(obj)])
                for flag in ('-MMD', '-MP', '-MF', '-MT', '-MQ'):
                    self.assertNotIn(flag, calls[-1])


if __name__ == '__main__':
    unittest.main()
