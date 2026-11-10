import base64,hashlib,json,os,sqlite3,struct,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_readonly_client as client
import nordicway_hostkey as key
import nordicway_server_guard as guard
import nordicway_readonly_diagnostics as diagnostics

class Client(unittest.TestCase):
 def setUp(self):
  name=b'ssh-ed25519';raw=struct.pack('>I',len(name))+name+struct.pack('>I',32)+b'X'*32
  self.env={'NORDICWAY_READONLY_AUTHORIZED':'1','NORDICWAY_KNOWN_HOST':key.HOST+' ssh-ed25519 '+base64.b64encode(raw).decode(),'NORDICWAY_VERIFIED_FINGERPRINT':'SHA256:'+base64.b64encode(hashlib.sha256(raw).digest()).decode().rstrip('='),'SSH_AUTH_SOCK':'/tmp/synthetic-agent'}
  self.env['NORDICWAY_RESTRICTED_KEY_VERIFIED']='1'
  self.report={'scope':'read_only_aggregate','observed_at':'2026-11-10T21:00:00+00:00','installation':{'declared_commit':'a'*40,'secret':'hidden'},'database':{'status':'ok','worker':{'status':'running','age_seconds':2,'token':'hidden'},'session_counts':{'ACTIVE':2,'secret-private-ticker':10},'due_count':1},'processes':{'status':'ok','counts':{'worker':1},'args':'hidden'},'storage':{'filesystem_free_bytes':123,'account_quota':'hidden'},'private':'hidden'}
 def test_no_ssh_without_each_explicit_prerequisite(self):
  for name in ['NORDICWAY_READONLY_AUTHORIZED','NORDICWAY_RESTRICTED_KEY_VERIFIED','NORDICWAY_KNOWN_HOST','NORDICWAY_VERIFIED_FINGERPRINT','SSH_AUTH_SOCK']:
   env=dict(self.env);env.pop(name);runner=Mock();result=client.run(env,runner)
   self.assertEqual(result['status'],'blocked');runner.assert_not_called()
 def test_only_fixed_remote_script_and_sanitized_aggregates(self):
  def runner(command,**kwargs):
   self.assertEqual(command[-2:],[client.HOST,'escape-readonly-v1 diagnostics']);self.assertIn('StrictHostKeyChecking=yes',command);self.assertIn('/dev/null',command)
   self.assertEqual(kwargs['input'],b'')
   return type('Result',(),{'returncode':0,'stdout':json.dumps({'protocol':client.PROTOCOL,'operation':'diagnostics','report':self.report}).encode()})()
  result=client.run(self.env,runner);self.assertEqual(result['status'],'ok')
  self.assertEqual(result['report']['database']['session_counts'],{'ACTIVE':2})
  self.assertNotIn('hidden',json.dumps(result));self.assertNotIn('secret-private-ticker',json.dumps(result))
 def test_bad_or_unsuccessful_output_has_no_remote_error_text(self):
  for code,raw in [(1,b'secret remote error'),(0,b'secret malformed response'),(0,b'x'*100001)]:
   runner=Mock(return_value=type('Result',(),{'returncode':code,'stdout':raw})())
   result=client.run(self.env,runner);self.assertEqual(result,{'status':'failed','reason':'ssh_or_report_failed'});self.assertNotIn('secret',json.dumps(result))
 def test_release_preflight_is_fixed_read_only_and_always_blocked(self):
  env={**self.env,'NORDICWAY_OPERATION':'release_preflight','NORDICWAY_RELEASE_SHA':'b'*40}
  payload={'status':'blocked','requested_sha':'b'*40,'manifest_sha256':'c'*64,'manifest_files':71,'installed_files_checked':71,'installed_files_matching':70,'source_bytes':100,'database_bytes':200,'filesystem_free_bytes':300,'blockers':sorted(client.PREFLIGHT_BLOCKERS),'private':'secret'}
  def runner(command,**kwargs):
   self.assertEqual(command[-2:],[client.HOST,'escape-readonly-v1 preflight '+'b'*40])
   self.assertEqual(kwargs['input'],b'')
   return type('Result',(),{'returncode':0,'stdout':json.dumps({'protocol':client.PROTOCOL,'operation':'release_preflight','report':payload}).encode()})()
  result=client.run(env,runner);self.assertEqual(result['status'],'ok');self.assertEqual(result['report']['status'],'blocked');self.assertNotIn('secret',json.dumps(result))
  env['NORDICWAY_RELEASE_SHA']='$(id)';runner=Mock();self.assertEqual(client.run(env,runner)['reason'],'invalid_operation');runner.assert_not_called()
 def test_transport_bounds_stdout_and_timeout(self):
  small=client._run_limited([sys.executable,'-c','import sys;sys.stdout.buffer.write(sys.stdin.buffer.read())'],input=b'hello',capture_output=True,timeout=3,env=os.environ)
  self.assertEqual(small.stdout,b'hello');self.assertEqual(small.returncode,0)
  with self.assertRaises(ValueError):client._run_limited([sys.executable,'-c','print("x"*100001)'],input=b'',capture_output=True,timeout=3,env=os.environ)
  with self.assertRaises(subprocess.TimeoutExpired):client._run_limited([sys.executable,'-c','import time;time.sleep(2)'],input=b'',capture_output=True,timeout=.1,env=os.environ)
 def test_end_to_end_fixed_guard_with_synthetic_database_is_read_only(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'var').mkdir();db=root/'var/escape.db'
   with sqlite3.connect(db) as connection:
    connection.execute('CREATE TABLE preserved(value TEXT)')
    connection.execute("INSERT INTO preserved VALUES('must-not-appear')")
   (root/'BUILD_COMMIT').write_text('a'*40,encoding='ascii');before=db.read_bytes()
   def runner(command,**kwargs):
    self.assertEqual(kwargs['input'],b'')
    report=guard.dispatch(command[-1],lambda:diagnostics.inspect(root),lambda sha:self.fail('preflight not requested'))
    return type('Result',(),{'returncode':0,'stdout':json.dumps(report).encode()})()
   result=client.run(self.env,runner)
   self.assertEqual(result['status'],'ok');self.assertEqual(result['report']['installation']['declared_commit'],'a'*40)
   self.assertEqual(result['report']['database']['status'],'ok')
   self.assertEqual(db.read_bytes(),before);self.assertNotIn('must-not-appear',json.dumps(result))
if __name__=='__main__':unittest.main()
