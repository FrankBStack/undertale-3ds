"""Package-copy fault injection, using invented compiler output only."""
from pathlib import Path
import errno
import hashlib
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent/'builder'))
import pipeline
import products


class CollectSafetyTests(unittest.TestCase):
    def fixture(self, kind):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        work = Path(temporary.name)
        product = products.PRODUCTS['undertale']
        source_root = str(Path(__file__).resolve().parents[2])
        stem = products.package_stem(product, 'n3ds', source_root)
        bdir = work/'src/build/3ds-undertale-n3ds'
        bdir.mkdir(parents=True)
        (bdir/'CMakeCache.txt').write_text('CTRPORT_AOT_DIR:PATH=/invented/aot\n', encoding='utf-8')
        compiled = bdir/(stem+'.'+kind)
        compiled.write_bytes(b'COMPILED-PACKAGE'*100)
        final = work/'out/n3ds'/compiled.name
        final.parent.mkdir(parents=True)
        final.write_bytes(b'PREVIOUS-PACKAGE')
        job = pipeline.Build.__new__(pipeline.Build)
        job.work, job.product, job.target = str(work), product, 'n3ds'
        job.source_root, job.outputs = source_root, (kind,)
        job.tc = SimpleNamespace(can_cia=True)
        job.log_path, job.notices, job.on_line = str(work/'unused.log'), [], lambda line: None
        return job, compiled, final

    def test_partial_copy_preserves_the_previous_package(self):
        for kind in ('3dsx', 'cia'):
            with self.subTest(kind=kind):
                job, compiled, final = self.fixture(kind)
                before = compiled.read_bytes()
                def interrupted(src, dst):
                    self.assertNotEqual(Path(dst), final)
                    Path(dst).write_bytes(Path(src).read_bytes()[:4])
                    raise OSError(errno.ENOSPC, 'invented disk full')
                with mock.patch.object(pipeline.shutil, 'copy2', side_effect=interrupted):
                    with self.assertRaises(pipeline.BuildFailed):
                        job.collect()
                self.assertEqual(final.read_bytes(), b'PREVIOUS-PACKAGE')
                self.assertEqual(compiled.read_bytes(), before)
                self.assertEqual(list(final.parent.iterdir()), [final])

    def test_same_length_damage_and_source_changes_are_not_published(self):
        for kind in ('3dsx', 'cia'):
            for changed_source in (False, True):
                with self.subTest(kind=kind, changed_source=changed_source):
                    job, compiled, final = self.fixture(kind)
                    def damaged(src, dst):
                        data = Path(src).read_bytes()
                        Path(dst).write_bytes(data if changed_source else b'BAD!'+data[4:])
                        if changed_source:
                            Path(src).write_bytes(b'NEW!'+data[4:])
                    with mock.patch.object(pipeline.shutil, 'copy2', side_effect=damaged):
                        with self.assertRaises(pipeline.BuildFailed):
                            job.collect()
                    self.assertEqual(final.read_bytes(), b'PREVIOUS-PACKAGE')
                    self.assertEqual(list(final.parent.iterdir()), [final])

    def test_sync_and_rename_failures_keep_previous_output(self):
        for operation in ('fsync', 'replace'):
            with self.subTest(operation=operation):
                job, compiled, final = self.fixture('3dsx')
                with mock.patch.object(pipeline.os, operation, side_effect=OSError(errno.EIO, 'invented I/O error')):
                    with self.assertRaises(pipeline.BuildFailed):
                        job.collect()
                self.assertEqual(final.read_bytes(), b'PREVIOUS-PACKAGE')
                self.assertEqual(list(final.parent.iterdir()), [final])

    def test_success_returns_the_verified_compiler_bytes_and_digest(self):
        for kind in ('3dsx', 'cia'):
            with self.subTest(kind=kind):
                job, compiled, final = self.fixture(kind)
                data = compiled.read_bytes()
                artifacts = job.collect()
                self.assertEqual(final.read_bytes(), data)
                self.assertEqual(artifacts[0].sha256, hashlib.sha256(data).hexdigest())
                self.assertEqual(artifacts[0].size, len(data))
                self.assertEqual(list(final.parent.iterdir()), [final])


if __name__ == '__main__':
    unittest.main()
