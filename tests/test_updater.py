import sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import apply_update
class Updater(unittest.TestCase):
 def fixture(self,root):
  target=root/'escape_app';source=target/'opdatering/release';source.mkdir(parents=True);(target/'var').mkdir()
  with sqlite3.connect(target/'var/escape.db') as c:c.execute('CREATE TABLE preserved(value)');c.execute("INSERT INTO preserved VALUES('private-data')")
  for name in apply_update.FILES:
   file=source/name;file.parent.mkdir(parents=True,exist_ok=True);file.write_text('new code')
  (target/'app.py').write_text('old code');return source,target
 def test_backup_and_preservation(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));backup=apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'new code');self.assertEqual((backup/'code/app.py').read_text(),'old code')
   for path in [target/'var/escape.db',backup/'escape.db']:
    with sqlite3.connect(path) as c:self.assertEqual(c.execute('SELECT value FROM preserved').fetchone()[0],'private-data')
 def test_missing_file_changes_nothing(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));(source/'oauth.py').unlink()
   with self.assertRaises(ValueError):apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'old code')
 def test_partial_copy_rolls_back(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));original=apply_update.os.replace;calls=[]
   def fail_second(*args):
    calls.append(args)
    if len(calls)==2:raise OSError('test failure')
    return original(*args)
   with patch('apply_update.os.replace',side_effect=fail_second):
    with self.assertRaises(OSError):apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'old code');self.assertFalse((target/'pluto.py').exists())
