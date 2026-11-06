"""Negative fixtures for the bounded position-table restoration adapter."""
from pathlib import Path
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audpar_compile as adapter


def function(name, label):
    number = int(label[2:])
    targets = [f'.L{i}' for i in range(number+1, number+5)]
    code = f'\t.section\t.text.{name},"ax",%progbits\n{name}:\n\tldr r0, [pc]\n.Lrtx{number}:\n'
    table = ('\t.section\t.rodata\n\t.align\t0\n'+label+':\n'+
             ''.join(f'\t.byte\t({target}-.Lrtx{number}-4)/4\n' for target in targets))
    tail = (f'\t.section\t.text.{name}\n'+''.join(target+':\n\tnop\n' for target in targets)+
            f'\tbx lr\n\t.word {label}\n\t.size\t{name}, .-{name}\n')
    return code, table, tail


GET = function(adapter.NAMES[0], '.L100')
SET = function(adapter.NAMES[1], '.L200')
SWAPPED = ''.join(SET+GET)
CANONICAL = SET[0]+GET[1]+SET[2]+GET[0]+SET[1]+GET[2]


class TableTest(unittest.TestCase):
    def test_offset_emission_moves_only_complete_groups(self):
        body = lambda n: (f"\t.align\t2\n\t.syntax unified\n\t.arm\n\t.type\t{n}, %function\n"
                          f"{n}:\n\tbx lr\n\t.size\t{n}, .-{n}\n")
        pool = lambda label,value: f'\t.section\t.rodata.str1.4\n\t.align\t2\n{label}:\n\t.ascii\t"{value}"\n'
        names = ('utaDecOpenMemory','utaChnReset','utaChnSetInterp','utaChnSetFormat')
        text = ('\t.section\t.text.late.utaudio2\n'+''.join(body(n) for n in names)+body('utaQueue')+
                '\t.section\t.text.late.utaudio2\n'+body('utaSetCallback')+
                '\t.section\t.text.flowburst_late\n'+body('CtrAudioSystem_chainFlowburst')+
                '\t.section\t.text.flowburst_late\n'+body('flowendPlaySound')+
                pool('.LC1','Audio: wanted to load audio group %d')+
                pool('.LC2',"Audio: read '%s' (%lu bytes) in the background")+
                pool('.LC3','FATAL: malloc(%zu) failed')+
                pool('.LC4','opener thread below it')+
                '\t.align\t2\n.LC5:\n\t.ascii\t"no opener thread"\n'+
                '\t.align\t2\n.LC6:\n\t.ascii\t"Audio: NDSP failed to start"\n'+
                pool('.LC7','Audio: invalid stream index %d'))
        actual = adapter.restore_offset_emission(text)
        for a,b in [('utaQueue:',names[0]+':'),(names[-1]+':','utaSetCallback:'),
                    ('flowendPlaySound:','CtrAudioSystem_chainFlowburst:'),
                    ('opener thread below it','Audio: wanted to load audio group'),
                    ('no opener thread','FATAL: malloc'),('FATAL: malloc','Audio: NDSP failed'),
                    ('Audio: invalid stream index',"Audio: read '%s'")]:
            self.assertLess(actual.index(a),actual.index(b))
        with self.assertRaisesRegex(AssertionError,'unqualified offset'):
            adapter.restore_offset_emission(text.replace('utaChnSetFormat','unknown'))
        new = text.replace(body(names[0]), body(names[0])+body('utaBuildSeam'))
        new = new.replace(body('utaQueue'),body('utaQueue')+body('utaFeed'))
        new = new.replace(body('utaSetCallback'),body('utaChnGetSamplePos')+body('utaSetCallback'))
        actual = adapter.restore_offset_emission(new)
        order = ('utaQueue','utaChnGetSamplePos','utaBuildSeam','utaFeed',*names,'utaSetCallback')
        offsets = [actual.index(name+':\n') for name in order]
        self.assertEqual(offsets,sorted(offsets))
        with self.assertRaisesRegex(AssertionError,'unqualified offset emission'):
            adapter.restore_offset_emission(new.replace('utaChnGetSamplePos','unknown'))

    def test_offsets_keep_placeholders_and_move_only_new_tables(self):
        names = ('audparGetTrackPosition', 'audparSetTrackPosition')
        get, setpos = function(names[0], '.L100'), function(names[1], '.L200')
        text = ''.join(setpos+get)
        for name in ('ctrInit', 'ctrPlaySound', 'flowendPlaySound'):
            text += f'\t.section .text.{name}\n{name}:\n\tbx lr\n\t.size {name}, .-{name}\n'
        actual, receipt = adapter.restore_offsets(text)
        self.assertIn('.section\t.rodata\n\t.byte\t56,21,6,0\n', actual)
        self.assertIn('.section\t.rodata\n\t.byte\t43,20,41,0\n', actual)
        self.assertEqual(actual.count('.section\t.rodata.late.audpar\n'), 2)
        self.assertIn('.space 1372-(.-ctrPlaySound), 0', actual)
        self.assertEqual(actual.count('\t.byte\t(.L'), 8)
        self.assertTrue(receipt['retained_slots'])
        diagnostic, receipt = adapter.restore_offsets(''.join(setpos+get), diagnostic=True)
        self.assertNotIn('.space', diagnostic)
        self.assertFalse(receipt['retained_slots'])

    def test_offsets_reject_unqualified_or_missing_slots(self):
        text = ''.join(function('audparGetTrackPosition', '.L100')+
                       function('audparSetTrackPosition', '.L200'))
        with self.assertRaisesRegex(AssertionError, 'retained offset slot'):
            adapter.restore_offsets(text)
        with self.assertRaisesRegex(AssertionError, 'unqualified'):
            adapter.restore_offsets(text.replace('.byte', '.word'), diagnostic=True)

    def test_only_complete_tables_move(self):
        actual, receipt = adapter.restore_tables(SWAPPED)
        self.assertEqual(actual, CANONICAL)
        self.assertTrue(receipt['changed'])
        self.assertEqual(receipt['tables'][adapter.NAMES[0]], '.L100')
        again, receipt = adapter.restore_tables(actual)
        self.assertEqual(again, actual)
        self.assertFalse(receipt['changed'])

    def test_original_order_is_unchanged(self):
        original = ''.join(GET+SET)
        actual, receipt = adapter.restore_tables(original)
        self.assertEqual(actual, original)
        self.assertFalse(receipt['changed'])

    def test_missing_and_duplicate_functions_fail(self):
        for text in (''.join(GET), SWAPPED+''.join(GET)):
            with self.subTest(text=text), self.assertRaisesRegex(AssertionError, 'position function'):
                adapter.restore_tables(text)

    def test_missing_and_duplicate_tables_fail(self):
        for text in (SWAPPED.replace(GET[1], ''), SWAPPED.replace(GET[1], GET[1]*2)):
            with self.subTest(text=text), self.assertRaisesRegex(AssertionError, 'position table'):
                adapter.restore_tables(text)

    def test_unknown_table_forms_fail(self):
        for table in (GET[1]+'\t.word 123\n', GET[1].replace('.align\t0', '.align\t2'),
                      GET[1].replace('\t.byte\t(.L101-.Lrtx100-4)/4\n', ''),
                      GET[1].replace('.Lrtx100', '.Lrtx999'),
                      GET[1].replace('.byte', '.word')):
            with self.subTest(table=table), self.assertRaisesRegex(AssertionError, 'unqualified'):
                adapter.restore_tables(SWAPPED.replace(GET[1], table))

    def test_missing_or_ambiguous_literal_reference_fails(self):
        for text in (SWAPPED.replace('\t.word .L100\n', ''),
                     SWAPPED.replace('\t.word .L200\n', '\t.word .L200\n\t.word .L100\n')):
            with self.subTest(text=text), self.assertRaisesRegex(AssertionError, 'table reference'):
                adapter.restore_tables(text)

    def test_base_and_target_must_belong_to_owner(self):
        for label in ('.Lrtx100', '.L101'):
            with self.subTest(label=label), self.assertRaisesRegex(AssertionError, 'target outside owner'):
                adapter.restore_tables(SWAPPED.replace(label+':\n', ''))

    def test_guard_delegates_other_builds(self):
        command = ['gcc', '-c', '/source/ctr_audio_system.c', '-o', 'audio.o',
                   '-DENABLE_WAD16', '-D__3DS__', '-DNDEBUG', '-O2']
        self.assertTrue(adapter.selected(command))
        for flag in command[5:]:
            with self.subTest(flag=flag), mock.patch.object(adapter, 'run', return_value=9) as run:
                other = [arg for arg in command if arg != flag]
                self.assertEqual(adapter.main(['delegate', adapter.MARKER]+other), 9)
                run.assert_called_once_with(['delegate']+other)
        self.assertFalse(adapter.selected([arg.replace('WAD16', 'WAD17') for arg in command]))
        self.assertFalse(adapter.selected([arg.replace('ctr_audio_system.c', 'main.c') for arg in command]))


if __name__ == '__main__':
    unittest.main()
