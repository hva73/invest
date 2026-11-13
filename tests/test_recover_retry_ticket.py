import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_recover_retry_ticket as retry

class Retry(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.bridge=self.root/'bridge';self.bridge.mkdir(mode=0o700);self.app=self.root/'app';(self.app/'var').mkdir(parents=True);self.repo=self.root/'repo';self.repo.mkdir()
  for name,data in {'deploy-enabled':b'1\n','approved-sha':(retry.recovery.RELEASE+'\n').encode(),'owner-approval-key':b'k'*32}.items():
   p=self.bridge/name;p.write_bytes(data);p.chmod(0o600)
  self.verify=patch.object(retry.recovery,'_verify_bridge_modules');self.verify.start();self.addCleanup(self.verify.stop)
 def good(self,*args):return {'status':'ready','release':retry.recovery.RELEASE,'bundle':retry.recovery.BUNDLE}
 def call(self,recover=None):return retry.prepare(self.repo,self.bridge,self.app,recover=recover or self.good)
 def test_real_approval_issues_exact_ticket_once(self):
  result=self.call();self.assertEqual(result['status'],'prepared')
  ticket=json.loads((self.bridge/'approval-ticket.json').read_text());self.assertEqual(ticket['sha'],retry.recovery.RELEASE)
  self.assertEqual(ticket['expires'],result['expires']);self.assertNotIn('nonce',result)
  with self.assertRaisesRegex(ValueError,'pending_work'):self.call()
 def test_recovery_failure_never_issues_ticket(self):
  with self.assertRaisesRegex(ValueError,'recovery_unverified'):self.call(lambda *args:{'status':'failed'})
  self.assertFalse((self.bridge/'approval-ticket.json').exists())
 def test_marker_blocks_approval(self):
  (self.bridge/'deployment-incomplete.json').write_text('{}')
  with self.assertRaisesRegex(ValueError,'pending_work'):self.call()
  self.assertFalse((self.bridge/'approval-ticket.json').exists())
 def test_wrong_gate_or_approval_blocks_ticket(self):
  (self.bridge/'deploy-enabled').write_bytes(b'0\n')
  with self.assertRaisesRegex(ValueError,'gate_unavailable'):self.call()
  self.assertFalse((self.bridge/'approval-ticket.json').exists())
 def test_changed_bridge_blocks_ticket(self):
  retry.recovery._verify_bridge_modules.side_effect=ValueError('installed_bridge_changed')
  with self.assertRaisesRegex(ValueError,'installed_bridge_changed'):self.call()
  self.assertFalse((self.bridge/'approval-ticket.json').exists())


if __name__=='__main__':unittest.main()
