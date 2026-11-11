import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_upgrade_probe_guard as upgrade

OLD = b'print("ping only")\n'
NEW = b'print("ping and write probe")\n'


class GuardUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.bridge = Path(self.temp.name)
        self.target = self.bridge / 'nordicway_deploy_guard.py'
        self.target.write_bytes(OLD)
        self.target.chmod(0o600)
        self.patches = patch.multiple(upgrade, OLD_SHA256=hashlib.sha256(OLD).hexdigest(),
                                      NEW_SHA256=hashlib.sha256(NEW).hexdigest())
        self.patches.start()

    def tearDown(self):
        self.patches.stop()
        self.temp.cleanup()

    def test_upgrade_is_atomic_and_idempotent(self):
        self.assertEqual(upgrade.upgrade(self.bridge, NEW), 'installed')
        self.assertEqual(self.target.read_bytes(), NEW)
        self.assertEqual(upgrade.upgrade(self.bridge, NEW), 'already_installed')
        self.assertEqual(sorted(x.name for x in self.bridge.iterdir()), [self.target.name])

    def test_refuses_wrong_existing_or_new_hash(self):
        with self.assertRaises(ValueError):
            upgrade.upgrade(self.bridge, b'bad')
        self.target.write_bytes(b'unexpected')
        with self.assertRaises(ValueError):
            upgrade.upgrade(self.bridge, NEW)
        self.assertEqual(self.target.read_bytes(), b'unexpected')

    def test_refuses_enabled_deploy_and_symlink(self):
        (self.bridge / 'deploy-enabled').touch()
        with self.assertRaises(ValueError):
            upgrade.upgrade(self.bridge, NEW)
        (self.bridge / 'deploy-enabled').unlink()
        self.target.unlink()
        self.target.symlink_to('/dev/null')
        with self.assertRaises(ValueError):
            upgrade.upgrade(self.bridge, NEW)
