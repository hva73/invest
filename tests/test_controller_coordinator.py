import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from development import controller_coordinator as c
from development.controller_dispatch import coordinate, write_status

class LocalCoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.row=dict(issue=273,generation=12,role="data",priority=1,status="ready",base_branch="codex/trading-engine-v2-integration",base_sha="a"*40,paths=["trading_engine_v2.py","tests/test_trading_engine_v2.py"],task="Approved test-only feature task",local_review=True,followups=[{"task":"Approved next test", "paths":["tests/test_trading_engine_v2.py"]}])
        self.results={"273:12":"draft_pr"}
        (self.root/"receipts").mkdir()
        c.save(self.root/"receipts"/"273-12.json",{"issue":273,"generation":12,"status":"draft_pr","pr":"https://github.com/hva73/invest/pull/501"})
    def test_queue_repin_writes_valid_json_and_preserves_other_rows(self):
        import base64
        old=self.row
        new=dict(old,base_sha="b"*40)
        other=dict(old,issue=14,role="motor")
        rows=[old,other]
        def document():
            return {"content":base64.b64encode(json.dumps(rows).encode()).decode(),"sha":"c"*40}
        def api(endpoint,method="GET",data=None):
            if method=="PUT":
                payload=base64.b64decode(data["content"])
                self.assertTrue(payload.endswith(b"\n"))
                rows[:]=json.loads(payload)
                return {}
            return document()
        with patch.object(c,"gh",side_effect=api):
            self.assertEqual(c.replace_queue_row(old,new),new)
        self.assertEqual(rows,[new,other])

    def test_review_comment_failure_does_not_repeat_rejected_review(self):
        import subprocess
        row=dict(self.row,local_repair=True)
        p={"head":{"sha":"d"*40}}
        decision={"verdict":"hold","reason":"Concrete reproducible regression"}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value=decision) as review,patch.object(c,"comment",side_effect=subprocess.CalledProcessError(1,["gh"])),patch.object(c,"repair_review",return_value="Repaired") as repair:
            c.run_once(self.root,self.root,[row],self.results)
            journal=c.read(self.root/"coordinator-review.json",{})
            self.assertEqual(journal["501"]["state"],"hold")
            self.assertEqual(journal["501"]["repair_reason"],decision["reason"])
            journal["501"]["at"]=0
            c.save(self.root/"coordinator-review.json",journal)
            c.run_once(self.root,self.root,[row],self.results)
            review.assert_called_once()
            repair.assert_called_once()

    def test_adaptive_repair_preserves_scope_and_reuses_only_matching_findings(self):
        row=dict(self.row,role="data")
        first=c.adaptive_repair_task(self.root,row,501,"d"*40,"current defect",1)
        self.assertIn("ROOT_CAUSE",first)
        c.save(self.root/"coordinator-repair-501.json",{"key":c.key(row),"reason":"old lock regression"})
        second=c.adaptive_repair_task(self.root,row,501,"e"*40,"current defect",2)
        self.assertIn("FUNCTION_REASSESSMENT",second)
        self.assertIn("old lock regression",second)
        c.save(self.root/"coordinator-repair-501-2.json",{"key":"999:1","reason":"unrelated task"})
        third=c.adaptive_repair_task(self.root,row,501,"f"*40,"current defect",3)
        self.assertIn("FRESH_APPROACH",third)
        self.assertIn("old lock regression",third)
        self.assertNotIn("unrelated task",third)
        self.assertIn(row["task"],third)
        self.assertIn("current defect",third)
        self.assertIn("SQLite",third)
        self.assertIn("untrusted evidence",third)

    def test_same_head_recovery_reuses_exact_preserved_worktree(self):
        import subprocess
        root=self.root
        repo=root/"repo"
        repo.mkdir()
        def git(path,*args):
            return subprocess.check_output(["git","-C",str(path),*args],stderr=subprocess.DEVNULL).decode().strip()
        git(repo,"init")
        git(repo,"config","user.name","Test")
        git(repo,"config","user.email","test@example.invalid")
        (repo/"trading_engine_v2.py").write_text("original")
        git(repo,"add",".")
        git(repo,"commit","-m","base")
        sha=git(repo,"rev-parse","HEAD")
        row=dict(self.row,local_repair=True)
        folder=root/"review-repair-273-12-501"
        git(repo,"worktree","add","-b","controller/local-273-123",str(folder),sha)
        (folder/"trading_engine_v2.py").write_text("preserved repair")
        record=root/"coordinator-repair-501.json"
        old={"key":c.key(row),"head":sha,"state":"held"}
        c.save(record,old)
        self.assertIsNone(c.repair_attempt(root,501,sha))
        with patch.object(c,"verify_pr",return_value=({"head":{"sha":sha}},[],"open")):
            self.assertEqual(c.authorize_repair_resume(root,repo,row,501,sha),1)
        self.assertEqual(c.repair_attempt(root,501,sha),1)
        self.assertEqual(c.resume_repair_workspace(root,repo,row,501,1,sha,folder,record),"controller/local-273-123")
        self.assertEqual((folder/"trading_engine_v2.py").read_text(),"preserved repair")
        git(folder,"add",".")
        git(folder,"commit","-m","local tested fix")
        local=git(folder,"rev-parse","HEAD")
        c.resume_repair_workspace(root,repo,row,501,1,sha,folder,record)
        self.assertEqual(git(folder,"rev-parse","HEAD"),sha)
        self.assertEqual(git(folder,"rev-parse","refs/heads/controller/recovery-backup-501-"+local),local)
        self.assertEqual((folder/"trading_engine_v2.py").read_text(),"preserved repair")
        (folder/"outside.py").write_text("not approved")
        with self.assertRaises(c.Hold):
            c.resume_repair_workspace(root,repo,row,501,1,sha,folder,record)
        c.save(record.with_suffix(".resume-history.json"),old)
        self.assertEqual(c.repair_attempt(root,501,sha),1)
        c.save(record.with_suffix(".resume-history-2.json"),old)
        c.save(record.with_suffix(".resume-history-3.json"),old)
        c.save(record.with_suffix(".resume-history-4.json"),old)
        self.assertIsNone(c.repair_attempt(root,501,sha))

    def test_automatic_recovery_requires_finished_child_and_is_bounded(self):
        row=dict(self.row,local_repair=True)
        head="d"*40
        record=self.root/"coordinator-repair-501.json"
        held={"key":c.key(row),"head":head,"state":"held"}
        c.save(record,held)
        self.assertFalse(c.finished_repair_can_resume(self.root,row,501,head))
        c.save(record,dict(held,child_finished=True,resume_eligible=True))
        self.assertTrue(c.finished_repair_can_resume(self.root,row,501,head))
        c.save(record,dict(held,state="reserved",child_finished=True,resume_eligible=True))
        self.assertFalse(c.finished_repair_can_resume(self.root,row,501,head))
        c.save(record,dict(held,child_finished=True,resume_eligible=True))
        c.save(record.with_suffix(".resume-history.json"),held)
        self.assertTrue(c.finished_repair_can_resume(self.root,row,501,head))
        c.save(record.with_suffix(".resume-history-2.json"),held)
        c.save(record.with_suffix(".resume-history-3.json"),held)
        c.save(record.with_suffix(".resume-history-4.json"),held)
        self.assertFalse(c.finished_repair_can_resume(self.root,row,501,head))

    def test_coordinator_defers_repair_to_developer_scheduler(self):
        row=dict(self.row,local_repair=True)
        p={"head":{"sha":"d"*40}}
        decision={"verdict":"hold","reason":"Concrete reproducible regression"}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value=decision) as review,patch.object(c,"comment"),patch.object(c,"repair_review") as repair:
            c.run_once(self.root,self.root,[row],self.results,defer_repairs=True)
            journal=c.read(self.root/"coordinator-review.json",{})
            self.assertEqual(journal["501"]["state"],"hold")
            self.assertEqual(journal["501"]["repair_reason"],decision["reason"])
            repair.assert_not_called()
            review.assert_called_once()
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"repair_review",return_value="published") as worker:
            self.assertEqual(c.run_developer_repair(self.root,self.root,row,501,"d"*40,decision["reason"],60000),"published")
            worker.assert_called_once()
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"repair_review") as worker:
            self.assertEqual(c.run_developer_repair(self.root,self.root,row,501,"e"*40,decision["reason"],60000),"changed_head")
            worker.assert_not_called()

    def test_trigger_is_explicit_and_bounded(self):
        self.assertIsNone(c.trigger(self.root))
        value={"schema":1,"id":"f"*32,"requests":["b"*32],"at":c.now()}
        c.save(self.root/"coordinator-trigger.json",value)
        self.assertEqual(c.trigger(self.root),value)
        value["requests"]=["unsafe"]
        c.save(self.root/"coordinator-trigger.json",value)
        self.assertIsNone(c.trigger(self.root))
    def test_local_review_is_opt_in_and_receipt_matches_generation(self):
        self.assertEqual(list(c.candidates(self.root,[self.row],self.results)),[(self.row,501)])
        self.assertFalse(list(c.candidates(self.root,[dict(self.row,local_review=False)],self.results)))
        self.assertFalse(list(c.candidates(self.root,[dict(self.row,base_branch="main")],self.results)))
        self.assertFalse(list(c.candidates(self.root,[dict(self.row,role="release")],self.results)))
        self.assertFalse(list(c.candidates(self.root,[self.row],{"273:12":"reserved"})))
    def test_successor_only_from_approved_scope_and_accepted_base(self):
        new=c.successor([self.row],self.row,"c"*40)
        self.assertEqual((new["generation"],new["base_sha"],new["dependencies"]),(13,"c"*40,["273:12"]))
        self.assertEqual(new["task"],"Approved next test")
        self.assertTrue(new["local_review"])
        self.assertEqual(new["followups"],[])
        with self.assertRaises(c.Hold):
            c.successor([self.row],dict(self.row,followups=[{"task":"Bad","paths":[".github/workflows/x.yml"]}]),"c"*40)
    def test_ci_requires_actual_relevant_steps(self):
        sha="d"*40
        run={"id":7,"name":"ESCAPE controller regression review","path":".github/workflows/escape-controller-regression.yml","head_sha":sha,"status":"completed","conclusion":"success"}
        job={"name":"regression","conclusion":"success","steps":[{"name":"Baseline smoke and scope confirmation","conclusion":"success"},{"name":"Motor and data-path regression","conclusion":"skipped"}]}
        with patch.object(c,"gh",side_effect=[{"workflow_runs":[run]},{"jobs":[job]}]):
            with self.assertRaises(c.Hold):
                c.verified_ci(sha,[{"filename":"trading_engine_v2.py"}])
        job["steps"][1]["conclusion"]="success"
        with patch.object(c,"gh",side_effect=[{"workflow_runs":[run]},{"jobs":[job]}]):
            self.assertEqual(c.verified_ci(sha,[{"filename":"trading_engine_v2.py"}]),7)
    def test_long_term_specialized_ci_requires_actual_pinned_suite(self):
        import base64
        sha="d"*40
        run={"id":7,"name":"ESCAPE controller regression review","path":".github/workflows/escape-controller-regression.yml","head_sha":sha,"status":"completed","conclusion":"success"}
        job={"name":"regression","conclusion":"success","steps":[{"name":"Baseline smoke and scope confirmation","conclusion":"success"},{"name":"Motor and data-path regression","conclusion":"success"}]}
        files=[{"filename":"long_term_watch.py"},{"filename":"tests/test_strategy_lab.py"}]
        workflow={"content":base64.b64encode(b"if test -f tests/test_trading_engine_v2.py; then python -m unittest tests.test_trading_engine_v2 tests.test_strategy_lab; fi").decode()}
        with patch.object(c,"gh",side_effect=[{"workflow_runs":[run]},{"jobs":[job]},workflow,{"type":"file"}]):
            self.assertEqual(c.verified_ci(sha,files),7)
        with patch.object(c,"gh",side_effect=[{"workflow_runs":[run]},{"jobs":[job]},workflow,{"type":"dir"}]):
            with self.assertRaises(c.Hold):
                c.verified_ci(sha,files)
        missing={"content":base64.b64encode(b"python -m unittest tests.test_hotwatch_engine").decode()}
        with patch.object(c,"gh",side_effect=[{"workflow_runs":[run]},{"jobs":[job]},missing]):
            with self.assertRaises(c.Hold):
                c.verified_ci(sha,files)

    def test_four_continuations_apply_to_all_tasks(self):
        head="b32e473553d233b616e8f57f88350327c8ab41a8"
        record=self.root/"coordinator-repair-303.json"
        held={"key":"114:1","head":head,"state":"held","child_finished":True,"resume_eligible":True}
        for suffix in (".resume-history.json",".resume-history-2.json"):
            c.save(record.with_suffix(suffix),held)
        c.save(record,held)
        self.assertEqual(c.repair_resume_archive(record),record.with_suffix(".resume-history-3.json"))
        c.save(record,dict(held,resume_authorized=True))
        self.assertEqual(c.repair_attempt(self.root,303,head),1)
        c.save(record.with_suffix(".resume-history-3.json"),held)
        self.assertEqual(c.repair_attempt(self.root,303,head),1)
        c.save(record.with_suffix(".resume-history-4.json"),held)
        self.assertIsNone(c.repair_attempt(self.root,303,head))
        c.save(record,dict(held,state="reserved"))
        self.assertIsNone(c.repair_attempt(self.root,303,head))

    def test_preflight_hold_without_code_rejection_can_proceed(self):
        sha="d"*40
        c.save(self.root/"coordinator-review.json",{"501":{"state":"hold","sha":sha,"detail":"Specialized CI","at":0}})
        p={"head":{"sha":sha}}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value={"verdict":"accept","reason":"Tested component"}) as review,patch.object(c,"integrate",return_value="Integrated"):
            self.assertTrue(c.run_once(self.root,self.root,[self.row],self.results))
            review.assert_called_once()

    def test_local_activation_holds_or_integrates_not_duplicate(self):
        p={"head":{"sha":"d"*40}}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value={"verdict":"accept","reason":"Scoped test-only component"}),patch.object(c,"integrate",return_value="Accepteret; næste opgave frigivet") as merge:
            self.assertTrue(c.due(self.root,[self.row],self.results))
            self.assertTrue(c.run_once(self.root,self.root,[self.row],self.results))
            merge.assert_called_once()
            self.assertFalse(c.due(self.root,[self.row],self.results))
            self.assertEqual(c.read(self.root/"coordinator-status.json",{})["state"],"completed")
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review") as review,patch.object(c,"integrate") as merge:
            self.assertFalse(c.run_once(self.root,self.root,[self.row],self.results))
            review.assert_not_called();merge.assert_not_called()
    def test_provider_pause_and_budget_never_run_model(self):
        with patch.object(c,"independent_review") as model:
            self.assertFalse(c.run_once(self.root,self.root,[self.row],self.results,provider_pause=True))
            model.assert_not_called()
        p={"head":{"sha":"d"*40}}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review") as model:
            self.assertFalse(c.run_once(self.root,self.root,[self.row],self.results,reserve_review=lambda:False))
            model.assert_not_called()
    def test_owner_review_output_is_strict(self):
        self.assertEqual(c.parse_review('{"verdict":"hold","reason":"Regression found"}')["verdict"],"hold")
        for text in ('{"verdict":"accept","reason":"ok","command":"rm"}','{"verdict":"merge","reason":"ok"}','{"verdict":"hold","reason":"github_pat_secret"}'):
            with self.assertRaises(c.Hold):
                c.parse_review(text)
    def test_dispatcher_advertises_actual_capability_and_running(self):
        write_status(self.root,"coordinating",[],[],[],True,True)
        status=c.read(self.root/"status.json",{})
        self.assertEqual(status["coordinator_protocol"],1)
        self.assertTrue(status["coordinator_running"])
        with patch.object(c,"run_once",return_value=True) as run:
            self.assertTrue(coordinate(self.root,self.root,[self.row],self.results,[],["273:12"]))
            run.assert_called_once()

    def test_manual_receipt_distinguishes_waiting_and_survives_automatic_run(self):
        rid="b"*32
        value={"schema":1,"id":rid,"requests":[rid],"at":c.now()}
        c.save(self.root/"coordinator-trigger.json",value)
        with patch.object(c,"owner_requests",return_value={rid:{"task":"all"}}),patch.object(c,"comment") as ack:
            self.assertFalse(c.run_once(self.root,self.root,[],{}))
            ack.assert_called_once()
        receipt=c.read(self.root/"coordinator-manual-status.json",{})
        self.assertEqual((receipt["id"],receipt["state"],receipt["requests"]),(rid,"waiting",[rid]))
        self.assertFalse((self.root/"coordinator-trigger.json").exists())
        self.assertFalse(c.run_once(self.root,self.root,[],{}))
        self.assertEqual(c.read(self.root/"coordinator-manual-status.json",{}),receipt)

    def test_manual_failure_is_not_completion(self):
        rid="a"*32
        c.save(self.root/"coordinator-trigger.json",{"schema":1,"id":rid,"requests":[rid],"at":c.now()})
        with patch.object(c,"owner_requests",side_effect=OSError("offline")):
            self.assertFalse(c.run_once(self.root,self.root,[],{}))
        self.assertEqual(c.read(self.root/"coordinator-manual-status.json",{})["state"],"blocked")

    def test_held_review_is_rechecked_after_cooldown_without_repeat_model(self):
        old="d"*40
        c.save(self.root/"coordinator-review.json",{"501":{"at":1,"state":"hold","sha":old,"detail":"Concrete review failure"}})
        self.assertTrue(c.due(self.root,[self.row],self.results,current_time=62))
        with patch.object(c,"verify_pr",return_value=({"head":{"sha":old}},[],"open")),patch.object(c,"independent_review") as model:
            self.assertFalse(c.run_once(self.root,self.root,[self.row],self.results))
            model.assert_not_called()
        self.assertFalse(c.due(self.root,[self.row],self.results))
        journal=c.read(self.root/"coordinator-review.json",{})
        journal["501"]["at"]=1
        c.save(self.root/"coordinator-review.json",journal)
        with patch.object(c,"verify_pr",return_value=({"head":{"sha":"e"*40}},[],"open")),patch.object(c,"verified_ci",return_value=8),patch.object(c,"independent_review",return_value={"verdict":"accept","reason":"Fix confirmed"}) as model,patch.object(c,"integrate",return_value="Accepted"):
            self.assertTrue(c.run_once(self.root,self.root,[self.row],self.results))
            model.assert_called_once()
        self.assertFalse(c.due(self.root,[self.row],self.results))

    def test_one_lookup_failure_does_not_starve_independent_review(self):
        other=dict(self.row,issue=14,generation=6,priority=2)
        c.save(self.root/"receipts"/"14-6.json",{"issue":14,"generation":6,"status":"draft_pr","pr":"https://github.com/hva73/invest/pull/502"})
        results=dict(self.results,**{"14:6":"draft_pr"})
        with patch.object(c,"verify_pr",side_effect=[OSError("temporary"),({"head":{"sha":"e"*40}},[],"open")]),patch.object(c,"verified_ci",return_value=8),patch.object(c,"independent_review",return_value={"verdict":"accept","reason":"Independent task passed"}),patch.object(c,"integrate",return_value="Accepted") as merge:
            self.assertTrue(c.run_once(self.root,self.root,[self.row,other],results))
            self.assertEqual(merge.call_args.args[0],other)

    def test_explicit_scoped_repair_reenters_ci_without_merging(self):
        row=dict(self.row,local_repair=True)
        p={"head":{"sha":"d"*40}}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value={"verdict":"hold","reason":"Actual defect"}),patch.object(c,"comment"),patch.object(c,"repair_review",return_value="Repaired; CI pending") as repair,patch.object(c,"integrate") as merge:
            self.assertFalse(c.run_once(self.root,self.root,[row],self.results,repair_allowance=1234))
            repair.assert_called_once_with(self.root,self.root,row,501,p,"Actual defect",1234)
            merge.assert_not_called()
        self.assertEqual(c.read(self.root/"coordinator-review.json",{})["501"]["state"],"waiting")

    def test_hold_without_opt_in_or_budget_does_not_repair(self):
        p={"head":{"sha":"d"*40}}
        for row,budget in ((self.row,lambda:True),(dict(self.row,local_repair=True),iter([True,False]).__next__)):
            with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value={"verdict":"hold","reason":"Actual defect"}),patch.object(c,"comment"),patch.object(c,"repair_review") as repair,patch.object(c,"integrate") as merge:
                (self.root/"coordinator-review.json").unlink(missing_ok=True)
                self.assertFalse(c.run_once(self.root,self.root,[row],self.results,reserve_review=budget))
                repair.assert_not_called()
                merge.assert_not_called()

    def test_repair_existing_reservation_does_not_repeat(self):
        c.save(self.root/"coordinator-repair-501.json",{"state":"reserved"})
        p={"head":{"sha":"d"*40,"ref":"controller/local-273-1234"}}
        with patch.object(c.subprocess,"run") as run:
            self.assertIn("ingen dublet",c.repair_review(self.root,self.root,self.row,501,p,"Defect",1234))
            run.assert_not_called()

    def test_deferred_repair_resumes_same_reviewed_sha_without_new_review(self):
        row=dict(self.row,local_repair=True)
        p={"head":{"sha":"d"*40}}
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=7),patch.object(c,"independent_review",return_value={"verdict":"hold","reason":"Actual defect"}) as model,patch.object(c,"comment"),patch.object(c,"repair_review",return_value="Repaired; CI pending") as repair:
            self.assertFalse(c.run_once(self.root,self.root,[row],self.results,reserve_review=iter([True,False]).__next__))
            model.assert_called_once()
            repair.assert_not_called()
            journal=c.read(self.root/"coordinator-review.json",{})
            journal["501"]["at"]=1
            c.save(self.root/"coordinator-review.json",journal)
            self.assertFalse(c.run_once(self.root,self.root,[row],self.results))
            model.assert_called_once()
            repair.assert_called_once()
        self.assertEqual(c.read(self.root/"coordinator-review.json",{})["501"]["state"],"waiting")

    def test_unstarted_pin_preserves_history_and_rejects_divergence(self):
        row=dict(self.row,follow_base=True);new="c"*40
        # The default fixture represents a delivered PR and must never be re-pinned.
        self.assertEqual(c.pin_unstarted(self.root,row,{}),row)
        (self.root/"receipts/273-12.json").unlink()
        compare={"behind_by":0,"merge_base_commit":{"sha":row["base_sha"]}}
        with patch.object(c,"branch_head",return_value=new),patch.object(c,"gh",return_value=compare),patch.object(c,"replace_queue_row",side_effect=lambda old,new:new) as replace:
            self.assertEqual(c.pin_unstarted(self.root,row,{})["base_sha"],new)
            replace.assert_called_once()
            self.assertEqual(c.pin_unstarted(self.root,row,{c.key(row):"reserved"}),row)
            replace.assert_called_once()
        with patch.object(c,"branch_head",return_value=new),patch.object(c,"gh",return_value={"behind_by":1,"merge_base_commit":{"sha":row["base_sha"]}}):
            with self.assertRaises(c.Hold):
                c.pin_unstarted(self.root,row,{})

    def test_rebase_refuses_overlap_and_incomplete_compare(self):
        old="a"*40
        data={"behind_by":0,"merge_base_commit":{"sha":old},"files":[{"filename":"unrelated.py"}]}
        self.assertTrue(c.disjoint_base_changes(data,old,["static/","tests/test.py"]))
        self.assertFalse(c.disjoint_base_changes(dict(data,files=[{"filename":"other.py","previous_filename":"static/app.js"}]),old,["static/"]))
        self.assertFalse(c.disjoint_base_changes(dict(data,files=[{"filename":"x"}]*300),old,["static/"]))
        self.assertFalse(c.disjoint_base_changes(dict(data,behind_by=1),old,["static/"]))

    def test_multiple_repairs_only_after_published_new_sha(self):
        old="d"*40;new="e"*40
        self.assertEqual(c.repair_attempt(self.root,501,old),1)
        c.save(self.root/"coordinator-repair-501.json",{"state":"reserved","head":old})
        self.assertIsNone(c.repair_attempt(self.root,501,new))
        c.save(self.root/"coordinator-repair-501.json",{"state":"published","head":old,"new_head":new})
        self.assertIsNone(c.repair_attempt(self.root,501,old))
        self.assertEqual(c.repair_attempt(self.root,501,new),2)
        c.save(self.root/"coordinator-repair-501-2.json",{"state":"held","head":new})
        self.assertIsNone(c.repair_attempt(self.root,501,new))
        self.assertEqual(c.repair_attempt(self.root,501,"f"*40),3)

    def test_actual_stalled_queue_historical_holds_do_not_block_new_heads(self):
        for number in (299,300,303,304,306):
            path=self.root/("coordinator-repair-"+str(number)+".json")
            old={"state":"held","head":"a"*40,"key":"273:12"}
            c.save(path,old)
            self.assertEqual(c.repair_attempt(self.root,number,"b"*40),2)
            self.assertIsNone(c.repair_attempt(self.root,number,"a"*40))
            self.assertEqual(c.read(path,{}),old)
            c.save(path,dict(old,state="reserved"))
            self.assertIsNone(c.repair_attempt(self.root,number,"b"*40))

    def test_fourth_repair_is_allowed_after_three_distinct_publications(self):
        heads=[str(i)*40 for i in range(1,5)]
        for i in range(3):
            suffix="" if i==0 else "-"+str(i+1)
            c.save(self.root/("coordinator-repair-501"+suffix+".json"),{"state":"published","head":heads[i],"new_head":heads[i+1]})
        self.assertEqual(c.repair_attempt(self.root,501,heads[3]),4)
        self.assertIsNone(c.repair_attempt(self.root,501,heads[1]))
        c.save(self.root/"coordinator-repair-501-4.json",{"state":"published","head":heads[3],"new_head":heads[0]})
        self.assertIsNone(c.repair_attempt(self.root,501,"5"*40))

    def test_verify_pr_uses_exact_branch_and_diff_when_pr_base_metadata_lags(self):
        row=self.row;sha="d"*40
        f={"filename":"trading_engine_v2.py","status":"modified","sha":"e"*40}
        p={"head":{"sha":sha,"ref":"controller/local-273-123","repo":{"full_name":c.REPO}},
           "base":{"sha":"b"*40,"ref":row["base_branch"],"repo":{"full_name":c.REPO}},
           "state":"open","changed_files":1}
        comparison={"merge_base_commit":{"sha":row["base_sha"]},"behind_by":0,"files":[f]}
        with patch.object(c,"branch_head",return_value=row["base_sha"]),patch.object(c,"gh",side_effect=[p,[f],comparison]):
            self.assertEqual(c.verify_pr(row,501),(p,[f],"open"))
        with patch.object(c,"branch_head",return_value=row["base_sha"]),patch.object(c,"gh",side_effect=[p,[f],dict(comparison,files=[dict(f,sha="f"*40)])]):
            with self.assertRaises(c.Hold):
                c.verify_pr(row,501)

    def test_disjoint_rebase_does_not_require_fresh_pr_base_metadata(self):
        row=dict(self.row,follow_base=True);old=row["base_sha"];latest="b"*40;sha="d"*40;new="e"*40
        f={"filename":"trading_engine_v2.py","status":"modified","sha":"f"*40}
        p={"head":{"sha":sha,"ref":"controller/local-273-123","repo":{"full_name":c.REPO}},
           "base":{"sha":old,"ref":row["base_branch"],"repo":{"full_name":c.REPO}},
           "state":"open","changed_files":1}
        fresh=dict(p,head=dict(p["head"],sha=new))
        compare=lambda base,files:{"merge_base_commit":{"sha":base},"behind_by":0,"files":files}
        calls=[p,compare(old,[{"filename":"unrelated.py"}]),[f],compare(old,[f]),
               {"tree":[{"path":f["filename"],"type":"blob","mode":"100644","sha":f["sha"]}]},
               {"sha":"1"*40},{"sha":new},compare(latest,[f]),p,{"object":{"sha":new}},fresh]
        with patch.object(c,"branch_head",return_value=latest),patch.object(c,"tree",return_value="2"*40),patch.object(c,"gh",side_effect=calls) as api,patch.object(c,"replace_queue_row",side_effect=lambda old,new:new):
            self.assertEqual(c.rebase_disjoint(self.root,row,501)["base_sha"],latest)
            self.assertFalse(next(call.args[2]["force"] for call in api.call_args_list if len(call.args)>1 and call.args[1]=="PATCH"))

    def test_exact_accepted_review_is_reused_without_another_model(self):
        sha="d"*40;run=7;p={"head":{"sha":sha}}
        decision={"verdict":"accept","reason":"Verified scoped change"}
        c.save(self.root/"coordinator-accepted-501.json",dict(c.review_identity(self.row,sha,run),decision=decision))
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=run),patch.object(c,"independent_review") as model,patch.object(c,"integrate",return_value="Accepted") as merge:
            self.assertTrue(c.run_once(self.root,self.root,[self.row],self.results,reserve_review=lambda:False))
            model.assert_not_called();merge.assert_called_once()

    def test_integration_hold_does_not_discard_exact_accepted_review(self):
        sha="d"*40;run=7;p={"head":{"sha":sha}}
        c.save(self.root/"coordinator-review.json",{"501":{"at":1,"state":"hold","sha":sha,"detail":"Integration temporarily held"}})
        c.save(self.root/"coordinator-accepted-501.json",dict(c.review_identity(self.row,sha,run),decision={"verdict":"accept","reason":"Verified scoped change"}))
        with patch.object(c,"verify_pr",return_value=(p,[],"open")),patch.object(c,"verified_ci",return_value=run),patch.object(c,"independent_review") as model,patch.object(c,"integrate",return_value="Accepted") as merge:
            self.assertTrue(c.run_once(self.root,self.root,[self.row],self.results,reserve_review=lambda:False))
            model.assert_not_called();merge.assert_called_once()

    def test_preflight_failure_preserves_prior_review_findings(self):
        row=dict(self.row,follow_base=True)
        sha="d"*40
        c.save(self.root/"coordinator-review.json",{"501":{"at":1,"state":"hold","sha":sha,"repair_reason":"Material regression"}})
        with patch.object(c,"rebase_disjoint",side_effect=c.Hold("Temporary basis mismatch")),patch.object(c,"independent_review") as model:
            self.assertFalse(c.run_once(self.root,self.root,[row],self.results))
            model.assert_not_called()
        entry=c.read(self.root/"coordinator-review.json",{})["501"]
        self.assertEqual((entry["sha"],entry["repair_reason"],entry["state"]),(sha,"Material regression","hold"))
