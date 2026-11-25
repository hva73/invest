import errno
import os,sqlite3,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock, patch
import release_approval
from tools import nordicway_app_release as bridge


class AppReleaseBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'db'
        self.bridge=self.root/'bridge';self.bridge.mkdir(mode=0o700)
        key=self.bridge/'owner-approval-key';key.write_bytes(b'k'*32);key.chmod(0o600)
        with self.connect() as c:
            c.execute('CREATE TABLE users(id INTEGER,username TEXT,role TEXT,active INTEGER)')
            c.execute("INSERT INTO users VALUES(7,'owner','admin',1)")
            release_approval.init(c)

    def connect(self):return sqlite3.connect(self.path,timeout=5)

    def test_owner_click_then_runner_receives_only_approved_sha(self):
        calls=[];times=iter([100,103,103])
        def notify(uid):
            candidate=release_approval.pending(self.connect,uid,now=101)
            release_approval.approve(self.connect,candidate['id'],candidate['sha'],uid,now=102)
        def proof(sha,key):
            self.assertEqual(key,b'k'*32);return {'test':'proof','sha':sha}
        def runner(sha,token,owner_request):
            calls.append((sha,token,owner_request))
            return {'operation':'deploy','status':'ok','stage':'complete','service_restored':True,'recovery_required':False}
        result=bridge.run(self.connect,'a'*40,'Test release','t'*40,self.bridge,runner=runner,
                          create_proof=proof,notify=notify,clock=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(result['status'],'completed');self.assertEqual(len(calls),1)
        self.assertEqual(calls[0][0],'a'*40);self.assertEqual(calls[0][2]['sha'],'a'*40)
        self.assertNotIn('t'*40,str(result));self.assertNotIn('proof',str(result))

    def test_invalid_key_stops_before_runner_and_requires_recovery(self):
        (self.bridge/'owner-approval-key').chmod(0o644);times=iter([100,103,103]);calls=[]
        def notify(uid):
            candidate=release_approval.pending(self.connect,uid,now=101)
            release_approval.approve(self.connect,candidate['id'],candidate['sha'],uid,now=102)
        result=bridge.run(self.connect,'a'*40,'Test','t'*40,self.bridge,runner=lambda *a,**k:calls.append(1),
                          create_proof=lambda *a:{},notify=notify,clock=lambda:next(times),sleep=lambda _:None)
        self.assertEqual(result['status'],'recovery');self.assertEqual(calls,[])

    def test_unknown_owner_rejected_before_staging(self):
        with self.connect() as c:c.execute('UPDATE users SET active=0')
        with self.assertRaisesRegex(ValueError,'owner_unavailable'):
            bridge.run(self.connect,'a'*40,'Test','t'*40,self.bridge,runner=None,create_proof=None,notify=None)

    def public_directory(self, state='normal'):
        directory = self.root.resolve() / 'public-release'
        directory.mkdir(exist_ok=True)
        status = directory / 'status.json'
        status.write_text('{"state":"' + state + '"}\n')
        return status

    def approved_release(self, runner, directory, *, notify=None, times=(100, 103, 103)):
        def approve(uid):
            candidate = release_approval.pending(self.connect, uid, now=101)
            release_approval.approve(self.connect, candidate['id'], candidate['sha'], uid, now=102)

        clock = iter(times)
        return bridge.run(
            self.connect, 'a'*40, 'Test', 't'*40, self.bridge,
            runner=runner, create_proof=lambda sha, key: {'sha': sha},
            notify=approve if notify is None else notify, clock=lambda: next(clock),
            sleep=lambda _: None, public_status_dir=directory,
        )

    def test_public_maintenance_wraps_only_approved_runner(self):
        status = self.public_directory()

        def runner(sha, token, owner_request):
            self.assertEqual(status.read_text(), '{"state":"maintenance"}\n')
            self.assertEqual(owner_request, {'sha': sha})
            with self.assertRaisesRegex(ValueError, 'release_in_progress'):
                self.approved_release(Mock(), status.parent)
            with self.assertRaises(BlockingIOError):
                bridge._open_status_directory(status.parent)
            return dict(operation='deploy', status='ok', stage='complete',
                        service_restored=True, recovery_required=False)

        result = self.approved_release(runner, status.parent)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(status.read_text(), '{"state":"normal"}\n')

    def test_unapproved_expired_and_repeated_requests_do_not_run(self):
        status = self.public_directory()
        runner = Mock()
        rejected = []

        def reject_wrong_commit(uid):
            candidate = release_approval.pending(self.connect, uid, now=101)
            try:
                release_approval.approve(self.connect, candidate['id'], 'b'*40, uid, now=102)
            except ValueError as exc:
                rejected.append(str(exc))

        self.assertEqual(self.approved_release(runner, status.parent, notify=reject_wrong_commit,
                                               times=(100, 103, 701))['status'], 'expired')
        self.assertEqual(rejected, ['approval_unavailable'])
        self.assertEqual(self.approved_release(runner, status.parent, notify=lambda uid: None,
                                               times=(100, 701))['status'], 'expired')
        with self.assertRaisesRegex(ValueError, 'approval_unavailable'):
            self.approved_release(runner, status.parent, times=(100, 103, 701))
        self.assertEqual(status.read_text(), '{"state":"normal"}\n')
        runner.assert_not_called()

    def test_public_final_state_follows_runner_contract(self):
        cases = [
            ('failed', 'preflight', False, False, 'normal', 'failed'),
            ('failed', 'drain', True, False, 'normal', 'recovery'),
            ('failed', 'drain', True, True, 'recovery', 'recovery'),
            ('failed', 'health', True, False, 'recovery', 'recovery'),
            ('updated_stopped', 'complete', False, False, 'recovery', 'recovery'),
            ('ok', 'complete', False, False, 'recovery', 'recovery'),
        ]
        for status, stage, restored, required, public, private in cases:
            with self.subTest(status=status, stage=stage, required=required):
                with self.connect() as c:
                    c.execute('DELETE FROM release_approvals')
                path = self.public_directory()
                runner = Mock(return_value=dict(operation='deploy', status=status, stage=stage,
                                                service_restored=restored, recovery_required=required))
                self.assertEqual(self.approved_release(runner, path.parent)['status'], private)
                runner.assert_called_once()
                self.assertEqual(path.read_text(), '{"state":"' + public + '"}\n')

    def test_runner_exception_publishes_recovery(self):
        status = self.public_directory()
        result = self.approved_release(Mock(side_effect=OSError('private detail')), status.parent)
        self.assertEqual(result['status'], 'recovery')
        self.assertEqual(status.read_text(), '{"state":"recovery"}\n')

    def test_stale_or_unsafe_status_is_never_overwritten(self):
        for state in ('maintenance', 'recovery', 'unrecognized', 'missing', 'symlink',
                      'hardlink', 'directory_symlink'):
            with self.subTest(state=state):
                with self.connect() as c:
                    c.execute('DELETE FROM release_approvals')
                path = self.public_directory(state)
                target = self.root / 'unrelated'
                target.write_text('{"state":"normal"}\n')
                directory = path.parent
                if state in ('missing', 'symlink', 'hardlink'):
                    path.unlink()
                if state == 'symlink':
                    path.symlink_to(target)
                elif state == 'hardlink':
                    os.link(target, path)
                elif state == 'directory_symlink':
                    directory = self.root / 'alias'
                    directory.symlink_to(path.parent, target_is_directory=True)
                runner = Mock()
                self.assertEqual(self.approved_release(runner, directory)['status'], 'recovery')
                runner.assert_not_called()
                self.assertEqual(target.read_text(), '{"state":"normal"}\n')
                if state != 'missing':
                    self.assertEqual(path.read_text(), target.read_text() if state in (
                        'symlink', 'hardlink') else '{"state":"' + state + '"}\n')
                if state in ('symlink', 'hardlink'):
                    path.unlink()

    def test_publication_error_prevents_runner_and_cleans_temp_file(self):
        status = self.public_directory()
        runner = Mock()
        with patch.object(bridge.os, 'replace', side_effect=OSError(errno.ENOSPC, 'full')):
            result = self.approved_release(runner, status.parent)
        self.assertEqual(result['status'], 'recovery')
        self.assertEqual(list(status.parent.iterdir()), [status])
        self.assertEqual(status.read_text(), '{"state":"normal"}\n')
        runner.assert_not_called()

    def test_final_publication_failure_leaves_maintenance(self):
        status = self.public_directory()

        def runner(*args, **kwargs):
            replacement.side_effect = OSError(errno.ENOSPC, 'full')
            return dict(operation='deploy', status='ok', stage='complete',
                        service_restored=True, recovery_required=False)

        with patch.object(bridge.os, 'replace', wraps=os.replace) as replacement:
            result = self.approved_release(runner, status.parent)
        self.assertEqual(result['status'], 'recovery')
        self.assertEqual(status.read_text(), '{"state":"maintenance"}\n')

    def test_directory_sync_failure_after_replace_prevents_runner(self):
        status = self.public_directory()
        runner = Mock()
        with patch.object(bridge.os, 'fsync', side_effect=[None, OSError(errno.EIO, 'sync')]):
            result = self.approved_release(runner, status.parent)
        self.assertEqual(result['status'], 'recovery')
        self.assertEqual(status.read_text(), '{"state":"maintenance"}\n')
        runner.assert_not_called()


if __name__=='__main__':unittest.main()
