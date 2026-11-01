import importlib.util
import hashlib
import io
import marshal
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('hygiene', Path(__file__).with_name('check_kit_hygiene.py'))
hygiene = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hygiene)


class KitHygieneTests(unittest.TestCase):
    def test_private_identity_all_binary_encodings_and_offsets(self):
        for value in ('delta'+'tale', 'Eth'+'an'):
            for encoding in ('ascii', 'utf-16le', 'utf-16be'):
                for prefix in (b'', b'\x01'):
                    with self.subTest(encoding=encoding, prefix=prefix):
                        self.assertTrue(hygiene.findings({'file.bin': prefix+value.encode(encoding)}))

    def test_private_profile_workspace_unc_all_encodings(self):
        paths = ('Q:'+r'\workspace\tree', 'Q:'+'/AI/tree', r'\\private-pc\share',
                 '/'+'home/user/tree', 'C:'+r'\Users\account\tree', '/'+'Users/account/tree',
                 'relative/'+'.cl'+'aude/tree', 'relative/work'+'trees/project',
                 'relative/scratch/'+'agents/run')
        for value in paths:
            for encoding in ('ascii','utf-16le','utf-16be'):
                with self.subTest(path=value, encoding=encoding):
                    hits = hygiene.findings({'payload':b'\x01'+value.encode(encoding)})
                    self.assertTrue(any(h['rule'].startswith('private-') for h in hits))

    def test_os_sdk_defaults_placeholders_and_shebangs(self):
        values = ['/usr/bin/env', '/bin/sh', '/dev/null', '/System/Library/Frameworks',
                  'C:'+r'\Windows\System32', 'C:/devkitPro/bin', 'C:/msys64/ucrt64',
                  '%APPDATA%/builder', '${HOME}/builder']
        for value in values:
            with self.subTest(value=value):
                self.assertEqual(hygiene.findings({'launcher.sh':('#!'+value+'\n').encode()}), [])

    def test_approved_credit_notice_files_only(self):
        text = ('N'+'Eth'+'an Cawse\n').encode()
        for name in ('kit/docs/release/credits-port.txt', 'THIRD_PARTY_NOTICES',
                     'LICENSE', 'vendor/component/NOTICE.txt', 'vendor/component/LICENSE-MIT'):
            self.assertEqual(hygiene.findings({name:text}), [], name)
        for name in ('credits.txt', 'not-LICENSE.txt', 'tool.py', 'vendor/component/README.md'):
            self.assertTrue(hygiene.findings({name:b'# '+text}), name)

    def test_notice_and_vendor_paths_cannot_hide_private_profile(self):
        for name in ('LICENSE', 'kit/tools/release/builder/runtime/vendor.py'):
            self.assertTrue(hygiene.findings({name:('# /'+'home/private/build').encode()}))

    def test_comment_attribution_in_python_c_and_docstrings(self):
        words = ('lan'+'e worker', '(lan'+'e worker)', 'lead '+'ruling', 'cla'+'ude',
                 'co'+'dex', 'g'+'pt-6.1', 'gem'+'ini', 'op'+'us 5.5')
        for word in words:
            for name, text in [('module.py', '# '+word+'\nx=1\n'),
                               ('module.c', 'int x; /* '+word+' */\n'),
                               ('module.py', '"""'+word+'"""\nx=1\n')]:
                with self.subTest(word=word, name=name):
                    self.assertTrue(any(h['rule']=='internal-attribution'
                                        for h in hygiene.findings({name:text.encode()})))

    def test_attribution_in_code_and_binary_data_is_not_comment(self):
        self.assertEqual(hygiene.findings({'module.py':b'assert la'+b'ne in kinds\n'}), [])
        self.assertEqual(hygiene.findings({'unicodedata.pyd':b'\x00LA'+b'NE M\x18P'}), [])
        self.assertEqual(hygiene.findings({'platform.py':b'# The Op'+b'us Magnum of platform strings\n'}), [])

    def test_public_handle_and_relative_paths(self):
        value = b'engine/src/file.c https://github.com/ethancawse/undertale-3ds '
        self.assertEqual(hygiene.findings({'relative.txt':value}), [])
        handle = ('https://github.com/'+'delta'+'tale/port').encode()
        self.assertEqual(hygiene.findings({'links.txt':handle}), [])
        self.assertTrue(hygiene.findings({'links.txt':handle+b'-private '+b'delta'+b'tale'}))

    def test_real_nested_bytecode_checks_all_code_filenames(self):
        private = 'Q:/AI/project/module.py'
        code = compile('def nested():\n    return 1\n', private, 'exec')
        pyc = importlib.util.MAGIC_NUMBER + bytes(12) + marshal.dumps(code)
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('module.pyc', pyc)
        hits = hygiene.findings({'stdlib.zip':data.getvalue()})
        self.assertTrue(any(h['encoding']=='co_filename' and
                            h['member']=='stdlib.zip!module.pyc' for h in hits))
        clean = compile('x=1', 'module.py', 'exec')
        self.assertEqual(hygiene.findings({'module.pyc':importlib.util.MAGIC_NUMBER+
                                          bytes(12)+marshal.dumps(clean)}), [])

    def test_vendor_tutorial_exception_requires_exact_bytes_and_member(self):
        name='runtime/stdlib.zip!tutorial.txt'
        data=('/'+'home/TutorialUser/example').encode()
        review=(('tutorial.txt',hashlib.sha256(data).hexdigest(),r'^[/]home[/]TutorialUser[/]',
                 'Synthetic hash-bound tutorial regression'),)
        with patch.object(hygiene,'REVIEWED_VENDOR_EXAMPLES',review):
            self.assertEqual(hygiene.findings({name:data}),[])
            self.assertEqual(hygiene.findings({'runtime/python3.14/tutorial.txt':data}),[])
            self.assertTrue(hygiene.findings({'runtime/python3.14/tutorial.txt':data+b' changed'}))
            self.assertTrue(hygiene.findings({name:data+b' changed'}))
            self.assertTrue(hygiene.findings({'other.txt':data}))

    def test_cli_directory_returns_nonzero_for_leak(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)
            (path/'data.bin').write_bytes(b'delta'+b'tale')
            self.assertEqual(hygiene.main([str(path)]),1)

    def test_malformed_python_source_is_not_exempted(self):
        with self.assertRaisesRegex(ValueError, 'Cannot inspect source comments'):
            hygiene.findings({'runtime/fixture.py': b'runtime fixture'})

    def test_malformed_nested_bytecode_is_not_exempted(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as archive:
            archive.writestr('module.pyc', b'not bytecode')
        with self.assertRaisesRegex(ValueError, 'Unsupported bytecode magic'):
            hygiene.findings({'runtime/stdlib.zip': stream.getvalue()})


if __name__ == '__main__':
    unittest.main()
