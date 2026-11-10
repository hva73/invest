import importlib.util,os,sqlite3,subprocess,tempfile,unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('nordicway_release_preflight',Path(__file__).resolve().parents[1]/'tools/nordicway_release_preflight.py')
preflight=importlib.util.module_from_spec(spec);spec.loader.exec_module(preflight)

class Preflight(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.checkout=self.root/'checkout';self.target=self.root/'app';self.checkout.mkdir();(self.target/'var').mkdir(parents=True)
  with sqlite3.connect(self.target/'var/escape.db') as db:db.execute('CREATE TABLE preserved(value TEXT)');db.execute("INSERT INTO preserved VALUES('private-data')")
  self.git('init','-q');self.git('config','user.name','Test');self.git('config','user.email','test@example.invalid')
  (self.checkout/'apply_update.py').write_text("FILES=('app.py','BUILD_COMMIT')\n")
  (self.checkout/'app.py').write_text('safe code\n');(self.checkout/'BUILD_COMMIT').write_text('$Format:%H$\n')
  self.git('add','.');self.git('commit','-qm','test');self.sha=self.git('rev-parse','HEAD').strip()
 def tearDown(self):self.tmp.cleanup()
 def git(self,*args):return subprocess.run(['git','-C',str(self.checkout),*args],check=True,capture_output=True,text=True,env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_TERMINAL_PROMPT':'0'}).stdout
 def test_preflight_is_read_only_and_cannot_approve_release(self):
  db=self.target/'var/escape.db';before=db.read_bytes();result=preflight.inspect(self.checkout,self.target,self.sha)
  self.assertEqual(result['status'],'blocked');self.assertEqual(result['requested_sha'],self.sha);self.assertEqual(result['manifest_files'],2)
  self.assertIn('passenger_quiesce_unverified',result['blockers']);self.assertIn('release_gate_not_implemented',result['blockers']);self.assertEqual(result['account_quota'],'unknown')
  self.assertEqual(db.read_bytes(),before);self.assertNotIn('private-data',str(result));self.assertEqual(self.git('status','--porcelain'),'')
 def test_invalid_sha_dirty_checkout_and_hidden_modification_fail_closed(self):
  self.assertEqual(preflight.inspect(self.checkout,self.target,'$(touch BAD)')['reason'],'invalid_sha')
  self.assertEqual(preflight.inspect(self.checkout,self.target,'b'*40)['reason'],'checkout_sha_mismatch')
  (self.checkout/'app.py').write_text('modified\n');self.assertEqual(preflight.inspect(self.checkout,self.target,self.sha)['reason'],'checkout_not_clean')
  self.git('checkout','--','app.py');self.git('update-index','--assume-unchanged','app.py');(self.checkout/'app.py').write_text('modified\n')
  self.assertEqual(preflight.inspect(self.checkout,self.target,self.sha)['reason'],'manifest_file_mismatch')
 def test_manifest_is_literal_only_and_symlinks_are_rejected(self):
  marker=self.root/'should-not-exist';(self.checkout/'apply_update.py').write_text("FILES=__import__('os').system('touch "+str(marker)+"')\n")
  with self.assertRaisesRegex(ValueError,'manifest_invalid'):preflight.manifest(self.checkout)
  self.assertFalse(marker.exists())
  (self.checkout/'apply_update.py').write_text("FILES=('app.py','BUILD_COMMIT')\n");(self.checkout/'app.py').unlink();(self.checkout/'app.py').symlink_to(self.root/'outside')
  self.git('add','.');self.git('commit','-qm','symlink');sha=self.git('rev-parse','HEAD').strip()
  self.assertEqual(preflight.inspect(self.checkout,self.target,sha)['reason'],'manifest_symlink')
 def test_database_directory_symlink_is_rejected(self):
  outside=self.root/'outside';outside.mkdir();(self.target/'var/escape.db').rename(outside/'escape.db');(self.target/'var').rmdir();(self.target/'var').symlink_to(outside,target_is_directory=True)
  self.assertEqual(preflight.inspect(self.checkout,self.target,self.sha)['reason'],'database_unavailable')
 def test_installed_file_comparison_is_read_only_and_does_not_claim_running_version(self):
  (self.target/'app.py').write_text('safe code\n');(self.target/'BUILD_COMMIT').write_text(self.sha+'\n')
  result=preflight.inspect(self.checkout,self.target,self.sha)
  self.assertEqual(result['installed_files_checked'],2);self.assertEqual(result['installed_files_matching'],2)
  self.assertEqual(result['runtime_version'],'unknown');self.assertEqual(result['status'],'blocked')
  (self.target/'app.py').write_text('other code\n')
  self.assertEqual(preflight.inspect(self.checkout,self.target,self.sha)['installed_files_matching'],1)
  (self.target/'app.py').unlink();(self.target/'app.py').symlink_to(self.checkout/'app.py')
  self.assertEqual(preflight.inspect(self.checkout,self.target,self.sha)['installed_files_matching'],1)
if __name__=='__main__':unittest.main()
