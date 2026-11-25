import gzip,hashlib,importlib,os,pathlib,sqlite3,sys,tempfile,unittest
from contextlib import closing
from unittest.mock import patch
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"tools"))
import nordicway_phase_backup as phase
import nordicway_install_phase_bridge as installer

class PhaseTests(unittest.TestCase):
    def test_budget_preserves_full_restart_reserve(self):
        plan=phase.budget(6848282624,5_000_000,5_000_000,9_964_079_104)
        self.assertEqual(plan["archive_cap"]+plan["restart_reserve"],plan["required_bytes"])
        self.assertGreater(plan["restart_reserve"],6848282624)
        self.assertLessEqual(plan["required_bytes"],9_964_079_104)
        with self.assertRaises(ValueError):
            phase.budget(6848282624,5_000_000,5_000_000,7_000_000_000)

    def test_actual_locked_snapshot_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);db=root/"live.sqlite";gz=root/"backup.gz";restore=root/"restore.sqlite"
            with closing(sqlite3.connect(db)) as c:
                c.execute("CREATE TABLE sample(id INTEGER PRIMARY KEY,value BLOB)")
                c.executemany("INSERT INTO sample VALUES(?,?)",((i,os.urandom(2048)) for i in range(1,101)));c.commit()
            original=db.read_bytes()
            with phase.snapshot(db,gz,len(original)*2,len(original)) as m:
                self.assertEqual(m["database_sha256"],hashlib.sha256(original).hexdigest())
                with closing(sqlite3.connect(db,timeout=.01)) as c:
                    with self.assertRaises(sqlite3.OperationalError):c.execute("INSERT INTO sample VALUES(101,?)",(b"bad",))
            self.assertEqual(db.read_bytes(),original)
            restore.write_bytes(gzip.decompress(gz.read_bytes()))
            with closing(sqlite3.connect(restore)) as c:
                self.assertEqual(c.execute("PRAGMA integrity_check").fetchone(),("ok",))
                self.assertEqual(c.execute("SELECT count(*) FROM sample").fetchone(),(100,))
            self.assertEqual(phase.gzip_digest(gz,len(original)),hashlib.sha256(original).hexdigest())
            with self.assertRaises(phase.SnapshotFailure):
                with phase.snapshot(db,root/"small.gz",10,len(original)): self.fail("unexpected publication")
            self.assertFalse((root/"small.gz").exists())
            self.assertEqual(db.read_bytes(),original)
            with gz.open("r+b") as f:f.seek(-8,os.SEEK_END);f.write(b"bad!")
            with self.assertRaises((gzip.BadGzipFile,ValueError)):
                phase.gzip_digest(gz,len(original))

    def test_owner_installer_preserves_approval_and_originals(self):
        history=ROOT/"bridge-history/tools"
        old={n:((ROOT/n) if n=="apply_update.py" else (history/n)).read_bytes() for n in installer.HASHES}
        helper=(ROOT/"tools"/installer.HELPER).read_bytes()
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td); b=root/"bridge"; b.mkdir(mode=0o700)
            app=root/"app"; (app/"var").mkdir(parents=True)
            for n,data in old.items():installer.write(b/n,data)
            installer.write(b/"deploy-enabled",b"1\n")
            installer.write(b/"approved-sha",installer.RELEASE.encode()+b"\n")
            installer.write(app/"BUILD_COMMIT",installer.INSTALLED.encode()+b"\n")
            self.assertEqual(installer.install(b,app,helper,False)["status"],"preflight_pass")
            self.assertFalse((b/installer.HELPER).exists())
            report=installer.install(b,app,helper,True)
            self.assertEqual(report["status"],"phase_bridge_installed")
            self.assertEqual((b/"deploy-enabled").read_bytes(),b"1\n")
            self.assertEqual((b/"approved-sha").read_text().strip(),installer.RELEASE)
            self.assertEqual((app/"BUILD_COMMIT").read_text().strip(),installer.INSTALLED)
            for n in report["modules"]:
                if n in old:self.assertEqual((b/"bridge-backups"/report["backup"]/n).read_bytes(),old[n])
            self.assertFalse((b/"deploy-enabled.phase-held").exists())
    def test_real_bridge_patch_and_apply(self):
        history=ROOT/"bridge-history/tools"
        if not history.exists(): self.fail("historical bridge checkout missing")
        old={name:(history/name).read_bytes() for name in installer.HASHES if name!="apply_update.py"}
        old["apply_update.py"]=(ROOT/"apply_update.py").read_bytes()
        for name,content in old.items():
            self.assertEqual(hashlib.sha256(content).hexdigest(),installer.HASHES[name],name)
            print("Fixture",name,hashlib.sha256(content).hexdigest(),flush=True)
        result=installer.patch(old,(ROOT/"tools"/installer.HELPER).read_bytes())
        with tempfile.TemporaryDirectory() as d:
            root=pathlib.Path(d);bridge=root/"bridge";bridge.mkdir()
            for path in history.glob("*.py"):(bridge/path.name).write_bytes(path.read_bytes())
            for name,content in result.items():(bridge/name).write_bytes(content)
            app=root/"app";var=app/"var";var.mkdir(parents=True);stage=app/"opdatering/release";stage.mkdir(parents=True)
            db=var/"escape.db"
            with closing(sqlite3.connect(db)) as c:
                c.execute("CREATE TABLE evidence(id INTEGER PRIMARY KEY, value TEXT)")
                c.execute("INSERT INTO evidence VALUES(1,'preserve')");c.commit()
            original=db.read_bytes()
            sys.path.insert(0,str(bridge))
            saved={name:sys.modules.pop(name,None) for name in ("apply_update","nordicway_release_backup","nordicway_phase_backup")}
            try:
                updater=importlib.import_module("apply_update");backup=importlib.import_module("nordicway_release_backup")
                for name in updater.FILES:
                    p=stage/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("new "+name)
                    p=app/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("old "+name)
                expected=backup.inventory(app,updater.FILES)
                path=updater.apply(stage,app,verify_backup=lambda p:backup.verify_backup(p,expected),
                    compressed_plan={"archive_cap":len(original)*2,"db_bytes":len(original)})
                self.assertFalse((path/"escape.db").exists())
                self.assertTrue(backup.verify_backup(path,expected))
                self.assertEqual(gzip.decompress((path/"escape.db.gz").read_bytes()),original)
                self.assertEqual(db.read_bytes(),original)
                for name in updater.FILES:self.assertEqual((app/name).read_text(),"new "+name)
                # A failed capped snapshot cannot replace any product code.
                stage2=app/"opdatering/release2";stage2.mkdir()
                for name in updater.FILES:
                    p=stage2/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text("next "+name)
                with self.assertRaises(phase.SnapshotFailure if sys.modules["nordicway_phase_backup"] is phase else sys.modules["nordicway_phase_backup"].SnapshotFailure):
                    updater.apply(stage2,app,verify_backup=lambda p:True,
                        compressed_plan={"archive_cap":10,"db_bytes":len(original)})
                for name in updater.FILES:self.assertEqual((app/name).read_text(),"new "+name)
                self.assertEqual(db.read_bytes(),original)
                self.assertTrue(backup.verify_backup(path,expected))
            finally:
                sys.path.remove(str(bridge))
                for name,obj in saved.items():
                    sys.modules.pop(name,None)
                    if obj is not None:sys.modules[name]=obj

if __name__=="__main__":unittest.main()
