import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hashlib
import tempfile
import unittest
from pathlib import Path
import nordicway_provision_deploy as p

KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKcXPr/KFsF9ObTXmb9cK5XQWl3UHuQWSqazGCxWd0EU deploy-test'
DATA = b'guard test bytes'
HASH = hashlib.sha256(DATA).hexdigest()

class ProvisionTests(unittest.TestCase):
    def test_preserves_key_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); ssh = home / '.ssh'; ssh.mkdir(mode=0o700)
            auth = ssh / 'authorized_keys'; auth.write_text('existing\n'); auth.chmod(0o600)
            self.assertEqual(p.provision(home, '/bin/sh', KEY, DATA, HASH), 'configured')
            saved = auth.read_text()
            self.assertTrue(saved.startswith('existing\n'))
            self.assertIn('restrict,command=', saved)
            self.assertEqual(p.provision(home, '/bin/sh', KEY, DATA, HASH), 'already_configured')
            self.assertEqual(auth.read_text(), saved)

    def test_duplicate_unrestricted_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root); ssh = home / '.ssh'; ssh.mkdir(mode=0o700)
            auth = ssh / 'authorized_keys'; auth.write_text(KEY + '\n'); auth.chmod(0o600)
            with self.assertRaisesRegex(ValueError, 'key_already_authorized_differently'):
                p.provision(home, '/bin/sh', KEY, DATA, HASH)
            self.assertEqual(auth.read_text(), KEY + '\n')

    def test_invalid_hash_key_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            for key, digest in (('ssh-ed25519 bad', HASH), (KEY, '0' * 64)):
                with self.assertRaises(ValueError):
                    p.provision(home, '/bin/sh', key, DATA, digest)
            self.assertFalse((home / '.ssh').exists())
            (home / '.ssh').symlink_to(home)
            with self.assertRaises(ValueError):
                p.provision(home, '/bin/sh', KEY, DATA, HASH)

if __name__ == '__main__':
    unittest.main()
