import base64,hashlib,json,os,struct,subprocess,sys,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_readonly_client as client
import nordicway_hostkey as key

class Client(unittest.TestCase):
 def setUp(self):
  name=b'ssh-ed25519';raw=struct.pack('>I',len(name))+name+struct.pack('>I',32)+b'X'*32
  self.env={'NORDICWAY_READONLY_AUTHORIZED':'1','NORDICWAY_KNOWN_HOST':key.HOST+' ssh-ed25519 '+base64.b64encode(raw).decode(),'NORDICWAY_VERIFIED_FINGERPRINT':'SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='),'SSH_AUTH_SOCK':'/tmp/synthetic-agent'}
  self.report={'scope':'read_only_aggregate','observed_at':'2026-11-10T21:00:00+00:00','installation':{'declared_commit':'a'*40,'secret':'hidden'},'database':{'status':'ok','worker':{'status':'running','age_seconds':2,'token':'hidden'},'session_counts':{'ACTIVE':2,'secret-private-ticker':10},'due_count':1},'processes':{'status':'ok','counts':{'worker':1},'args':'hidden'},'storage':{'filesystem_free_bytes':123,'account_quota':'hidden'},'private':'hidden'}
 def test_no_ssh_without_each_explicit_prerequisite(self):
  for name in ['NORDICWAY_READONLY_AUTHORIZED','NORDICWAY_KNOWN_HOST','NORDICWAY_VERIFIED_FINGERPRINT','SSH_AUTH_SOCK']:
   env=dict(self.env);env.pop(name);runner=Mock();result=client.run(env,runner)
   self.assertEqual(result['status'],'blocked');runner.assert_not_called()
 def test_only_fixed_remote_script_and_sanitized_aggregates(self):
  def runner(command,**kwargs):
   self.assertEqual(command[-2:],[client.HOST,'python3 -']);self.assertIn('StrictHostKeyChecking=yes',command);self.assertIn('/dev/null',command)
   self.assertTrue(kwargs['input'].startswith(b'"""Fixed, redacted'))
   return type('Result',(),{'returncode':0,'stdout':json.dumps(self.report).encode()})()
  result=client.run(self.env,runner);self.assertEqual(result['status'],'ok')
  self.assertEqual(result['report']['database']['session_counts'],{'ACTIVE':2})
  self.assertNotIn('hidden',json.dumps(result));self.assertNotIn('secret-private-ticker',json.dumps(result))
 def test_bad_or_unsuccessful_output_has_no_remote_error_text(self):
  for code,raw in [(1,b'secret remote error'),(0,b'secret malformed response'),(0,b'x'*100001)]:
   runner=Mock(return_value=type('Result',(),{'returncode':code,'stdout':raw})())
   result=client.run(self.env,runner);self.assertEqual(result,{'status':'failed','reason':'ssh_or_report_failed'});self.assertNotIn('secret',json.dumps(result))
 def test_transport_bounds_stdout_and_timeout(self):
  small=client._run_limited([sys.executable,'-c','import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'],input=b'hello',capture_output=True,timeout=3,env=os.environ)
  self.assertEqual(small.stdout,b'hello');self.assertEqual(small.returncode,0)
  with self.assertRaises(ValueError):client._run_limited([sys.executable,'-c','print("x"*100001)'],input=b'',capture_output=True,timeout=3,env=os.environ)
  with self.assertRaises(subprocess.TimeoutExpired):client._run_limited([sys.executable,'-c','import time;time.sleep(2)'],input=b'',capture_output=True,timeout=.1,env=os.environ)
if __name__=='__main__':unittest.main()
