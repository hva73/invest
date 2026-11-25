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
