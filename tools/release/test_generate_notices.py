"""Notice generation uses source texts, fails closed, and follows the export scope."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location('notices', Path(__file__).with_name('generate_notices.py'))
notices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(notices)


class NoticeTests(unittest.TestCase):
    def setUp(self):
        (notices.ROOT / 'scratch').mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=notices.ROOT / 'scratch')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'engine/vendor/example').mkdir(parents=True)
        self.license = self.root / 'engine/vendor/example/LICENSE'
        self.license.write_text('Actual upstream terms\n', encoding='utf-8')
        self.manifest = self.root / 'manifest'
        self.manifest.write_text('engine/vendor/example/LICENSE\n', encoding='utf-8')
        self.catalogue = self.root / 'catalogue'
        self.catalogue.write_text(json.dumps({'components': [{
            'name': 'example', 'license': 'Example', 'paths': ['engine/vendor/example/'],
            'provenance': 'test fixture', 'texts': [{'file': 'engine/vendor/example/LICENSE'}]
        }]}), encoding='utf-8')

    def render(self):
        return notices.generate(self.root, self.manifest, self.catalogue)

    def test_source_changes_propagate_deterministically(self):
        self.assertEqual(self.render(), self.render())
        self.assertIn('Actual upstream terms', self.render())
        self.license.write_text('Changed upstream terms\n', encoding='utf-8')
        self.assertIn('Changed upstream terms', self.render())
        self.assertNotIn('Actual upstream terms', self.render())

    def test_manifest_selects_components(self):
        self.manifest.write_text('', encoding='utf-8')
        self.assertNotIn('Actual upstream terms', self.render())

    def test_unknown_vendor_is_rejected(self):
        source = self.root / 'engine/vendor/unknown.c'
        source.write_text('int x;', encoding='utf-8')
        self.manifest.write_text('engine/vendor/unknown.c\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'uncatalogued'):
            self.render()

    def test_missing_notice_source_is_rejected(self):
        self.catalogue.write_text(self.catalogue.read_text().replace('example/LICENSE"}', 'example/MISSING"}'))
        with self.assertRaisesRegex(ValueError, 'absent from export'):
            self.render()

    def test_traversal_is_rejected(self):
        self.manifest.write_text('../outside\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'unsafe'):
            self.render()

    def test_checked_in_bundle_is_current(self):
        for game in ('ut', 'dr'):
            with self.subTest(game=game):
                manifest = notices.ROOT / ('tools/release/manifest-' + game + '.txt')
                if not manifest.is_file():
                    self.skipTest('This source export does not include the ' + game + ' manifest')
                self.assertEqual(notices.bundle_path(notices.ROOT, manifest).read_text(encoding='utf-8'),
                                 notices.generate(notices.ROOT, manifest,
                                                  notices.ROOT / 'tools/release/notices.json'))

    def test_notice_map_is_unique_and_stays_inside_tree(self):
        self.manifest.write_text('#map THIRD_PARTY_NOTICES <- engine/vendor/example/LICENSE\n')
        self.assertEqual(notices.bundle_path(self.root, self.manifest), self.license)
        for mapping in ('../outside', 'engine/vendor/example/LICENSE\n#map THIRD_PARTY_NOTICES <- LICENSE'):
            self.manifest.write_text('#map THIRD_PARTY_NOTICES <- ' + mapping + '\n')
            with self.assertRaises(ValueError):
                notices.bundle_path(self.root, self.manifest)

    def test_each_game_uses_the_same_notice_bytes_in_mirror_payload_and_legal_pages(self):
        import sys
        sys.path.insert(0, str(notices.ROOT / 'tools/release/builder'))
        import pipeline
        import prepare_legal
        for game, short in (('undertale', 'ut'), ('deltarune', 'dr')):
            manifest = notices.ROOT / ('tools/release/manifest-' + short + '.txt')
            if not manifest.is_file():
                continue
            expected = notices.generate(notices.ROOT, manifest, notices.ROOT / 'tools/release/notices.json').encode()
            with mock.patch.object(pipeline, 'SOURCE_DIRS', ()), \
                 mock.patch.object(pipeline, 'SOURCE_FILES', ('THIRD_PARTY_NOTICES',)):
                destination = self.root / game
                pipeline.mirror_source(notices.ROOT, destination, game)
                self.assertEqual((destination / 'THIRD_PARTY_NOTICES').read_bytes(), expected)
                self.assertEqual(pipeline.source_payload(notices.ROOT, game)['THIRD_PARTY_NOTICES'], expected)
                self.assertEqual(pipeline.source_input(destination, 'THIRD_PARTY_NOTICES', game).read_bytes(), expected)
            legal = self.root / (game + '-legal')
            prepare_legal.prepare(notices.ROOT, legal, pipeline.source_input(notices.ROOT, 'THIRD_PARTY_NOTICES', game))
            self.assertEqual((legal / 'THIRD_PARTY_NOTICES').read_bytes(), expected)
            self.assertEqual(b'PacketVideo' in expected, game == 'deltarune')

    def test_release_rejects_stale_mapped_notices_even_when_root_is_current(self):
        import contextlib
        import io
        import sys
        import check_release as gate
        (self.root / 'THIRD_PARTY_NOTICES').write_text('current')
        (self.root / 'scoped.txt').write_text('stale')
        manifest = self.root / 'manifest-ut.txt'
        manifest.write_text('#map THIRD_PARTY_NOTICES <- scoped.txt\nTHIRD_PARTY_NOTICES\n')
        stderr = io.StringIO()
        with mock.patch.object(gate, 'ROOT', self.root), \
             mock.patch.object(sys, 'argv', ['check_release.py', '--manifest', 'manifest-ut.txt']), \
             mock.patch.object(gate, 'read_manifest', return_value=(['THIRD_PARTY_NOTICES'], {}, {'THIRD_PARTY_NOTICES': 'scoped.txt'})), \
             mock.patch.object(gate.import_closure, 'Repository'), \
             mock.patch.object(gate.import_closure, 'check', return_value={'missing': []}), \
             mock.patch.object(gate.generate_notices, 'generate', return_value='current'), \
             contextlib.redirect_stderr(stderr):
            self.assertEqual(gate.main(), 2)
        self.assertIn('THIRD_PARTY_NOTICES is stale', stderr.getvalue())
        self.assertEqual(list((self.root / 'scratch').iterdir()), [])

    def test_builder_ca_bundle_is_named_in_both_export_notices(self):
        for game in ('ut','dr'):
            with self.subTest(game=game):
                manifest=notices.ROOT/('tools/release/manifest-'+game+'.txt')
                if not manifest.is_file():
                    self.skipTest('This source export does not include the '+game+' manifest')
                text=notices.generate(notices.ROOT,manifest,
                    notices.ROOT/'tools/release/notices.json')
                self.assertIn('Mozilla CA certificates from certifi (builder HTTPS)',text)
                self.assertIn('Source: tools/release/builder/certs/LICENSE.certifi',text)
                self.assertIn('Licence: MPL-2.0',text)

    def test_empty_notice_and_empty_source_fail(self):
        self.license.write_text(' \n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'empty licence'):
            self.render()
        data = json.loads(self.catalogue.read_text())
        data['components'][0]['texts'] = []
        self.catalogue.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'no licence source'):
            self.render()

    def test_file_prefix_cannot_cover_another_vendor_file(self):
        data = json.loads(self.catalogue.read_text())
        data['components'][0]['paths'] = ['engine/vendor/example/LICENSE']
        self.catalogue.write_text(json.dumps(data))
        (self.root / 'engine/vendor/example/LICENSE-extra').write_text('fixture')
        self.manifest.write_text('engine/vendor/example/LICENSE-extra\n')
        with self.assertRaisesRegex(ValueError, 'uncatalogued'):
            self.render()

    def test_linked_library_without_notice_fails_including_variable_lists(self):
        path = self.root / 'platform/3ds/CMakeLists.txt'
        path.parent.mkdir(parents=True)
        path.write_text('find_library(OGG_LIBRARY ogg)\nset(AUDIO ${OGG_LIBRARY})\n'
                        'list(APPEND AUDIO unknownlib)\ntarget_link_libraries(app PRIVATE ${AUDIO})\n')
        self.manifest.write_text(self.manifest.read_text() + 'platform/3ds/CMakeLists.txt\n')
        with self.assertRaisesRegex(ValueError, 'linked libraries without notices: .*unknownlib'):
            self.render()
        data = json.loads(self.catalogue.read_text())
        data['components'][0]['link_names'] = ['ogg', 'unknownlib', 'gcc', 'c', 'sysbase', '3dsx_crt0']
        self.catalogue.write_text(json.dumps(data))
        self.assertIn('Actual upstream terms', self.render())
        path.write_text('target_link_libraries(app PRIVATE ${MISSING})\n')
        with self.assertRaisesRegex(ValueError, 'unresolved linked-library'):
            self.render()


if __name__ == '__main__':
    unittest.main()
