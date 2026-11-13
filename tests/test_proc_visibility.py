import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_prepare_first_release as base

class Visibility(unittest.TestCase):
 def check_mount(self,option,point='/proc',mount_id='42',duplicate=False):
  line=f'42 1 0:3 / {point} rw,nosuid - proc proc rw,{option}'
  lines=line+'\n'+line+'\n' if duplicate else line+'\n'
  def read(path,*args,**kwargs):
   if str(path)=='/proc/self/mountinfo': return lines
   if str(path)=='/proc/self/fdinfo/8': return f'mnt_id:\t{mount_id}\n'
   raise AssertionError(str(path))
  with patch.object(Path,'read_text',read),patch.object(base.os,'open',return_value=8),patch.object(base.os,'close'):
   return base.proc_visibility(Path('/proc'))
 def test_documented_same_user_modes(self):
  for option in ('hidepid=invisible','hidepid=2','hidepid=0','rw'):
   with self.subTest(option=option): self.assertIsNone(self.check_mount(option))
 def test_unknown_and_ambiguous_modes_fail_closed(self):
  for option in ('hidepid=4','hidepid=ptraceable','hidepid=1','hidepid=unknown','hidepid=0,hidepid=invisible'):
   with self.subTest(option=option),self.assertRaisesRegex(ValueError,'process_visibility_unverified'):self.check_mount(option)
 def test_wrong_mount_and_ambiguous_mounts_fail_closed(self):
  for kw in ({'point':'/elsewhere'},{'mount_id':'41'},{'duplicate':True}):
   with self.subTest(kw=kw),self.assertRaisesRegex(ValueError,'process_visibility_unverified'):self.check_mount('hidepid=invisible',**kw)

if __name__=='__main__':unittest.main()
