import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from development.controller_dispatch import reserve, write_status, plan_with_review, choose_review
from development import controller_dispatch as d
from types import SimpleNamespace
import threading

class DispatcherBudgetTests(unittest.TestCase):
    def test_reservations_are_bounded(self):
        state = {}
        self.assertTrue(reserve(state, "2026-11-24", 120000, 60000))
        self.assertTrue(reserve(state, "2026-11-24", 120000, 60000))
        self.assertFalse(reserve(state, "2026-11-24", 120000, 1))
        self.assertEqual(state["reserved"], 120000)

    def test_default_unlimited_reservation_preserves_accounting(self):
        state = {"day": "2026-11-24", "reserved": 120000}
        self.assertTrue(reserve(state, "2026-11-24", None, 60000))
        self.assertEqual(state["reserved"], 180000)

    def test_daily_reset(self):
        state = {"day": "2026-11-24", "reserved": 120000}
        self.assertTrue(reserve(state, "2026-11-25", 120000, 60000))
        self.assertEqual(state, {"day": "2026-11-25", "reserved": 60000})

class DispatcherStatusTests(unittest.TestCase):
    def test_status_exposes_only_scheduler_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_status(root, "working", [{"issue": 273, "generation": 2,
                                             "task": "private task"}], ["268:1"], ["8:2"])
            status = json.loads((root/"status.json").read_text())
            self.assertEqual(status["reason"], "working")
            self.assertEqual(status["active"], ["273:2"])
            self.assertEqual(status["waiting"], ["268:1"])
            self.assertEqual(status["awaiting_review"], ["8:2"])
            self.assertNotIn("private task", str(status))
            self.assertTrue(status["updated_at"].endswith("+00:00"))

    def test_status_error_does_not_interrupt_dispatch(self):
        with patch("development.controller_dispatch.save", side_effect=OSError):
            write_status(Path("."), "queue_unavailable", [])


