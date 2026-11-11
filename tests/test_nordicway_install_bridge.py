import hashlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_install_bridge as bridge_installer


class BridgeInstallerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.bridge = self.root / '.escape_deploy_bridge'
        self.bridge.mkdir(mode=0o700)
        self.guard = self.bridge / 'nordicway_deploy_guard.py'
        self.guard.write_bytes(b'old guard')
        self.guard.chmod(0o600)
        self.files = {
            'nordicway_deploy_guard.py': b"PROTOCOL='escape-deploy-v1'\n",
            'nordicway_deploy_runner.py': b"x=1\n",
            'apply_update.py': b"FILES=()\n",
        }
        self.sha = 'a' * 40

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self):
        with patch.object(bridge_installer, '_sources', return_value=self.files), \\
                patch.object(bridge_installer, 'OLD_GUARD_SHA256',
                             hashlib.sha256(b'old guard').hexdigest()):
            return bridge_installer.install(self.root, self.bridge, self.sha)

    def test_stages_pinned_bridge_and_preserves_previous_guard(self):
        result = self._run()
        self.assertEqual(result['status'], 'installed_disabled')
        self.assertEqual(result['file_count'], 3)
        self.assertFalse((self.bridge / 'deploy-enabled').exists())
        for name, data in self.files.items():
            self.assertEqual((self.bridge / name).read_bytes(), data)
            self.assertEqual(stat.S_IMODE((self.bridge / name).stat().st_mode), 0o600)
        backup = next((self.bridge / 'bridge-backups').iterdir())
        self.assertEqual((backup / 'nordicway_deploy_guard.py').read_bytes(), b'old guard')

    def test_does_not_touch_anything_when_deploy_enabled(self):
        (self.bridge / 'deploy-enabled').write_text('1\n')
        with self.assertRaisesRegex(ValueError, 'deployment_must_be_disabled'):
            self._run()
        self.assertEqual(self.guard.read_bytes(), b'old guard')

    def test_unknown_installed_guard_is_rejected(self):
        with patch.object(bridge_installer, '_sources', return_value=self.files):
            with self.assertRaisesRegex(ValueError, 'unexpected_guard_version'):
                bridge_installer.install(self.root, self.bridge, self.sha)
        self.assertFalse((self.bridge / 'nordicway_deploy_runner.py').exists())

    def test_preexisting_symlink_module_is_rejected(self):
        (self.bridge / 'nordicway_deploy_runner.py').symlink_to(self.guard)
        with self.assertRaisesRegex(ValueError, 'unsafe_bridge_file'):
            self._run()
        self.assertEqual(self.guard.read_bytes(), b'old guard')

    def test_approval_file_is_untouched(self):
        marker = self.bridge / 'approved-sha'
        marker.write_text('b' * 40)
        self._run()
        self.assertEqual(marker.read_text(), 'b' * 40)

    def test_bad_sha_is_rejected_before_git_or_writes(self):
        with self.assertRaisesRegex(ValueError, 'invalid_sha'):
            bridge_installer._sources(self.root, 'HEAD')


if __name__ == '__main__':
    unittest.main()
