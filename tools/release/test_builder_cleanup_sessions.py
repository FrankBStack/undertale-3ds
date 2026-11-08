"""Build lifecycle, ancestor aliases and cleanup scale, with invented files only."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parent/'builder')]
import cleanup
import pipeline
import test_builder as fixture


class CleanupSessionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.work = self.base/'work'

    def link(self, path, target):
        try:
            path.symlink_to(target, target_is_directory=True)
        except OSError:
            if os.name != 'nt':
                self.skipTest('Host does not allow directory symlinks')
            command = "New-Item -ItemType Junction -Path '%s' -Target '%s' | Out-Null" % (
                str(path).replace("'", "''"), str(target).replace("'", "''"))
            result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',command],
                stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
        self.addCleanup(lambda: path.unlink() if path.is_symlink() else path.rmdir())

    def test_tmp_cache_and_home_ancestor_aliases_allow_launch_and_cleanup(self):
        for alias_name, tail in (('tmp','u3ds-plain'), ('.cache','u3ds'), ('home','player/.cache/u3ds')):
            with self.subTest(shape=alias_name):
                target = self.base/(alias_name.replace('.','')+'-real')
                target.mkdir()
                alias = self.base/alias_name
                self.link(alias,target)
                work = alias/tail
                lease = pipeline.claim_work(str(work))
                lease.release()
                area = work/'ccache'
                token = cleanup.begin_build(work,[area])
                area.mkdir()
                created = area/'invented.o'
                created.write_bytes(b'BUILDER')
                cleanup.finish_build(work,token)
                deleted,_ = cleanup.remove(cleanup.plan(work),['build'])
                self.assertIn(str(created.resolve()),deleted)
                self.assertFalse(created.exists())
                # A legitimate ancestor alias must not conceal a link inside work.
                outside = self.base/(alias_name.replace('.','')+'-outside')
                outside.mkdir()
                sentinel = outside/'sentinel'
                sentinel.write_bytes(b'KEEP')
                self.link(work/'src',outside)
                with self.assertRaises(pipeline.WorkLockError):
                    pipeline.claim_work(str(work))
                with self.assertRaises(ValueError):
                    pipeline.mirror_source(str(target),str(work/'src'),'undertale')
                self.assertEqual(sentinel.read_bytes(),b'KEEP')

    def run_build(self, case, target, result='success'):
        case.outputs = lambda *args, **kwargs: None
        build,_ = case.make(['[100%] Linking invented output\n'],rc=0 if result=='success' else 1)
        build.target = target
        original = build.popen
        def process(argv, **kwargs):
            bdir = Path(case.work)/'src/build'/('3ds-undertale-'+target)
            bdir.mkdir(parents=True,exist_ok=True)
            (bdir/'CMakeCache.txt').write_text('CTRPORT_AOT_DIR:PATH=/invented/aot\n',encoding='utf-8')
            (bdir/'generated').mkdir(exist_ok=True)
            (bdir/'generated/ctrport_build_id.h').write_text(
                '#pragma once\n#define CTRPORT_COMMIT_TEXT "%s"\n' % case.build_id,encoding='utf-8')
            (bdir/'object.o').write_bytes(b'OBJECT-'+target.encode())
            (bdir/('undertale-3ds-'+target+'.3dsx')).write_bytes(b'3DSX'*100)
            cache = Path(case.work)/'ccache'/target
            cache.mkdir(parents=True,exist_ok=True)
            (cache/'cache.o').write_bytes(b'CACHE-'+target.encode())
            if result == 'cancel':
                build.cancelled = True
            return original(argv,**kwargs)
        build.popen = process
        if result=='success':
            build.run()
        else:
            with self.assertRaises(pipeline.BuildFailed):
                build.run()
        return build

    def build_fixture(self):
        case = fixture.BuildTest('test_successful_build')
        case.setUp()
        self.addCleanup(case.doCleanups)
        self.addCleanup(case.tearDown)
        return case

    def test_real_run_records_both_models_and_keeps_later_personal_additions(self):
        case = self.build_fixture()
        self.run_build(case,'o3ds')
        personal = Path(case.work)/'ccache/personal.txt'
        personal.write_bytes(b'PLAYER')
        self.run_build(case,'n3ds')
        plan = cleanup.plan(case.work)
        selected = {item.path for item in plan.files}
        for target in ('o3ds','n3ds'):
            self.assertIn(str(Path(case.work)/'ccache'/target/'cache.o'),selected)
            self.assertIn(str(Path(case.work)/'src/build'/('3ds-undertale-'+target)/'object.o'),selected)
        cleanup.remove(plan,['build'])
        self.assertEqual(personal.read_bytes(),b'PLAYER')
        self.assertTrue((Path(case.work)/'out/o3ds/undertale-3ds-o3ds.3dsx').is_file())
        self.assertTrue((Path(case.work)/'out/n3ds/undertale-3ds-n3ds.3dsx').is_file())

    def test_real_run_records_failed_and_cancelled_builds_then_retry(self):
        for result in ('failure','cancel'):
            with self.subTest(result=result):
                case = self.build_fixture()
                self.run_build(case,'n3ds',result)
                cache = Path(case.work)/'ccache/n3ds/cache.o'
                self.assertIn(str(cache),{f.path for f in cleanup.plan(case.work).files})
                self.run_build(case,'n3ds')
                deleted,_ = cleanup.remove(cleanup.plan(case.work),['build'])
                self.assertIn(str(cache),deleted)
                self.assertFalse(cache.exists())

    def test_preexisting_and_edited_files_never_gain_ownership_on_a_later_build(self):
        area = self.work/'ccache'
        area.mkdir(parents=True)
        personal = area/'personal'
        personal.write_bytes(b'PLAYER')
        token = cleanup.begin_build(self.work,[area])
        created = area/'created.o'
        created.write_bytes(b'BUILD')
        cleanup.finish_build(self.work,token)
        created.write_bytes(b'PLAYER EDIT')
        token = cleanup.begin_build(self.work,[area])
        created.write_bytes(b'STILL KEPT')
        cleanup.finish_build(self.work,token)
        self.assertEqual(cleanup.plan(self.work).files,[])
        self.assertEqual(personal.read_bytes(),b'PLAYER')
        self.assertEqual(created.read_bytes(),b'STILL KEPT')

    def test_large_unknown_and_owned_areas_have_bounded_previews(self):
        area = self.work/'ccache'
        area.mkdir(parents=True)
        for number in range(512):
            (area/str(number)).write_bytes(b'PLAYER')
        plan = cleanup.plan(self.work)
        self.assertEqual(plan.files,[])
        self.assertLessEqual(len(plan.kept),2)
        self.assertIn('512 files',plan.preview(['build']))
        token = cleanup.begin_build(self.work,[area])
        for number in range(512):
            (area/('owned-'+str(number))).write_bytes(b'BUILDER')
        cleanup.finish_build(self.work,token)
        plan = cleanup.plan(self.work)
        self.assertEqual(len(plan.files),512)
        self.assertLess(len(plan.preview(['build'])),2048)
        self.assertIn('512 files',plan.preview(['build']))
        with mock.patch.object(Path,'unlink',side_effect=PermissionError('invented refusal')):
            deleted,kept = cleanup.remove(plan,['build'])
        self.assertEqual(deleted,[])
        self.assertLess(len(kept),4)
        self.assertIn("couldn't delete it",'\n'.join(kept))

    def test_link_walk_checks_files_once_instead_of_rechecking_every_ancestor(self):
        area = self.work/'ccache/deep/nested'
        area.mkdir(parents=True)
        for number in range(64):
            (area/str(number)).write_bytes(b'X')
        original = Path.lstat
        calls = []
        def count(path,*args,**kwargs):
            calls.append(path)
            return original(path,*args,**kwargs)
        with mock.patch.object(Path,'lstat',count):
            cleanup.require_work_paths(self.work)
        self.assertLess(len(calls),64)

    def test_only_the_recorded_private_package_temporary_is_reclaimable(self):
        folder = self.work/'out/n3ds'
        folder.mkdir(parents=True)
        handle, name = tempfile.mkstemp(prefix='.package.',suffix='.part',dir=folder)
        os.close(handle)
        staged = Path(name)
        cleanup.record_temporary(self.work,staged)
        staged.write_bytes(b'INTERRUPTED COPY')
        unknown = folder/'.personal.part'
        unknown.write_bytes(b'PLAYER')
        package = folder/'finished.3dsx'
        package.write_bytes(b'FINISHED')
        deleted,_ = cleanup.remove(cleanup.plan(self.work),['build'])
        self.assertEqual(deleted,[str(staged)])
        self.assertEqual(unknown.read_bytes(),b'PLAYER')
        self.assertEqual(package.read_bytes(),b'FINISHED')

    def test_real_collect_abrupt_exit_leaves_a_recorded_reclaimable_copy(self):
        script = self.base/'interrupted.py'
        module_dir = Path(__file__).resolve().parent/'builder'
        source_root = Path(__file__).resolve().parents[2]
        script.write_text('''from pathlib import Path
import os, sys
from types import SimpleNamespace
sys.path.insert(0, %r)
import pipeline, products
work = Path(%r)
bdir = work/'src/build/3ds-undertale-n3ds'
bdir.mkdir(parents=True)
(bdir/'CMakeCache.txt').write_text('CTRPORT_AOT_DIR:PATH=/invented/aot\\n')
stem = products.package_stem(products.PRODUCTS['undertale'],'n3ds',%r)
(bdir/(stem+'.3dsx')).write_bytes(b'COMPILED'*100)
out = work/'out/n3ds'
out.mkdir(parents=True)
(out/(stem+'.3dsx')).write_bytes(b'PREVIOUS')
job = pipeline.Build.__new__(pipeline.Build)
job.work, job.product, job.target = str(work), products.PRODUCTS['undertale'], 'n3ds'
job.source_root, job.outputs = %r, ('3dsx',)
job.tc, job.log_path = SimpleNamespace(can_cia=True), 'unused'
def stopped(source, destination):
    Path(destination).write_bytes(b'PARTIAL')
    os._exit(23)
pipeline.shutil.copy2 = stopped
job.collect()
''' % (str(module_dir),str(self.work),str(source_root),str(source_root)),encoding='utf-8')
        result = subprocess.run([sys.executable,'-X','utf8','-I','-B',str(script)],
            stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,23,result.stderr)
        plan = cleanup.plan(self.work)
        staged = list((self.work/'out/n3ds').glob('.*.part'))
        self.assertEqual(len(staged),1)
        self.assertIn(str(staged[0]),{item.path for item in plan.files})
        cleanup.remove(plan,['build'])
        self.assertFalse(staged[0].exists())
        self.assertEqual(next((self.work/'out/n3ds').glob('*.3dsx')).read_bytes(),b'PREVIOUS')

    def test_replacing_a_recorded_temporary_does_not_adopt_the_replacement(self):
        folder = self.work/'out/n3ds'
        folder.mkdir(parents=True)
        handle,name = tempfile.mkstemp(prefix='.package.',suffix='.part',dir=folder)
        os.close(handle)
        staged = Path(name)
        cleanup.record_temporary(self.work,staged)
        other = folder/'player'
        other.write_bytes(b'PLAYER')
        os.replace(other,staged)
        self.assertNotIn(str(staged),{item.path for item in cleanup.plan(self.work).files})
        cleanup.remove(cleanup.plan(self.work),['build'])
        self.assertEqual(staged.read_bytes(),b'PLAYER')


if __name__ == '__main__':
    unittest.main()
