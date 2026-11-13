import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_guard_observe_owner as owner
import nordicway_guard_observe_hold as holder

BASE={'guard_count':0,'guard_found':False,'inspection_complete':True}
LIVE={'guard_count':1,'guard_found':True,'inspection_complete':True,
      'same_pid_namespace':True,'same_mount_namespace':True}
STATE={'gate_enabled':True,'recovery_present':False,'setup_present':False,
       'ticket_present':False,'installed_old_release':True,'approved_hash':b'x'}

class Observer(unittest.TestCase):
 def execute(self, observations, states=None):
  out=io.StringIO()
  with patch.object(owner,'same_old_code',return_value=True), \
       patch.object(owner,'state',side_effect=states or [STATE,STATE]), \
       patch.object(owner,'inspect',side_effect=observations), \
       contextlib.redirect_stdout(out):
   status=owner.main(wait_seconds=1,drain_seconds=1,pause=0)
  return status,out.getvalue()
 def test_one_guard_then_disappeared(self):
  result,text=self.execute([BASE,LIVE,BASE]);self.assertEqual(result,0);self.assertIn('"state_unchanged": true',text)
 def test_existing_guard_rejected(self):
  result,text=self.execute([LIVE]);self.assertEqual(result,1);self.assertIn('baseline_unavailable',text)
 def test_namespace_mismatch_rejected(self):
  result,text=self.execute([BASE,{**LIVE,'same_pid_namespace':False}]);self.assertEqual(result,1);self.assertIn('namespace_mismatch',text)
 def test_changed_state_rejected(self):
  result,text=self.execute([BASE,LIVE,BASE],[STATE,{**STATE,'ticket_present':True}]);self.assertEqual(result,1);self.assertIn('state_changed',text)
 def test_unreadable_inspection_rejected(self):
  result,text=self.execute([BASE,{**LIVE,'inspection_complete':False}]);self.assertEqual(result,1);self.assertIn('observation_unavailable',text)

class Input(io.BytesIO):
 def close(self): self.saved=self.getvalue();super().close()

class FakeSSH:
 def __init__(self,cmd,**kwargs): self.cmd=cmd;self.stdin=Input();self.code=None
 def poll(self): return self.code
 def wait(self,timeout): self.code=1;return 1
 def kill(self): self.code=-9

class Holder(unittest.TestCase):
 def test_only_invalid_fragment_is_sent(self):
  jobs=[]
  def spawn(*args,**kwargs):
   process=FakeSSH(*args,**kwargs);jobs.append(process);return process
  with patch.object(holder,'verify',return_value='fixture\n'),contextlib.redirect_stdout(io.StringIO()):
   holder.hold({'NORDICWAY_DEPLOY_PING_AUTHORIZED':'1','SSH_AUTH_SOCK':'fixture'},timeout=0,popen=spawn)
  self.assertEqual(jobs[0].stdin.saved,b'{')
  self.assertEqual(jobs[0].cmd[-1],'escape-deploy-v1 deploy '+('0'*40))

if __name__=='__main__': unittest.main()