class ParallelReviewTests(unittest.TestCase):
    def row(self,issue,role,branch,path,status="ready"):
        return dict(issue=issue,generation=1,role=role,priority=1,status=status,base_branch=branch,base_sha="a"*40,paths=[path],task="approved scoped task",dependencies=[])
    def test_review_occupies_one_slot_and_protects_branch_and_scope(self):
        review=self.row(14,"desktop","dev","static/app.js")
        same=self.row(54,"mobile","dev","static/engine-ui.js")
        overlap=self.row(67,"mobile","v2","static/app.js")
        separate=self.row(273,"data","v2","trading_engine_v2.py")
        self.assertEqual([x.issue for x in plan_with_review([review,same,overlap,separate],review,2)],[273])
        self.assertEqual(plan_with_review([separate],review,1),[])
    def test_review_and_independent_worker_actually_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);q=root/"queue.json"
            review=self.row(14,"desktop","dev","static/app.js")
            work=self.row(273,"data","v2","trading_engine_v2.py")
            d.save(q,[review,work])
            args=SimpleNamespace(parallel=2,publish=True,remote=True,queue=q,daily_reservation=None,per_task=60000)
            started=threading.Event(); concurrent=threading.Event()
            def coordinate(*args,**kwargs):
                started.set()
                if not concurrent.wait(3):
                    raise AssertionError("independent task did not run during review")
                return True
            def run(*args,**kwargs):
                self.assertTrue(started.wait(3))
                concurrent.set()
                (root/"STOP").touch()
                return "draft_pr"
            with patch.object(d.controller_remote,"refresh"),patch.object(d.controller_receipts,"flush"),patch.object(d.controller_progress,"flush"),patch.object(d,"notify_result"),patch.object(d,"choose_review",return_value=review),patch.object(d.controller_coordinator,"run_once",side_effect=coordinate) as cr,patch.object(d,"run_task",side_effect=run) as worker:
                results={"14:1":"draft_pr"}
                d.run_queue(args,root,root/"pilot.py",root/"budget.json",root/"results.json",{},results)
                cr.assert_called_once();worker.assert_called_once()
                self.assertTrue(concurrent.is_set())
                self.assertEqual(results["273:1"],"draft_pr")
    def test_local_only_delivery_is_scheduled_once_without_discarding_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);q=root/"queue.json"
            work=dict(self.row(268,"motor","codex/escape-development","hotwatch_engine.py"),generation=4,local_review=True)
            d.save(q,[work])
            d.save(d.task_record(root,work),{"row":work,"recovered":False})
            folder=root/"issue-268-4";folder.mkdir()
            (root/"issue-268-4.patch").write_text("preserved")
            results={"268:4":"review_required"}
            self.assertTrue(d.can_resume_delivery(root,work,results))
            self.assertFalse(d.can_resume_delivery(root,dict(work,task="changed scope"),results))
            args=SimpleNamespace(parallel=2,publish=True,remote=True,queue=q,daily_reservation=None,per_task=60000)
            def worker(*args):
                reservation=d.load(d.task_record(root,work),{})
                self.assertTrue(reservation["delivery_retry"])
                self.assertTrue(reservation["recovered"])
                self.assertEqual((root/"issue-268-4.patch").read_text(),"preserved")
                (root/"STOP").touch()
                return "draft_pr"
            with patch.object(d.controller_remote,"refresh"),patch.object(d.controller_receipts,"flush"),patch.object(d.controller_progress,"flush"),patch.object(d,"notify_result"),patch.object(d,"run_task",side_effect=worker) as call:
                d.run_queue(args,root,root/"pilot.py",root/"budget.json",root/"results.json",{},results)
                call.assert_called_once()
            self.assertEqual(results["268:4"],"draft_pr")
            self.assertFalse(d.can_resume_delivery(root,work,{"268:4":"review_required"}))

    def test_two_developer_repairs_use_development_slots_not_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);q=root/"queue.json"
            rows=[dict(self.row(14,"data","codex/escape-development","hotwatch_service.py"),local_review=True,local_repair=True),dict(self.row(67,"desktop","codex/trading-engine-v2-integration","static/market-ui.js"),local_review=True,local_repair=True)]
            d.save(q,rows)
            results={"14:1":"draft_pr","67:1":"draft_pr"}
            (root/"receipts").mkdir()
            journal={}
            for row,number in zip(rows,(304,306)):
                d.save(root/("receipts/"+str(row["issue"])+"-1.json"),{"issue":row["issue"],"generation":1,"status":"draft_pr","pr":"https://github.com/hva73/invest/pull/"+str(number)})
                journal[str(number)]={"state":"hold","sha":"a"*40,"repair_reason":"Concrete defect","at":0}
            d.save(root/"coordinator-review.json",journal)
            barrier=threading.Barrier(2)
            seen=[]
            def repair(root,repo,row,number,sha,reason,allowance):
                seen.append(row["issue"])
                barrier.wait(3)
                (root/"STOP").touch()
                return "published"
            args=SimpleNamespace(parallel=2,publish=True,remote=True,queue=q,daily_reservation=None,per_task=60000)
            snapshots=[]
            original_status=d.write_status
            def status(*args,**kwargs):
                original_status(*args,**kwargs)
                snapshots.append(d.load(root/"status.json",{}))
            with patch.object(d.controller_remote,"refresh"),patch.object(d.controller_receipts,"flush"),patch.object(d.controller_progress,"flush"),patch.object(d,"remote_draft_head",return_value="a"*40),patch.object(d.controller_coordinator,"run_developer_repair",side_effect=repair),patch.object(d.controller_coordinator,"run_once") as coordinator,patch.object(d,"write_status",side_effect=status):
                d.run_queue(args,root,root/"pilot.py",root/"budget.json",root/"results.json",{},results)
                coordinator.assert_not_called()
                self.assertTrue(any(len(x["active"])==2 and not x["coordinator_running"] for x in snapshots))
            self.assertEqual(set(seen),{14,67})
            self.assertEqual(results,{"14:1":"draft_pr","67:1":"draft_pr"})

    def test_known_defect_is_never_scheduled_as_review_on_unchanged_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            row=dict(self.row(114,"motor","codex/trading-engine-v2-integration","trade_service.py"),local_review=True,local_repair=True)
            results={"114:1":"draft_pr"}
            (root/"receipts").mkdir()
            d.save(root/"receipts/114-1.json",{"issue":114,"generation":1,"status":"draft_pr","pr":"https://github.com/hva73/invest/pull/303"})
            head="b"*40
            d.save(root/"coordinator-review.json",{"303":{"state":"hold","sha":head,"repair_reason":"Concrete defect","at":0}})
            actions=list(d.draft_actions(root,[row],results,[],probe=lambda _:head))
            self.assertEqual([x[2] for x in actions],["repair"])
            self.assertIsNone(d.choose_review(root,[row],results,[],actions=actions))
            self.assertEqual(list(d.repair_candidates(root,[row],results,[],actions=actions)),[(row,303,head,"Concrete defect")])
            d.save(root/"coordinator-repair-303.json",{"key":"114:1","head":head,"state":"held"})
            actions=list(d.draft_actions(root,[row],results,[],probe=lambda _:head))
            self.assertEqual([x[2] for x in actions],["blocked_repair"])
            self.assertIsNone(d.choose_review(root,[row],results,[],actions=actions))
            self.assertEqual(list(d.repair_candidates(root,[row],results,[],actions=actions)),[])
            actions=list(d.draft_actions(root,[row],results,[],probe=lambda _:"c"*40))
            self.assertEqual([x[2] for x in actions],["review"])
            self.assertEqual(d.choose_review(root,[row],results,[],actions=actions),row)
            def unavailable(_):
                raise OSError("offline")
            actions=list(d.draft_actions(root,[row],results,[],probe=unavailable))
            self.assertEqual([x[2] for x in actions],["metadata_unavailable"])
            self.assertIsNone(d.choose_review(root,[row],results,[],actions=actions))

    def test_capacity_includes_coordinator_without_false_agent_activity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            write_status(root,"working",[self.row(273,"data","v2","engine.py")],coordinator_running=True,coordinator_task="14:1",capacity=2)
            s=json.loads((root/"status.json").read_text())
            self.assertEqual(s["slots_used"],2)
            self.assertEqual(s["active"],["273:1"])
            self.assertEqual(s["coordinator_task"],"14:1")

if __name__ == "__main__":
    unittest.main()
