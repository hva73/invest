import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import unittest
import nordicway_deploy_guard as guard

class GuardTests(unittest.TestCase):
    def test_ping_and_deploy_blocked(self):
        self.assertEqual(guard.dispatch('escape-deploy-v1 ping')['status'], 'ok')
        self.assertEqual(guard.dispatch('escape-deploy-v1 deploy ' + 'a' * 40)['status'], 'blocked')

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

    def test_resume_requires_exact_sha_and_fixed_handler(self):
        seen = []
        self.assertEqual(guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40)['status'], 'blocked')
        result = guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40,
                                recovery=lambda sha: seen.append(sha) or {'status': 'ok'})
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(seen, ['a' * 40])
        with self.assertRaises(ValueError):
            guard.dispatch('escape-deploy-v1 resume ' + 'a' * 40 + ';id', recovery=lambda sha: None)

if __name__ == '__main__':
    unittest.main()
