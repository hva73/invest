import hashlib
import hmac
import os
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_owner_approval as a

SHA='a'*40
class OwnerApprovalTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name); self.bridge=self.root/'bridge'; self.bridge.mkdir(mode=0o700)
  self.key=b'k'*32; (self.bridge/'owner-approval-key').write_bytes(self.key); (self.bridge/'owner-approval-key').chmod(0o600)
  self.lock=self.root/'lock'; self.lock.touch(mode=0o600)
 def req(self,sha=SHA,nonce='1'*32,expiry=1100):
  mac=hmac.new(self.key,a.message(sha,nonce,expiry),hashlib.sha256).hexdigest()
  return {'nonce':nonce,'expires':expiry,'mac':mac}
 def test_valid_and_replay_rejected(self):
  req=self.req(); self.assertEqual(a.approve(self.bridge,self.lock,SHA,req,now=1000)['sha'],SHA)
  self.assertEqual((self.bridge/'approved-sha').read_text(),SHA+'\n')
  with self.assertRaises(FileExistsError): a.approve(self.bridge,self.lock,SHA,req,now=1000)
 def test_sha_tamper_and_expired_rejected(self):
  for sha,req in [('b'*40,self.req()),(SHA,self.req(expiry=999)),(SHA,self.req(expiry=1301))]:
   with self.assertRaises(ValueError):a.approve(self.bridge,self.lock,sha,req,now=1000)
  self.assertFalse((self.bridge/'approved-sha').exists())
 def test_recovery_blocks_approval(self):
  (self.bridge/'deployment-incomplete.json').touch()
  with self.assertRaisesRegex(ValueError,'recovery_required'):a.approve(self.bridge,self.lock,SHA,self.req(),now=1000)
  self.assertFalse((self.bridge/'approved-sha').exists())
 def test_key_permissions_and_symlink_are_rejected(self):
  key=self.bridge/'owner-approval-key';key.chmod(0o644)
  with self.assertRaisesRegex(ValueError,'unsafe_key'):a.approve(self.bridge,self.lock,SHA,self.req(),now=1000)
  key.unlink();key.symlink_to(self.lock)
  with self.assertRaises(OSError):a.approve(self.bridge,self.lock,SHA,self.req(),now=1000)
 def test_unsafe_existing_approval_not_overwritten(self):
  path=self.bridge/'approved-sha';path.write_text('old');path.chmod(0o644)
  with self.assertRaisesRegex(ValueError,'unsafe_approval'):a.approve(self.bridge,self.lock,SHA,self.req(),now=1000)
  self.assertEqual(path.read_text(),'old')
