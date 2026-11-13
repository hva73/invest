import io, os, time, unittest, tempfile
from pathlib import Path
from unittest.mock import Mock,patch
import nordicway_deploy_runner as runner
import nordicway_owner_approval as owner
from nordicway_deploy_sequence import Outcome
SHA='a'*40
class LegacyTicket(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.bridge=Path(self.t.name);self.lock=self.bridge/'lock'
  key=self.bridge/'owner-approval-key';key.write_bytes(b'k'*32);key.chmod(0o600)
  self.payload=io.BytesIO(b'{"cpanel_token":"test_token_12345"}')
 def approved(self,sha=SHA):
  key=(self.bridge/'owner-approval-key').read_bytes();proof=owner.create_proof(sha,key)
  return owner.approve(self.bridge,self.lock,sha,proof)
 def submit(self,sha=SHA):
  real=runner.run
  def wrapped(candidate,token,**kwargs):
   return real(candidate,token,bridge=self.bridge,authorization_lock=self.lock,adapter_factory=Mock(),
    deploy=lambda *_:Outcome('ok','complete',True),prepare=lambda *_:None,**kwargs)
  self.payload.seek(0)
  with patch.object(runner,'run',side_effect=wrapped): return runner.run_request(sha,self.payload)
 def test_owner_ticket_is_one_use(self):
  self.approved();self.assertEqual(self.submit()['status'],'ok')
  self.assertFalse((self.bridge/'approval-ticket.json').exists())
  with self.assertRaises(FileNotFoundError): self.submit()
 def test_missing_ticket_rejected(self):
  (self.bridge/'approved-sha').write_text(SHA+'\n');(self.bridge/'approved-sha').chmod(0o600)
  with self.assertRaises(FileNotFoundError): self.submit()
 def test_ticket_for_other_sha_rejected(self):
  self.approved('b'*40)
  with self.assertRaises(ValueError): self.submit()
 def test_expired_ticket_rejected(self):
  self.approved();path=self.bridge/'approval-ticket.json'
  import json
  ticket=json.loads(path.read_text());ticket['expires']=int(time.time())-1;path.write_text(json.dumps(ticket));path.chmod(0o600)
  with self.assertRaises(ValueError): self.submit()

class ExistingClientJourney(LegacyTicket):
 def test_actual_existing_client_to_guard_and_runner(self):
  import importlib.util, json
  from types import SimpleNamespace
  import nordicway_deploy_guard as guard
  legacy=Path(os.environ['ESCAPE_TEST_LEGACY_BRIDGE'])
  spec=importlib.util.spec_from_file_location('old_client',legacy/'tools/nordicway_deploy_client.py')
  old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
  env={'ESCAPE_RELEASE_SHA':SHA,'ESCAPE_CPANEL_API_TOKEN':'test_token_12345',
       'ESCAPE_DEPLOY_OPERATION':'deploy','ESCAPE_DEPLOY_AUTHORIZED':'1',
       'SSH_AUTH_SOCK':'/synthetic','NORDICWAY_KNOWN_HOST':'x','NORDICWAY_VERIFIED_FINGERPRINT':'x'}
  self.approved();real=runner.run
  def run_local(sha,token,**kwargs):
   return real(sha,token,bridge=self.bridge,authorization_lock=self.lock,adapter_factory=Mock(),
               deploy=lambda *_:Outcome('ok','complete',True),prepare=lambda *_:None,**kwargs)
  def transport(command,**kwargs):
   self.assertEqual(json.loads(kwargs['input']),{'cpanel_token':'test_token_12345'})
   result=guard.dispatch(command[-1],runner=lambda sha:runner.run_request(sha,io.BytesIO(kwargs['input'])))
   return SimpleNamespace(returncode=0,stdout=json.dumps(result).encode())
  with patch.object(old,'verify',return_value='synthetic-key'),patch.object(runner,'run',side_effect=run_local):
   result=old.run(env,transport)
  self.assertEqual(result['status'],'ok');self.assertFalse(result['recovery_required'])
  self.assertFalse((self.bridge/'approval-ticket.json').exists())
