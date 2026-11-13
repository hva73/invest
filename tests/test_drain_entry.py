import importlib.util,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_drain_diagnostic_entry as entry

class Entry(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  root=Path(self.temp.name);self.bridge=root/'bridge';self.bridge.mkdir();self.app=root/'app';self.app.mkdir()
  record={'format':1,'sha':entry.recovery.RELEASE,'state':'started','motor_enabled':True,'motor_disabled':False}
  (self.bridge/'deployment-incomplete.json').write_text(json.dumps(record))
  (self.bridge/'approved-sha').write_text(entry.recovery.RELEASE+'\n')
  (self.bridge/'deploy-enabled').write_text('1\n')
  self.patches=[patch.object(entry,'BRIDGE',self.bridge),patch.object(entry,'APP',self.app),
   patch.object(entry.recovery,'_private_file',side_effect=lambda path,*a:Path(path).read_bytes()),
   patch.object(entry.recovery,'_verify_bridge_modules'),patch.object(entry.recovery,'_verify_files'),
   patch.object(entry.recovery,'_verify_runtime')]
  for p in self.patches:p.start();self.addCleanup(p.stop)
 def test_exact_prebackup_state_is_accepted_without_removing_marker(self):
  self.assertTrue(entry.validate());self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
 def test_backup_or_ticket_blocks_before_health_check(self):
  (self.bridge/'approval-ticket.json').write_text('pending')
  with self.assertRaisesRegex(ValueError,'pending_work'):entry.validate()
  entry.recovery._verify_runtime.assert_not_called()
 def test_different_marker_rejected(self):
  p=self.bridge/'deployment-incomplete.json';data=json.loads(p.read_text());data['backup']='backup';p.write_text(json.dumps(data))
  with self.assertRaisesRegex(ValueError,'unexpected_recovery'):entry.validate()
  self.assertTrue(p.exists())

if __name__=='__main__':unittest.main()
