import os, sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import nordicway_passenger_classification as m

class Classification(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);self.app=self.root/'escape_app';self.app.mkdir()
  self.proc=self.root/'proc';self.proc.mkdir();self.exe=self.root/'lswsgi';self.exe.touch()
 def process(self,pid,cmd,parent='1',cwd=None,exe=None):
  p=self.proc/str(pid);p.mkdir();(p/'cmdline').write_bytes(cmd)
  (p/'stat').write_text(f'{pid} (lswsgi) S {parent} '+'0 '*20)
  (p/'cwd').symlink_to(cwd or self.app);(p/'exe').symlink_to(exe or self.exe)
  return p
 def test_exact_orphan_criteria(self):
  self.process(42,b'python\0'+os.fsencode(str(self.app/'passenger_wsgi.py'))+b'\0')
  result=m.classify(self.app,self.proc,self_pid=0)
  self.assertEqual(result['passenger_active'],1);self.assertEqual(result['all_orphan_criteria'],1)
  self.assertFalse(result['inspection_incomplete']);self.assertNotIn('42',str(result))
 def test_neighbor_path_cannot_count_as_exact(self):
  self.process(42,b'python\0'+os.fsencode(str(self.app)+'_other/passenger_wsgi.py')+b'\0')
  result=m.classify(self.app,self.proc,self_pid=0)
  self.assertEqual(result['passenger_active'],1);self.assertEqual(result['wsgi_argument_exact'],0)
  self.assertEqual(result['all_orphan_criteria'],0)
 def test_title_only_and_different_parent(self):
  self.process(42,b'Passenger escape_app\0',parent='7')
  result=m.classify(self.app,self.proc,self_pid=0)
  self.assertEqual(result['passenger_title'],1);self.assertEqual(result['parent_is_one'],0)
  self.assertEqual(result['all_orphan_criteria'],0)
 def test_unreadable_selected_process_is_not_complete(self):
  p=self.process(42,b'python\0'+os.fsencode(str(self.app/'passenger_wsgi.py'))+b'\0')
  (p/'exe').unlink();result=m.classify(self.app,self.proc,self_pid=0)
  self.assertTrue(result['inspection_incomplete'])

if __name__=='__main__': unittest.main()
