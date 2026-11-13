import io,json,os,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock,patch
import nordicway_first_app_bridge_setup as setup
import nordicway_prepare_first_release as base
import nordicway_install_bridge as installer
import nordicway_owner_approval as approval
import nordicway_deploy_runner as runner
import nordicway_deploy_guard as guard
from nordicway_deploy_sequence import Outcome
SHA='a'*40; BRIDGE_SHA='b'*40
LEGACY=Path(os.environ['ESCAPE_TEST_LEGACY_BRIDGE'])
NEW=Path(__file__).resolve().parents[1]
class FirstAppBridge(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.bridge=self.root/'.escape_deploy_bridge';self.bridge.mkdir(mode=0o700);self.app=self.root/'escape_app';(self.app/'var').mkdir(parents=True)
  (self.app/'BUILD_COMMIT').write_text(base.INSTALLED+'\n');(self.app/'requirements.txt').write_bytes(b'same')
  self.old={name:(LEGACY/('apply_update.py' if name=='apply_update.py' else 'tools/'+name)).read_bytes() for name in (*base.MODULES,'apply_update.py')}
  for name,data in self.old.items():
   p=self.bridge/name;p.write_bytes(data);p.chmod(0o600)
  for name,data in [('deploy-enabled',b'1\n'),('approved-sha',b'c'*40+b'\n')]:
   p=self.bridge/name;p.write_bytes(data);p.chmod(0o600)
  self.files={Path(name).name:(NEW/name).read_bytes() for name in installer.MODULES}
  self.updater=self.files['apply_update.py']
 def prepare(self):
  with patch.object(installer,'_sources',return_value=self.files):
   return setup.prepare(self.root,SHA,BRIDGE_SHA,base.blob(self.updater),self.updater,self.updater,b'same',self.old,installer,approval,self.root,inspect=lambda _:True)
 def test_actual_installer_then_signed_ticket_and_legacy_request(self):
  import time
  before=int(time.time());result=self.prepare();self.assertEqual(result['status'],'prepared')
  self.assertGreaterEqual(result['expires'],before+299);self.assertLessEqual(result['expires'],int(time.time())+300)
  self.assertEqual((self.bridge/'nordicway_deploy_guard.py').read_bytes(),self.files['nordicway_deploy_guard.py'])
  self.assertEqual((self.bridge/'deploy-enabled').read_bytes(),b'1\n')
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists());self.assertFalse((self.bridge/'first-release-setup-incomplete.json').exists())
  self.assertTrue((self.bridge/'approval-ticket.json').is_file())
  real=runner.run
  def execute(sha,token,**kwargs):
   return real(sha,token,bridge=self.bridge,authorization_lock=self.app/'var/escape-deploy.lock',adapter_factory=Mock(),deploy=lambda *_:Outcome('ok','complete',True),prepare=lambda *_:None,**kwargs)
  import importlib.util
  spec=importlib.util.spec_from_file_location('existing_client',LEGACY/'tools/nordicway_deploy_client.py')
  existing_client=importlib.util.module_from_spec(spec);spec.loader.exec_module(existing_client)
  env={'ESCAPE_RELEASE_SHA':SHA,'ESCAPE_CPANEL_API_TOKEN':'test_token_12345','ESCAPE_DEPLOY_OPERATION':'deploy',
       'ESCAPE_DEPLOY_AUTHORIZED':'1','SSH_AUTH_SOCK':'/synthetic',
       'NORDICWAY_KNOWN_HOST':'x','NORDICWAY_VERIFIED_FINGERPRINT':'x'}
  def transport(command,**kwargs):
   result=guard.dispatch(command[-1],runner=lambda sha:runner.run_request(sha,io.BytesIO(kwargs['input'])))
   return SimpleNamespace(returncode=0,stdout=json.dumps(result).encode())
  with patch.object(runner,'run',side_effect=execute),patch.object(existing_client,'verify',return_value='synthetic-key'):
   result=existing_client.run(env,transport)
  self.assertEqual(result['status'],'ok');self.assertFalse((self.bridge/'approval-ticket.json').exists())
  self.assertEqual((self.app/'BUILD_COMMIT').read_text().strip(),base.INSTALLED)
 def test_installer_reads_actual_git_objects(self):
  import subprocess
  repo=self.root/'git-source';repo.mkdir()
  def git(*args):
   return subprocess.run(['git','-C',str(repo),*args],check=True,capture_output=True,text=True).stdout.strip()
  git('init','-q')
  for name in installer.MODULES:
   dest=repo/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(self.files[Path(name).name])
  (repo/'tools/nordicway_install_bridge.py').write_bytes((NEW/'tools/nordicway_install_bridge.py').read_bytes())
  git('add','.')
  git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
  commit=git('rev-parse','HEAD')
  pinned_installer=setup.load_module('pinned_installer',base.git_file(repo,commit,'tools/nordicway_install_bridge.py'))
  pinned_approval=setup.load_module('pinned_approval',base.git_file(repo,commit,'tools/nordicway_owner_approval.py'))
  result=setup.prepare(self.root,SHA,commit,base.blob(self.updater),self.updater,self.updater,b'same',self.old,pinned_installer,pinned_approval,repo,inspect=lambda _:True)
  self.assertEqual(result['bridge'],commit)
  self.assertEqual((self.bridge/'apply_update.py').read_bytes(),self.updater)
  self.assertTrue((self.bridge/'approval-ticket.json').exists())
 def test_installer_failure_keeps_gate_closed_and_both_markers(self):
  with patch.object(installer,'install',side_effect=OSError('fail')):
   with self.assertRaises(OSError):self.prepare()
  self.assertFalse((self.bridge/'deploy-enabled').exists());self.assertTrue((self.bridge/'first-release-setup-incomplete.json').exists());self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
 def test_approval_failure_keeps_gate_closed_and_setup_marker(self):
  with patch.object(approval,'approve',side_effect=OSError('fail')):
   with self.assertRaises(OSError):self.prepare()
  self.assertFalse((self.bridge/'deploy-enabled').exists());self.assertTrue((self.bridge/'first-release-setup-incomplete.json').exists())
 def test_interruption_after_ticket_before_second_claim_keeps_gate_closed(self):
  original=setup.claim; calls=[]
  def fail_second_deploy_claim(path,release):
   calls.append(path.name)
   if calls.count('deployment-incomplete.json')==2: raise OSError('fail')
   return original(path,release)
  with patch.object(setup,'claim',side_effect=fail_second_deploy_claim):
   with self.assertRaises(OSError):self.prepare()
  self.assertFalse((self.bridge/'deploy-enabled').exists())
  self.assertTrue((self.bridge/'first-release-setup-incomplete.json').exists())
  self.assertTrue((self.bridge/'approval-ticket.json').exists())
 def test_old_guard_reappears_after_installer_leaves_gate_closed(self):
  values=iter([True,True,False])
  with patch.object(installer,'_sources',return_value=self.files):
   with self.assertRaisesRegex(ValueError,'guard_in_flight'):
    setup.prepare(self.root,SHA,BRIDGE_SHA,base.blob(self.updater),self.updater,self.updater,b'same',self.old,installer,approval,self.root,inspect=lambda _:next(values))
  self.assertFalse((self.bridge/'deploy-enabled').exists())
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
  self.assertTrue((self.bridge/'first-release-setup-incomplete.json').exists())
 def test_gate_failure_preserves_claim_and_setup_marker(self):
  original=base.atomic
  def fail_gate(parent,name,data):
   if name=='deploy-enabled':raise OSError('fail')
   return original(parent,name,data)
  with patch.object(base,'atomic',side_effect=fail_gate):
   with self.assertRaises(OSError):self.prepare()
  self.assertTrue((self.bridge/'deployment-incomplete.json').exists());self.assertTrue((self.bridge/'first-release-setup-incomplete.json').exists());self.assertFalse((self.bridge/'deploy-enabled').exists())
 def test_new_request_while_gate_opens_is_locked_out(self):
  original=base.atomic;real=runner.run
  def at_open(parent,name,data):
   result=original(parent,name,data)
   if name=='deploy-enabled':
    def execute(sha,token,**kwargs):
     return real(sha,token,bridge=self.bridge,authorization_lock=self.app/'var/escape-deploy.lock',adapter_factory=Mock(),prepare=lambda *_:None,**kwargs)
    with patch.object(runner,'run',side_effect=execute):
     with self.assertRaises(BlockingIOError):
      guard.dispatch('escape-deploy-v1 deploy '+SHA,runner=lambda sha:runner.run_request(sha,io.BytesIO(b'{"cpanel_token":"test_token_12345"}')))
    self.assertTrue((self.bridge/'approval-ticket.json').exists())
   return result
  with patch.object(base,'atomic',side_effect=at_open): self.prepare()
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
 def test_guard_becomes_active_after_precheck_blocks_install(self):
  values=iter([True,False])
  with patch.object(installer,'_sources',return_value=self.files):
   with self.assertRaisesRegex(ValueError,'guard_in_flight'):
    setup.prepare(self.root,SHA,BRIDGE_SHA,base.blob(self.updater),self.updater,self.updater,b'same',self.old,installer,approval,self.root,inspect=lambda _:next(values))
  self.assertEqual((self.bridge/'nordicway_deploy_guard.py').read_bytes(),self.old['nordicway_deploy_guard.py'])
  self.assertFalse((self.bridge/'deploy-enabled').exists());self.assertTrue((self.bridge/'deployment-incomplete.json').exists())
 def test_mismatched_updater_does_not_change_bridge(self):
  with patch.object(installer,'_sources',return_value=self.files):
   with self.assertRaisesRegex(ValueError,'candidate_mismatch'):
    setup.prepare(self.root,SHA,BRIDGE_SHA,base.blob(self.updater),self.updater,b'wrong',b'same',self.old,installer,approval,self.root,inspect=lambda _:True)
  self.assertEqual((self.bridge/'deploy-enabled').read_bytes(),b'1\n');self.assertFalse((self.bridge/'first-release-setup-incomplete.json').exists())


class PublicOrigin(unittest.TestCase):
 def test_missing_ssh_environment_reuses_existing_health_origin(self):
  import nordicway_app_release_entry as entry
  import nordicway_deploy_health as health
  env={}
  entry.ensure_public_origin(env,health.HEALTH_URL)
  self.assertEqual(env['ESCAPE_PUBLIC_URL'],'https://escape.nordic-response.dk')
 def test_explicit_app_origin_is_preserved(self):
  import nordicway_app_release_entry as entry
  env={'ESCAPE_PUBLIC_URL':'https://example.invalid'}
  entry.ensure_public_origin(env,'https://escape.nordic-response.dk/api/health')
  self.assertEqual(env['ESCAPE_PUBLIC_URL'],'https://example.invalid')
 def test_invalid_health_origin_is_rejected(self):
  import nordicway_app_release_entry as entry
  for url in ('http://example.invalid/api/health','https://user@example.invalid/api/health',
              'https://example.invalid/other','https://example.invalid/api/health?x=1'):
   with self.subTest(url=url):
    with self.assertRaisesRegex(ValueError,'health_origin_invalid'): entry.ensure_public_origin({},url)

