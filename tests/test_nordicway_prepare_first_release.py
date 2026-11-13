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
  self.updater=b'FILES=("a",)\n';self.release='b'*40;self.blob=p.blob(self.updater)
 def run_prepare(self, inspect=lambda guard:True): return p.prepare(self.root,self.release,self.blob,self.updater,b'reqs',self.old,inspect=inspect)
 def test_success(self):
  self.assertEqual(self.run_prepare()['status'],'prepared')
  self.assertEqual((self.bridge/'apply_update.py').read_bytes(),self.updater)
  self.assertEqual((self.bridge/'approved-sha').read_text().strip(),self.release)
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
  with self.assertRaisesRegex(ValueError,'candidate_mismatch'):p.prepare(self.root,self.release,self.blob,b'bad',b'reqs',self.old,inspect=lambda _:True)
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_interrupted_update_leaves_gate_closed_and_marker(self):
  original=p.atomic
  def fail_on_approval(parent,name,data):
   if name=='approved-sha': raise OSError('simulated interruption')
   return original(parent,name,data)
  with patch.object(p,'atomic',side_effect=fail_on_approval):
   with self.assertRaises(OSError): self.run_prepare()
  self.assertFalse((self.bridge/'deploy-enabled').exists())
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertEqual((self.bridge/'first-release-updater-backup').read_bytes(),self.old['apply_update.py'])
 def test_busy_deploy_lock_does_not_close_gate(self):
  import fcntl
  fd=os.open(self.app/'var'/'escape-deploy.lock',os.O_CREAT|os.O_RDWR,0o600)
  try:
   fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
   with self.assertRaises(BlockingIOError):self.run_prepare()
   self.assertTrue((self.bridge/'deploy-enabled').exists())
   self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
  finally:os.close(fd)
 def test_gate_open_failure_preserves_claim(self):
  original=p.atomic
  def fail_before_open(parent,name,data):
   if name=='deploy-enabled': raise OSError('simulated open failure')
   return original(parent,name,data)
  with patch.object(p,'atomic',side_effect=fail_before_open):
   with self.assertRaises(OSError): self.run_prepare()
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertFalse((self.bridge/'deploy-enabled').exists())
 def test_failure_after_gate_open_preserves_claim(self):
  original=p.atomic
  def fail_after_open(parent,name,data):
   result=original(parent,name,data)
   if name=='deploy-enabled': raise OSError('simulated fsync failure')
   return result
  with patch.object(p,'atomic',side_effect=fail_after_open):
   with self.assertRaises(OSError): self.run_prepare()
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_bad_gate_readback_keeps_claim(self):
  original=p.atomic
  def corrupt_gate(parent,name,data):
   if name=='deploy-enabled': return original(parent,name,b'0\\n')
   return original(parent,name,data)
  with patch.object(p,'atomic',side_effect=corrupt_gate):
   with self.assertRaisesRegex(ValueError,'gate_readback_failed'):self.run_prepare()
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertEqual((self.bridge/'deploy-enabled').read_bytes(),b'0\\n')
 def test_failure_status_reports_open_gate_and_claim(self):
  (self.bridge/'deployment-incomplete.json').write_text('claim')
  self.assertEqual(p.failure_status(self.root,'open_failed'),{'status':'stopped','reason':'open_failed','gate_present':True,'recovery_present':True})
 def test_failure_status_reports_closed_gate_and_claim(self):
  (self.bridge/'deployment-incomplete.json').write_text('claim');(self.bridge/'deploy-enabled').unlink()
  self.assertEqual(p.failure_status(self.root,'open_failed'),{'status':'stopped','reason':'open_failed','gate_present':False,'recovery_present':True})
 def test_arrival_during_gate_open_sees_claim(self):
  original=p.atomic
  def during_open(parent,name,data):
   result=original(parent,name,data)
   if name=='deploy-enabled':
    with self.assertRaises(FileExistsError):
     fd=os.open(parent/'deployment-incomplete.json',os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
     os.close(fd)
   return result
  with patch.object(p,'atomic',side_effect=during_open): self.run_prepare()
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
 def test_living_unreadable_process_blocks(self):
  proc=self.root/'proc';entry=proc/'123456';entry.mkdir(parents=True)
  (entry/'status').write_text(f'State:\tS (sleeping)\nUid:\t{os.getuid()}\n')
  with self.assertRaisesRegex(ValueError,'process_inspection_unavailable'):
   p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc)
 def test_gone_process_is_ignored(self):
  proc=self.root/'proc';entry=proc/'123456';entry.mkdir(parents=True)
  original=Path.read_text
  def gone(path,*args,**kwargs):
   if path==entry/'status':
    entry.rmdir()
    raise FileNotFoundError()
   return original(path,*args,**kwargs)
  with patch.object(Path,'read_text',gone):
   self.assertTrue(p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc))
 def test_invalid_release_rejected_before_mutation(self):
  with self.assertRaisesRegex(ValueError,'invalid_release'):
   p.prepare(self.root,'invalid',self.blob,self.updater,b'reqs',self.old,inspect=lambda _:True)
  self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_hidden_proc_mount_is_rejected(self):
  proc=self.root/'proc';(proc/'self/fdinfo').mkdir(parents=True)
  (proc/'self/fdinfo/99').write_text('mnt_id:\t99\n')
  (proc/'self/mountinfo').write_text(f'99 1 0:9 / {proc} rw - proc proc rw,hidepid=2\n')
  with patch.object(p.os,'open',return_value=99), patch.object(p.os,'close'):
   with self.assertRaisesRegex(ValueError,'process_visibility_unverified'):p.proc_visibility(proc)
 def test_unrestricted_proc_mount_accepted(self):
  proc=self.root/'proc';(proc/'self/fdinfo').mkdir(parents=True)
  (proc/'self/fdinfo/99').write_text('mnt_id:\t99\n')
  (proc/'self/mountinfo').write_text(f'99 1 0:9 / {proc} rw - proc proc rw,hidepid=0\n')
  with patch.object(p.os,'open',return_value=99), patch.object(p.os,'close'):
   p.proc_visibility(proc)
 def test_scan_finds_exact_guard_argument(self):
  proc=self.root/'proc';(proc/'123456').mkdir(parents=True)
  (proc/'123456'/'status').write_text(f'Name:\tpython\nState:\tS (sleeping)\nUid:\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\t{os.getuid()}\n')
  (proc/'123456'/'cmdline').write_bytes(b'python\0'+os.fsencode(str(self.bridge/'nordicway_deploy_guard.py'))+b'\0')
  self.assertFalse(p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc))
  (proc/'123456'/'cmdline').write_bytes(b'python\0other.py\0')
  self.assertTrue(p.no_guard_process(self.bridge/'nordicway_deploy_guard.py',proc))
if __name__=='__main__':unittest.main()

