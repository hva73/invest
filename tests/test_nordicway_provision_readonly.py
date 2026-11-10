import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_provision_readonly as provision

PUBLIC_KEY = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKcXPr/KFsF9ObTXmb9cK5XQWl3UHuQWSqazGCxWd0EU escape-diagnostics'


class Provision(unittest.TestCase):
    def test_preserves_keys_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); ssh = home / '.ssh'; ssh.mkdir(mode=0o700)
            auth = ssh / 'authorized_keys'; auth.write_text('existing-key\n'); auth.chmod(0o600)
            with patch.object(provision, 'read_git_file', side_effect=lambda checkout, name: name.encode()):
                self.assertEqual(provision.provision(home, home, '/bin/sh', PUBLIC_KEY), 'configured')
                first = auth.read_text()
                self.assertTrue(first.startswith('existing-key\n'))
                self.assertIn('restrict,command="/bin/sh -I -S ', first)
                self.assertEqual(provision.provision(home, home, '/bin/sh', PUBLIC_KEY), 'already_configured')
                self.assertEqual(auth.read_text(), first)

    def test_rejects_unrestricted_duplicate_and_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp); ssh = home / '.ssh'; ssh.mkdir(mode=0o700)
            auth = ssh / 'authorized_keys'; auth.write_text(PUBLIC_KEY + '\n'); auth.chmod(0o600)
            with patch.object(provision, 'read_git_file', return_value=b'guard'):
                with self.assertRaisesRegex(ValueError, 'key_already_authorized_differently'):
                    provision.provision(home, home, '/bin/sh', PUBLIC_KEY)
                self.assertEqual(auth.read_text(), PUBLIC_KEY + '\n')
                auth.unlink(); auth.symlink_to(home / 'elsewhere')
                with self.assertRaisesRegex(ValueError, 'unsafe_authorized_keys'):
                    provision.provision(home, home, '/bin/sh', PUBLIC_KEY)

    def test_rejects_bad_key_before_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            with self.assertRaisesRegex(ValueError, 'invalid_setup'):
                provision.provision(home, home, '/bin/sh', 'ssh-ed25519 bad;id')
            self.assertFalse((home / '.ssh').exists())


if __name__ == '__main__':
    unittest.main()
