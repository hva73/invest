import sqlite3,tempfile,unittest,os,fcntl,ast,shutil,subprocess,sys,json
from pathlib import Path
from unittest.mock import patch
import apply_update
class Updater(unittest.TestCase):
 def test_installed_release_starts_without_source_checkout_on_import_path(self):
  root=Path(apply_update.__file__).resolve().parent
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d))
   for name in apply_update.FILES:shutil.copyfile(root/name,source/name)
   apply_update.apply(source,target)
   env={k:v for k,v in os.environ.items() if not k.startswith(('ESCAPE_','PLUTO_','PYTHONPATH'))}
   env.update(ESCAPE_DB=str(target/'var/escape.db'),ESCAPE_HW_AUTOSUPERVISE='0')
   probe='''import sys,io,json
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import passenger_wsgi,hotwatch_service,eodhd_capacity
status=[]
body=b''.join(passenger_wsgi.application({'PATH_INFO':'/api/health','REQUEST_METHOD':'GET','REMOTE_ADDR':'test','wsgi.input':io.BytesIO(b'')},lambda s,h:status.append(s)))
assert status==['200 OK'],status
assert json.loads(body)['database'] is True
assert Path(eodhd_capacity.__file__).parent==Path(sys.argv[1])
print('INSTALLED_RELEASE_HEALTH_PASS')
'''
   result=subprocess.run([sys.executable,'-I','-c',probe,str(target)],cwd=target,env=env,capture_output=True,text=True,timeout=30)
   self.assertEqual(result.returncode,0,result.stderr)
   self.assertIn('INSTALLED_RELEASE_HEALTH_PASS',result.stdout)
   with sqlite3.connect(target/'var/escape.db') as c:self.assertEqual(c.execute('SELECT value FROM preserved').fetchone()[0],'private-data')
 def test_manifest_contains_local_runtime_imports(self):
  root=Path(apply_update.__file__).resolve().parent;missing=set()
  for name in apply_update.FILES:
   if not name.endswith('.py'):continue
   for node in ast.walk(ast.parse((root/name).read_text())):
    modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and node.module else []
    for module in modules:
     dependency=module.split('.')[0]+'.py'
     if (root/dependency).is_file() and dependency not in apply_update.FILES:missing.add((name,dependency))
  self.assertEqual(missing,set(),'Installer omits local runtime imports: '+repr(sorted(missing)))
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
   self.assertEqual((target/'hotwatch_buy_plan.py').read_text(),'new code')
   self.assertIn('web_push.py',apply_update.FILES);self.assertEqual((target/'web_push.py').read_text(),'new code')
   self.assertIn('strategy_center.py',apply_update.FILES);self.assertEqual((target/'strategy_center.py').read_text(),'new code')
   self.assertIn('strategy_lab.py',apply_update.FILES);self.assertEqual((target/'strategy_lab.py').read_text(),'new code')
   self.assertIn('data/dk_postcodes.json',apply_update.FILES)
   self.assertEqual((target/'data/dk_postcodes.json').read_text(),'new code')
   self.assertIn('user_profile.py',apply_update.FILES)
   self.assertEqual((target/'user_profile.py').read_text(),'new code')
   self.assertIn('ishares_holdings.py',apply_update.FILES)
   self.assertEqual((target/'ishares_holdings.py').read_text(),'new code')
   self.assertTrue((target/'var/hotwatch-autostart.enabled').is_file())
   for path in [target/'var/escape.db',backup/'escape.db']:
    with sqlite3.connect(path) as c:self.assertEqual(c.execute('SELECT value FROM preserved').fetchone()[0],'private-data')
 def test_database_snapshot_occurs_with_worker_and_supervisor_quiesced(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));real_connect=sqlite3.connect;observations=[]
   def verify_lock_on_snapshot(database,*args,**kwargs):
    if str(database).endswith('?mode=ro'):
     for name in ('supervisor','worker'):
      fd=os.open(target/'var'/('hotwatch-'+name+'.lock'),os.O_RDWR)
      try:
       try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
       except BlockingIOError:observations.append(name)
       else:fcntl.flock(fd,fcntl.LOCK_UN)
      finally:os.close(fd)
    return real_connect(database,*args,**kwargs)
   with patch('apply_update.sqlite3.connect',side_effect=verify_lock_on_snapshot):apply_update.apply(source,target)
   self.assertEqual(observations,['supervisor','worker'])
 def test_snapshot_failure_preserves_code_and_releases_worker_locks(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d))
   with patch('apply_update.sqlite3.connect',side_effect=sqlite3.OperationalError('synthetic backup failure')):
    with self.assertRaises(sqlite3.OperationalError):apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'old code')
   self.assertFalse((target/'var/hotwatch-autostart.disabled').exists())
   for name in ('supervisor','worker'):
    fd=os.open(target/'var'/('hotwatch-'+name+'.lock'),os.O_RDWR)
    try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);fcntl.flock(fd,fcntl.LOCK_UN)
    finally:os.close(fd)
 def test_backup_restore_after_simulated_migration(self):
  # Only temporary files: demonstrate the existing updater's backup can be
  # independently read and restored after a synthetic schema/data change.
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));backup=apply_update.apply(source,target)
   database=target/'var/escape.db'
   with sqlite3.connect(database) as connection:
    connection.execute('ALTER TABLE preserved ADD COLUMN migration_marker TEXT')
    connection.execute("UPDATE preserved SET value='changed'")
   restored=Path(d)/'isolated-restore';restored.mkdir()
   with sqlite3.connect('file:'+str(backup/'escape.db')+'?mode=ro',uri=True) as snapshot,sqlite3.connect(restored/'escape.db') as destination:
    snapshot.backup(destination)
    self.assertEqual(destination.execute('PRAGMA integrity_check').fetchone()[0],'ok')
    self.assertEqual(destination.execute('SELECT value FROM preserved').fetchone()[0],'private-data')
    self.assertEqual([row[1] for row in destination.execute('PRAGMA table_info(preserved)')],['value'])
   shutil.copy2(backup/'code/app.py',restored/'app.py')
   self.assertEqual((restored/'app.py').read_text(),'old code')
   with sqlite3.connect(database) as connection:self.assertEqual(connection.execute('SELECT value FROM preserved').fetchone()[0],'changed')
 def test_notification_key_is_backed_up_without_replacement(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));key=target/'var/keys/push_vapid.pem';key.parent.mkdir(parents=True);key.write_bytes(b'private-test-key')
   backup=apply_update.apply(source,target)
   self.assertEqual(key.read_bytes(),b'private-test-key');self.assertEqual((backup/'push_vapid.pem').read_bytes(),b'private-test-key');self.assertEqual((backup/'push_vapid.pem').stat().st_mode&0o777,0o600)
 def test_missing_file_changes_nothing(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));(source/'oauth.py').unlink()
   with self.assertRaises(ValueError):apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'old code')
 def test_missing_capacity_module_is_rejected_before_existing_code_changes(self):
  with tempfile.TemporaryDirectory() as d:
   source,target=self.fixture(Path(d));(source/'eodhd_capacity.py').unlink()
   with self.assertRaises(ValueError):apply_update.apply(source,target)
   self.assertEqual((target/'app.py').read_text(),'old code')
   self.assertFalse((target/'hotwatch_warmup.py').exists())
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
