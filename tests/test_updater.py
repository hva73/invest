import sqlite3,tempfile,unittest,os,fcntl
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
   self.assertEqual((target/'hotwatch_warmup.py').read_text(),'new code')
   self.assertIn('data/dk_postcodes.json',apply_update.FILES)
   self.assertEqual((target/'data/dk_postcodes.json').read_text(),'new code')
   self.assertIn('user_profile.py',apply_update.FILES)
   self.assertEqual((target/'user_profile.py').read_text(),'new code')
   self.assertIn('ishares_holdings.py',apply_update.FILES)
   self.assertEqual((target/'ishares_holdings.py').read_text(),'new code')
   self.assertTrue((target/'var/hotwatch-autostart.enabled').is_file())
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

 def test_explicitly_disabled_watchdog_stays_disabled(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));(target/'var/hotwatch-autostart.disabled').touch()
   apply_update.apply(source,target)
   self.assertFalse((target/'var/hotwatch-autostart.enabled').exists())
 def test_running_unmanaged_worker_blocks_update_and_restores_marker(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));fd=os.open(target/'var/hotwatch-worker.lock',os.O_RDWR|os.O_CREAT,0o600)
   try:
    fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    with self.assertRaisesRegex(RuntimeError,'standsede ikke'):
     with apply_update.quiesce_hotwatch(target,timeout=0):self.fail('must not replace code')
    self.assertEqual((target/'app.py').read_text(),'old code')
    self.assertFalse((target/'var/hotwatch-autostart.disabled').exists())
   finally:os.close(fd)
