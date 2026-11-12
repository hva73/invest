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

    def test_current_status_is_owner_scoped_and_reports_expiry(self):
        item=self.candidate()
        self.assertIsNone(a.current(self.connect,8,now=101))
        self.assertEqual(a.current(self.connect,7,now=101)['status'],'pending')
        a.approve(self.connect,item['id'],item['sha'],7,now=102)
        self.assertEqual(a.current(self.connect,7,now=103)['status'],'approved')
        self.assertEqual(a.current(self.connect,7,now=161)['status'],'expired')
        a.claim(self.connect,item['id'],item['sha'],now=104)
        a.finish(self.connect,item['id'],item['sha'],verified=False)
        self.assertEqual(a.current(self.connect,7,now=200)['status'],'recovery')

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

    def test_uncertain_outcome_blocks_new_release_but_verified_completion_does_not(self):
        item = self.candidate()
        a.approve(self.connect, item['id'], item['sha'], 7, now=101)
        a.claim(self.connect, item['id'], item['sha'], now=102)
        with self.assertRaisesRegex(ValueError, 'invalid_result'):
            a.finish(self.connect, item['id'], item['sha'], verified=1)
        self.assertEqual(a.finish(self.connect, item['id'], item['sha'], verified=False)['status'], 'recovery')
        with self.assertRaisesRegex(ValueError, 'release_in_progress'):
            a.prepare(self.connect, 'b'*40, 'Ny version', 7, now=103)
        with self.connect() as c:
            c.execute("UPDATE release_approvals SET status='completed' WHERE id=?",(item['id'],))
        newer = a.prepare(self.connect, 'b'*40, 'Ny version', 7, now=104)
        a.approve(self.connect, newer['id'], newer['sha'], 7, now=105)
        a.claim(self.connect, newer['id'], newer['sha'], now=106)
        self.assertEqual(a.finish(self.connect, newer['id'], newer['sha'], verified=True)['status'], 'completed')
        self.assertIsNotNone(a.prepare(self.connect, 'c'*40, 'Næste version', 7, now=107))

    def test_runner_starts_only_after_matching_approval_and_never_retries(self):
        item=self.candidate(); calls=[]
        def deploy(sha):
            calls.append(sha)
            return {'operation':'deploy','status':'ok','stage':'complete',
                    'recovery_required':False,'service_restored':True}
        with self.assertRaisesRegex(ValueError,'approval_unavailable'):
            a.start_approved(self.connect,item['id'],item['sha'],deploy,now=101)
        self.assertEqual(calls,[])
        a.approve(self.connect,item['id'],item['sha'],7,now=102)
        self.assertEqual(a.start_approved(self.connect,item['id'],item['sha'],deploy,now=103)['status'],'completed')
        self.assertEqual(calls,[item['sha']])
        with self.assertRaisesRegex(ValueError,'approval_unavailable'):
            a.start_approved(self.connect,item['id'],item['sha'],deploy,now=104)
        self.assertEqual(calls,[item['sha']])

    def test_unknown_runner_outcome_requires_recovery(self):
        item=self.candidate();a.approve(self.connect,item['id'],item['sha'],7,now=101)
        result=a.start_approved(self.connect,item['id'],item['sha'],lambda sha: (_ for _ in ()).throw(OSError()),now=102)
        self.assertEqual(result['status'],'recovery')
        with self.assertRaisesRegex(ValueError,'release_in_progress'):
            a.prepare(self.connect,'b'*40,'Ny',7,now=103)

    def test_stage_notification_owner_approval_and_one_runner_call(self):
        calls=[]
        def notify(uid):
            item=a.pending(self.connect,uid,now=101)
            a.approve(self.connect,item['id'],item['sha'],uid,now=102)
        def deploy(sha):
            calls.append(sha)
            return {'operation':'deploy','status':'ok','stage':'complete',
                    'recovery_required':False,'service_restored':True}
        times=iter([100,103,103])
        result=a.stage_and_wait(self.connect,'a'*40,'Test',7,notify,deploy,
                                lifetime=60,clock=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(result['status'],'completed');self.assertEqual(calls,['a'*40])

    def test_push_failure_keeps_admin_path_and_timeout_never_deploys(self):
        times=iter([100,101,102,160]);calls=[]
        result=a.stage_and_wait(self.connect,'a'*40,'Test',7,
            lambda _:(_ for _ in ()).throw(OSError()),lambda sha:calls.append(sha),
            lifetime=60,clock=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(result['status'],'expired');self.assertEqual(calls,[])
        with self.assertRaisesRegex(ValueError,'approval_unavailable'):
            a.approve(self.connect,result['id'],result['sha'],7,now=160)


if __name__ == '__main__':
    unittest.main()
