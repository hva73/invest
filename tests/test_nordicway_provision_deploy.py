import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hashlib
import subprocess
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

    def test_cpanel_rsa_key_is_restricted_and_existing_key_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root)
            keyfile = home / 'test-key'
            subprocess.run(['ssh-keygen', '-q', '-t', 'rsa', '-b', '2048', '-N', '',
                            '-f', str(keyfile)], check=True, capture_output=True)
            key = keyfile.with_suffix('.pub').read_text().strip()
            (home / '.ssh').mkdir(mode=0o700)
            auth = home / '.ssh' / 'authorized_keys'
            auth.write_text('existing-key\n')
            auth.chmod(0o600)
            self.assertEqual(p.provision(home, '/bin/sh', key, DATA, HASH), 'configured')
            self.assertIn('existing-key\nrestrict,command=', auth.read_text())
            self.assertIn(key, auth.read_text())
            self.assertEqual(p.provision(home, '/bin/sh', key, DATA, HASH), 'already_configured')

    def test_small_rsa_key_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            keyfile = Path(root) / 'weak-key'
            subprocess.run(['ssh-keygen', '-q', '-t', 'rsa', '-b', '1024', '-N', '',
                            '-f', str(keyfile)], check=True, capture_output=True)
            with self.assertRaisesRegex(ValueError, 'invalid_key'):
                p._public_key(keyfile.with_suffix('.pub').read_text())

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
