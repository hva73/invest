import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from tools import nordicway_upgrade_updater as u

class UpdaterUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.bridge=self.root/"bridge";self.bridge.mkdir(mode=0o700)
        self.app=self.root/"app";self.app.mkdir();(self.app/"var").mkdir()
        self.old=b"FILES=('app.py',)\n"
        self.new=("FILES="+repr(tuple(sorted(u.ADDED))+("app.py",))+"\n").encode()
        self.adapter=b"reviewed adapter fixture"
        self.patch=patch.multiple(u,OLD_UPDATER=u.digest(self.old),ADAPTER_HASH=u.digest(self.adapter),NEW_BLOB=u.git_blob(self.new))
        self.patch.start();self.addCleanup(self.patch.stop)
        for name,data in (("apply_update.py",self.old),("nordicway_deploy_adapter.py",self.adapter),
                          ("approved-sha",(u.RELEASE_SHA+"\n").encode()),("deploy-enabled",b"1\n")):
            u.write_new(self.bridge/name,data)
        (self.app/"BUILD_COMMIT").write_text(u.CURRENT_BUILD+"\n")
        (self.app/"var/escape.db").write_bytes(b"database sentinel")
    def test_exact_updater_only_preserves_gate_approval_db_and_backup(self):
        result=u.upgrade(self.bridge,self.app,self.new)
        self.assertEqual((result["old_manifest"],result["new_manifest"]),(1,5))
        self.assertEqual((self.bridge/"apply_update.py").read_bytes(),self.new)
        self.assertEqual((self.bridge/"nordicway_deploy_adapter.py").read_bytes(),self.adapter)
        self.assertEqual((self.bridge/"deploy-enabled").read_bytes(),b"1\n")
        self.assertEqual((self.bridge/"approved-sha").read_text().strip(),u.RELEASE_SHA)
        self.assertEqual((self.app/"var/escape.db").read_bytes(),b"database sentinel")
        self.assertEqual([p.read_bytes() for p in (self.bridge/"bridge-backups").glob("*/apply_update.py")],[self.old])
        self.assertFalse((self.bridge/"deploy-enabled.updater-held").exists())
    def test_invalid_candidate_and_recovery_fail_without_mutation(self):
        with self.assertRaisesRegex(ValueError,"candidate_blob_mismatch"):
            u.upgrade(self.bridge,self.app,b"FILES=('other.py',)")
        (self.bridge/"deployment-incomplete.json").write_text("{}")
        with self.assertRaisesRegex(ValueError,"recovery_or_upgrade_in_progress"):
            u.upgrade(self.bridge,self.app,self.new)
        self.assertEqual((self.bridge/"apply_update.py").read_bytes(),self.old)
        self.assertTrue((self.bridge/"deploy-enabled").is_file())
    def test_changed_adapter_rejected(self):
        (self.bridge/"nordicway_deploy_adapter.py").write_bytes(b"different")
        with self.assertRaisesRegex(ValueError,"bridge_source_changed"):
            u.upgrade(self.bridge,self.app,self.new)
        self.assertTrue((self.bridge/"deploy-enabled").is_file())
    def test_failed_stage_keeps_gate_closed_and_original_intact(self):
        with patch.object(u,"write_new",side_effect=OSError("fixture")):
            with self.assertRaises(OSError):u.upgrade(self.bridge,self.app,self.new)
        self.assertFalse((self.bridge/"deploy-enabled").exists())
        self.assertEqual((self.bridge/"deploy-enabled.updater-held").read_bytes(),b"1\n")
        self.assertEqual((self.bridge/"apply_update.py").read_bytes(),self.old)
        self.assertEqual((self.app/"var/escape.db").read_bytes(),b"database sentinel")
    def test_lock_conflict_leaves_gate(self):
        import fcntl
        path=self.app/"var/escape-deploy.lock"
        with path.open("wb") as lock:
            path.chmod(0o600);fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):u.upgrade(self.bridge,self.app,self.new)
        self.assertTrue((self.bridge/"deploy-enabled").is_file())
    def test_pinned_candidate_in_repository(self):
        # Fixture hashes are patched; verify the actual Git object separately.
        source=u.candidate_source(Path(__file__).resolve().parents[1])
        self.assertEqual(u.git_blob(source),"c507247a7264c05154155ac5966de35200adf160")
        self.assertEqual(len(u.manifest(source)),81)
