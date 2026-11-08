"""Dispatch routing fails closed and preserves every other assembly byte."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
import tempfile

spec = importlib.util.spec_from_file_location('gmlstubs_compile', Path(__file__).with_name('gmlstubs_compile.py'))
adapter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(adapter)


class BackgroundRoutingTests(unittest.TestCase):
    def fixture(self):
        return ('resolveNamedVar:\n bl bsearch\n bx lr\n'
                'VMBuiltins_resolveBuiltinVarId:\n bl bsearch\n bx lr\n'
                'getter:\n bl VMBuiltins_getVariable\n b VMBuiltins_getVariable\n'
                'setter:\n bl VMBuiltins_setVariable\n')

    def test_only_call_targets_change(self):
        before = self.fixture()
        after, _ = adapter.rewrite(before, 'vm_builtins.c')
        after = after.replace('Gmlstubs_varSearch', 'bsearch').replace('__wrap_', '')
        self.assertEqual(before, after)

    def test_unqualified_count_and_caller_fail(self):
        for text in (self.fixture()+' bl bsearch\n',
                     self.fixture().replace('resolveNamedVar:', 'other:')):
            with self.assertRaises(AssertionError):
                adapter.rewrite(text, 'vm_builtins.c')

    def test_bridges_are_appended(self):
        before = ('drawGMS1Backgrounds:\n bx lr\ndrawBackground:\n bx lr\ninitRoom:\n bx lr\n'
                  + ' bl drawGMS1Backgrounds\n'*4 + ' bl initRoom\n'*3)
        after, _ = adapter.rewrite(before, 'runner.c')
        prefix = after.split('\n.pushsection')[0]
        self.assertEqual(prefix.replace('Gmlstubs_drawLegacy', 'drawGMS1Backgrounds')
                         .replace('Gmlstubs_initRoom', 'initRoom'), before)
        self.assertEqual(after.count('.size Gmlstubs_'), 2)
        self.assertIn('.word drawGMS1Backgrounds\n', after)

    def test_nonrelease_uninlined_resolver(self):
        before = self.fixture().replace('resolveNamedVar:\n bl bsearch\n',
                                        'resolveNamedVar:\n bl VMBuiltins_resolveBuiltinVarId\n')
        after, receipt = adapter.rewrite(before, 'vm_builtins.c', release=False)
        self.assertEqual(receipt['calls']['bsearch'], 1)
        self.assertIn(' bl VMBuiltins_resolveBuiltinVarId\n', after)
        with self.assertRaises(AssertionError):
            adapter.rewrite(before, 'vm_builtins.c', release=True)

    def test_nonrelease_emits_assembly_without_rng_side_file(self):
        root = Path(__file__).resolve().parents[2]
        (root/'scratch').mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=root/'scratch', prefix='gml-profile-') as directory:
            output=Path(directory)/'builtins.o'
            commands=[]
            def compiler(command):
                commands.append(command)
                if '-S' in command:
                    Path(command[command.index('-o')+1]).write_text(self.fixture())
                return 0
            with patch.object(adapter,'run',side_effect=compiler):
                result=adapter.main(['delegate',adapter.MARKER,'gcc','-DENABLE_WAD16',
                                     '-c','/engine/src/vm_builtins.c','-o',str(output)])
            self.assertEqual(result,0)
            self.assertEqual(len(commands),2)
            self.assertIn('-S',commands[0])
            self.assertIn('-x',commands[1])
            self.assertFalse(output.with_name('rng1.s').exists())
            self.assertIn('Gmlstubs_varSearch',output.with_name('builtins_gml1.s').read_text())

    def test_nonrelease_runner_without_release_only_paths(self):
        before = ('drawGMS1Backgrounds:\n bx lr\ndrawBackground:\n bx lr\ninitRoom:\n bx lr\n'
                  + ' bl drawGMS1Backgrounds\n'*2 + ' bl initRoom\n'*2)
        after, receipt = adapter.rewrite(before, 'runner.c', release=False)
        self.assertEqual(receipt['calls'], {'drawGMS1Backgrounds': 2, 'initRoom': 2})
        self.assertEqual(after.count(' bl Gmlstubs_drawLegacy\n'), 2)
        with self.assertRaises(AssertionError):
            adapter.rewrite(before, 'runner.c', release=True)


if __name__ == '__main__':
    unittest.main()
