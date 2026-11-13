import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_recover_a708_prebackup as r

class Recovery(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=Path(self.t.name);self.bridge=self.root/'bridge';self.bridge.mkdir(mode=0o700);self.app=self.root/'app';(self.app/'var').mkdir(parents=True);self.repo=self.root/'repo';self.repo.mkdir()
  self.mark=self.bridge/'deployment-incomplete.json';self.record={'format':1,'sha':r.RELEASE,'state':'started','motor_enabled':True,'motor_disabled':False}
  self.put('approved-sha',r.RELEASE+'\n');self.put('deploy-enabled','1\n');self.put('deployment-incomplete.json',json.dumps(self.record)+'\n')
 def tearDown(self):self.t.cleanup()
 def put(self,name,data):
  p=self.bridge/name;p.write_text(data);p.chmod(0o600)
 def invoke(self,verify_files=lambda *x:None,verify_runtime=lambda *x:None):
  with patch.object(r,'_verify_bridge_modules',return_value=None):
   return r.prepare(self.repo,self.bridge,self.app,verify_files=verify_files,verify_runtime=verify_runtime)
 def test_success_archives_exact_marker_and_restores_gate(self):
  original=self.mark.read_bytes();self.invoke()
  self.assertFalse(self.mark.exists());self.assertEqual((self.bridge/'deploy-enabled').read_bytes(),b'1\n')
  archives=list(self.bridge.glob('recovery-reviewed-*.json'));self.assertEqual(len(archives),1);self.assertEqual(archives[0].read_bytes(),original)
 def test_backup_marker_rejected_and_preserved(self):
  self.record['backup']='some-backup';self.put('deployment-incomplete.json',json.dumps(self.record))
  with self.assertRaisesRegex(ValueError,'unexpected_recovery'):self.invoke()
  self.assertTrue(self.mark.exists());self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_runtime_failure_keeps_marker_and_closes_gate(self):
  def fail(*a):raise ValueError('runtime_unavailable')
  with self.assertRaisesRegex(ValueError,'runtime_unavailable'):self.invoke(verify_runtime=fail)
  self.assertTrue(self.mark.exists());self.assertFalse((self.bridge/'deploy-enabled').exists())
 def test_ticket_rejected_before_gate_change(self):
  self.put('approval-ticket.json','fixture')
  with self.assertRaisesRegex(ValueError,'unexpected_pending_state'):self.invoke()
  self.assertTrue(self.mark.exists());self.assertTrue((self.bridge/'deploy-enabled').exists())
 def test_changed_marker_is_preserved(self):
  def change(*a):self.put('deployment-incomplete.json','{}')
  with self.assertRaisesRegex(ValueError,'recovery_changed'):self.invoke(verify_runtime=change)
  self.assertTrue(self.mark.exists());self.assertFalse((self.bridge/'deploy-enabled').exists())
 def test_gate_recreation_failure_recreates_marker(self):
  original=r._create
  def fail_gate(path,data):
   if path.name=='deploy-enabled':raise OSError('synthetic')
   return original(path,data)
  with patch.object(r,'_create',side_effect=fail_gate),self.assertRaises(OSError):self.invoke()
  self.assertTrue(self.mark.exists());self.assertFalse((self.bridge/'deploy-enabled').exists())
if __name__=='__main__':unittest.main()
