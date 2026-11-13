import importlib.util, os, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('prepare_first',Path(__file__).resolve().parents[1]/'tools/nordicway_prepare_first_release.py')
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class TestFirstRelease(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
  self.bridge=self.root/'.escape_deploy_bridge';self.bridge.mkdir(mode=0o700)
  self.app=self.root/'escape_app';(self.app/'var').mkdir(parents=True)
  (self.app/'BUILD_COMMIT').write_text(p.INSTALLED+'\n');(self.app/'requirements.txt').write_bytes(b'reqs')
  self.old={name:(b'# '+name.encode()+b'\n') for name in (*p.MODULES,'apply_update.py')}
  for name,data in self.old.items(): (self.bridge/name).write_bytes(data);(self.bridge/name).chmod(0o600)
  for name,data in [('deploy-enabled',b'1\n'),('approved-sha',(b'a'*40+b'\n'))]:
   (self.bridge/name).write_bytes(data);(self.bridge/name).chmod(0o600)
  self.updater=b'FILES=("a",)\n';self.blob=patch.object(p,'UPDATER_BLOB',p.blob(self.updater));self.blob.start();self.addCleanup(self.blob.stop)
 def run_prepare(self, inspect=lambda guard:True): return p.prepare(self.root,self.updater,b'reqs',self.old,inspect=inspect)
 def test_success(self):
  self.assertEqual(self.run_prepare()['status'],'prepared')
  self.assertEqual((self.bridge/'apply_update.py').read_bytes(),self.updater)
  self.assertEqual((self.bridge/'approved-sha').read_text().strip(),p.RELEASE)
  self.assertEqual((self.bridge/'deploy-enabled').read_bytes(),b'1\n')
  self.assertEqual((self.bridge/'first-release-updater-backup').read_bytes(),self.old['apply_update.py'])
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
 def test_existing_recovery_is_not_touched(self):
  m=self.bridge/'deployment-incomplete.json';m.write_text('keep');m.chmod(0o600)
  with self.assertRaisesRegex(ValueError,'recovery_required'):self.run_prepare()
  self.assertEqual(m.read_text(),'keep');self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_active_guard_leaves_gate_closed_and_marker(self):
  with self.assertRaisesRegex(ValueError,'guard_in_flight'):self.run_prepare(lambda _:False)
  self.assertFalse((self.bridge/'deploy-enabled').exists())
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertEqual((self.bridge/'apply_update.py').read_bytes(),self.old['apply_update.py'])
 def test_incorrect_requirements_leave_gate_untouched(self):
  (self.app/'requirements.txt').write_bytes(b'other')
  with self.assertRaisesRegex(ValueError,'requirements_changed'):self.run_prepare()
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_bridge_change_is_rejected(self):
  (self.bridge/'nordicway_deploy_runner.py').write_bytes(b'changed')
  with self.assertRaisesRegex(ValueError,'bridge_changed'):self.run_prepare()
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_source_tamper_is_rejected(self):
  with self.assertRaisesRegex(ValueError,'candidate_mismatch'):p.prepare(self.root,b'bad',b'reqs',self.old,inspect=lambda _:True)
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_scan_finds_exact_guard_argument(self):
  proc=self.root/'proc';(proc/'123456').mkdir(parents=True)
  (proc/'123456'/'cmdline').write_bytes(b'python\0'+os.fsencode(str(self.bridge/'nordicway_deploy_guard.py'))+b'\0')
  self.assertFalse(p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc))
  (proc/'123456'/'cmdline').write_bytes(b'python\0other.py\0')
  self.assertTrue(p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc))
if __name__=='__main__':unittest.main()
