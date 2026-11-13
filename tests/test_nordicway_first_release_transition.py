"""Offline integration of proposed setup with the actual c1b6 legacy guard."""
import ast
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

LEGACY = Path(os.environ.get('ESCAPE_TEST_LEGACY_BRIDGE', '/nonexistent'))
RELEASE_REPO = Path(os.environ.get('ESCAPE_TEST_RELEASE_REPO', '/nonexistent'))
RELEASE = '819a444668c5aff4a992fcee73666837264869f4'

@unittest.skipUnless((LEGACY/'tools/nordicway_deploy_guard.py').is_file() and (RELEASE_REPO/'apply_update.py').is_file(), 'requires pinned legacy and release checkouts')
class Transition(unittest.TestCase):
 def setUp(self):
  sys.path[:0]=[str(LEGACY/'tools'),str(LEGACY)]
  import nordicway_deploy_guard as guard
  import nordicway_deploy_runner as runner
  import nordicway_deploy_adapter as adapter
  from nordicway_deploy_sequence import Outcome
  self.guard,self.runner,self.adapter,self.Outcome=guard,runner,adapter,Outcome
  path=Path(__file__).resolve().parents[1]/'tools/nordicway_prepare_first_release.py'
  spec=importlib.util.spec_from_file_location('first_release_integration',path)
  self.p=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.p)
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
  self.bridge=self.root/'.escape_deploy_bridge';self.bridge.mkdir(mode=0o700)
  self.app=self.root/'escape_app';(self.app/'var').mkdir(parents=True)
  (self.app/'BUILD_COMMIT').write_text(self.p.INSTALLED+'\n');(self.app/'requirements.txt').write_bytes(b'same')
  self.checkout=self.root/'checkout';self.checkout.mkdir();(self.checkout/'requirements.txt').write_bytes(b'same')
  self.modules={name:(LEGACY/('apply_update.py' if name=='apply_update.py' else 'tools/'+name)).read_bytes()
                for name in (*self.p.MODULES,'apply_update.py')}
  for name,data in self.modules.items():
   path=self.bridge/name;path.write_bytes(data);path.chmod(0o600)
  for name,data in [('deploy-enabled',b'1\n'),('approved-sha',b'a'*40+b'\n')]:
   path=self.bridge/name;path.write_bytes(data);path.chmod(0o600)
  self.updater=(RELEASE_REPO/'apply_update.py').read_bytes()
  tree=ast.parse(self.updater)
  self.manifest=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='FILES')
 def prepare(self):
  return self.p.prepare(self.root,RELEASE,self.p.blob(self.updater),self.updater,b'same',self.modules,inspect=lambda _:True)
 def real_runner(self, sha, token):
  def simulated_deploy(concrete, commit):
   concrete.preflight(commit)
   return self.Outcome('ok','complete',True)
  return self.runner.run(sha,token,bridge=self.bridge,checkout=self.checkout,target=self.app,
                         deploy=simulated_deploy,prepare=lambda *_:None)
 def test_setup_to_actual_legacy_preflight(self):
  self.assertEqual(self.prepare()['status'],'prepared')
  self.assertTrue(self.guard.deployment_enabled(str(self.bridge/'deploy-enabled')))
  original=self.runner.run
  try:
   with patch.object(self.runner,'run',side_effect=lambda sha,token:self.real_runner_impl(original,sha,token)), \
        patch.object(self.adapter.nordicway_release_preflight,'inspect',return_value={'status':'blocked'}), \
        patch.object(self.adapter.nordicway_release_preflight,'manifest',return_value=self.manifest), \
        patch.object(self.adapter.apply_update,'FILES',self.manifest):
    response=self.guard.dispatch('escape-deploy-v1 deploy '+RELEASE,
       runner=lambda sha:self.runner.run_request(sha,io.BytesIO(b'{"cpanel_token":"test_token_12345"}')))
  finally: pass
  self.assertEqual(response['status'],'ok');self.assertFalse(response['recovery_required'])
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
  self.assertEqual((self.app/'BUILD_COMMIT').read_text().strip(),self.p.INSTALLED)
 def real_runner_impl(self, original, sha, token):
  def simulated_deploy(concrete, commit):
   concrete.preflight(commit)
   return self.Outcome('ok','complete',True)
  return original(sha,token,bridge=self.bridge,checkout=self.checkout,target=self.app,
                  deploy=simulated_deploy,prepare=lambda *_:None)
 def test_guard_request_while_gate_reopens_cannot_claim(self):
  original=self.p.atomic; runner_run=self.runner.run
  def at_open(parent,name,data):
   result=original(parent,name,data)
   if name=='deploy-enabled':
    self.assertTrue(self.guard.deployment_enabled(str(parent/name)))
    with patch.object(self.runner,'run',side_effect=lambda sha,token:runner_run(sha,token,bridge=self.bridge,checkout=self.checkout,target=self.app)):
     with self.assertRaises(FileExistsError):
      self.guard.dispatch('escape-deploy-v1 deploy '+RELEASE,
       runner=lambda sha:self.runner.run_request(sha,io.BytesIO(b'{"cpanel_token":"test_token_12345"}')))
   return result
  with patch.object(self.p,'atomic',side_effect=at_open):
   self.assertEqual(self.prepare()['status'],'prepared')
  self.assertFalse((self.bridge/'deployment-incomplete.json').exists())
