import sqlite3
import tempfile
import unittest
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import release_approval as a


class ReleaseApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'db'
        with self.connect() as c:
            a.init(c)

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def candidate(self):
        return a.prepare(self.connect, 'a' * 40, 'Mobil og datarettelser', 7, now=100, lifetime=60)

    def test_correct_owner_and_version_approves_once(self):
        item = self.candidate()
        self.assertEqual(a.pending(self.connect, 7, now=101)['sha'], item['sha'])
        for uid, sha in ((8, item['sha']), (7, 'b' * 40)):
            with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
                a.approve(self.connect, item['id'], sha, uid, now=102)
        self.assertEqual(a.approve(self.connect, item['id'], item['sha'], 7, now=102)['status'], 'approved')
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.approve(self.connect, item['id'], item['sha'], 7, now=103)

    def test_expired_and_replaced_candidates_cannot_be_approved(self):
        old = self.candidate()
        new = a.prepare(self.connect, 'b' * 40, 'Ny version', 7, now=101, lifetime=10)
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.approve(self.connect, old['id'], old['sha'], 7, now=102)
        self.assertIsNone(a.pending(self.connect, 7, now=111))
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.approve(self.connect, new['id'], new['sha'], 7, now=111)

    def test_parallel_approval_only_succeeds_once(self):
        item = self.candidate()
        def attempt(_):
            try:
                return a.approve(self.connect, item['id'], item['sha'], 7, now=101)['status']
            except ValueError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            self.assertEqual(sorted(pool.map(attempt, range(2))), ['approved', 'rejected'])

    def test_claim_is_single_use_and_bound_to_candidate(self):
        item = self.candidate()
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.claim(self.connect, item['id'], item['sha'], now=101)
        a.approve(self.connect, item['id'], item['sha'], 7, now=102)
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.claim(self.connect, item['id'], 'b' * 40, now=103)
        self.assertEqual(a.claim(self.connect, item['id'], item['sha'], now=103)['status'], 'claimed')
        with self.assertRaisesRegex(ValueError, 'release_in_progress'):
            a.prepare(self.connect, 'c' * 40, 'Anden version', 7, now=103)
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.claim(self.connect, item['id'], item['sha'], now=104)

    def test_new_candidate_cancels_older_unused_approval(self):
        item = self.candidate()
        a.approve(self.connect, item['id'], item['sha'], 7, now=101)
        a.prepare(self.connect, 'b' * 40, 'Ny version', 7, now=102)
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            a.claim(self.connect, item['id'], item['sha'], now=103)


if __name__ == '__main__':
    unittest.main()
