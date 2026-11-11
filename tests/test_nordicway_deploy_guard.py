import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import unittest
import os
import tempfile
import nordicway_deploy_guard as guard

class GuardTests(unittest.TestCase):
    def test_ping_and_deploy_blocked(self):
        self.assertEqual(guard.dispatch('escape-deploy-v1 ping')['status'], 'ok')
        self.assertEqual(guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40)['status'], 'blocked')

    def test_write_probe_creates_verifies_and_removes_only_fixed_marker(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(guard.write_probe(root),
                             {'status': 'ok', 'operation': 'write_probe'})
            self.assertEqual(os.listdir(root), [])
            self.assertEqual(guard.dispatch('escape-deploy-v1 write-probe',
                                           probe=lambda: guard.write_probe(root))['status'], 'ok')

    def test_write_probe_rejects_preexisting_file_without_modification(self):
        with tempfile.TemporaryDirectory() as root:
            marker = Path(root) / guard.PROBE_FILENAME
            marker.write_text('existing')
            with self.assertRaises(FileExistsError):
                guard.write_probe(root)
            self.assertEqual(marker.read_text(), 'existing')

    def test_write_probe_rejects_symlink_directory(self):
        with tempfile.TemporaryDirectory() as root:
            actual = Path(root) / 'actual'
            actual.mkdir()
            symlink = Path(root) / 'link'
            symlink.symlink_to(actual, target_is_directory=True)
            with self.assertRaises(OSError):
                guard.write_probe(symlink)
            self.assertEqual(os.listdir(actual), [])

    def test_write_probe_does_not_expand_command_surface(self):
        for cmd in ('escape-deploy-v1 write-probe x',
                    'escape-deploy-v1 write-probe;id',
                    'escape-deploy-v1 write-probe\\n'):
            with self.assertRaises(ValueError):
                guard.dispatch(cmd, probe=lambda: {'status': 'ok'})

    def test_rejects_arbitrary_commands(self):
        for cmd in ('', 'id', 'escape-deploy-v1 deploy HEAD',
                    'escape-deploy-v1 deploy ' + 'a' * 40 + ';id',
                    'escape-deploy-v1 deploy ' + 'A' * 40, 'escape-deploy-v1 ping\nid'):
            with self.assertRaises(ValueError):
                guard.dispatch(cmd)

    def test_only_exact_deploy_command_reaches_runner(self):
        seen = []
        def runner(sha):
            seen.append(sha)
            return {'status': 'ok', 'operation': 'deploy'}
        sha = 'b' * 40
        self.assertEqual(guard.dispatch('escape-deploy-v1 deploy ' + sha, runner)['status'], 'ok')
        self.assertEqual(seen, [sha])
        with self.assertRaises(ValueError):
            guard.dispatch('escape-deploy-v1 deploy ' + sha + ';id', runner)
        self.assertEqual(seen, [sha])

if __name__ == '__main__':
    unittest.main()
