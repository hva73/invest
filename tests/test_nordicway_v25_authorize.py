import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('authorize', Path(__file__).resolve().parents[1] / 'tools/nordicway_v25_authorize.py')
a = importlib.util.module_from_spec(spec)
spec.loader.exec_module(a)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.bridge = self.home / '.escape_deploy_bridge'
        self.app = self.home / 'escape_app'
        self.bridge.mkdir(mode=0o700)
        (self.app / 'var').mkdir(parents=True)
        (self.app / 'var/escape-deploy.lock').touch(mode=0o600)
        (self.app / 'BUILD_COMMIT').write_text(a.INSTALLED + '\n')
        (self.bridge / 'deploy-enabled').write_bytes(b'1\n')
        (self.bridge / 'deploy-enabled').chmod(0o600)
        for name in a.MODULES:
            path = self.bridge / name
            path.write_bytes(('verified:' + name).encode())
            path.chmod(0o600)
        self.blob = lambda sha, name: ('verified:' + Path(name).name).encode()

    def test_authorizes_only_requested_sha(self):
        self.assertEqual(a.authorize(self.home, self.blob), a.CANDIDATE)
        self.assertEqual((self.bridge / 'approved-sha').read_text(), a.CANDIDATE + '\n')
        self.assertEqual((self.bridge / 'approved-sha').stat().st_mode & 0o777, 0o600)

    def test_recovery_marker_blocks_without_approval(self):
        (self.bridge / 'deployment-incomplete.json').touch()
        with self.assertRaisesRegex(ValueError, 'recovery_required'):
            a.authorize(self.home, self.blob)
        self.assertFalse((self.bridge / 'approved-sha').exists())

    def test_bridge_difference_blocks(self):
        (self.bridge / 'nordicway_deploy_guard.py').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'bridge_mismatch'):
            a.authorize(self.home, self.blob)

    def test_changed_installed_version_blocks(self):
        (self.app / 'BUILD_COMMIT').write_text('0' * 40)
        with self.assertRaisesRegex(ValueError, 'installed_version_changed'):
            a.authorize(self.home, self.blob)

    def test_disabled_gate_blocks(self):
        (self.bridge / 'deploy-enabled').write_bytes(b'0\n')
        with self.assertRaisesRegex(ValueError, 'deploy_disabled_or_unsafe'):
            a.authorize(self.home, self.blob)

    def test_symlinked_approval_blocks(self):
        os.symlink(self.app / 'BUILD_COMMIT', self.bridge / 'approved-sha')
        with self.assertRaises(OSError):
            a.authorize(self.home, self.blob)


if __name__ == '__main__':
    unittest.main()
