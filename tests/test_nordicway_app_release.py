import os,sqlite3,tempfile,unittest
from pathlib import Path
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

    def test_verified_resume_reconciles_only_matching_recovery(self):
        item=release_approval.prepare(self.connect,'a'*40,'Test',7,now=100,lifetime=60)
        release_approval.approve(self.connect,item['id'],item['sha'],7,now=101)
        release_approval.claim(self.connect,item['id'],item['sha'],now=102)
        release_approval.finish(self.connect,item['id'],item['sha'],verified=False)
        failed={'operation':'resume','status':'failed','recovery_required':True,'backup_cleanup':'not_run'}
        self.assertEqual(bridge.resume_app(self.connect,item['sha'],resume=lambda _:failed)['status'],'failed')
        self.assertEqual(release_approval.current(self.connect,7,now=103)['status'],'recovery')
        ok={'operation':'resume','status':'ok','recovery_required':False,'backup_cleanup':'ok'}
        wrong_calls=[]
        self.assertEqual(bridge.resume_app(self.connect,'b'*40,resume=lambda sha:wrong_calls.append(sha) or ok)['status'],'failed')
        self.assertEqual(wrong_calls,[])
        self.assertEqual(release_approval.current(self.connect,7,now=103)['status'],'recovery')
        self.assertEqual(bridge.resume_app(self.connect,item['sha'],resume=lambda _:ok)['status'],'ok')
        self.assertEqual(release_approval.current(self.connect,7,now=103)['status'],'completed')

    def test_unknown_owner_rejected_before_staging(self):
        with self.connect() as c:c.execute('UPDATE users SET active=0')
        with self.assertRaisesRegex(ValueError,'owner_unavailable'):
            bridge.run(self.connect,'a'*40,'Test','t'*40,self.bridge,runner=None,create_proof=None,notify=None)


if __name__=='__main__':unittest.main()
