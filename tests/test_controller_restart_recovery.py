import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from development import controller_dispatch as d


def row():
    return dict(issue=273,generation=5,role="motor",priority=1,status="ready",
                paths=["trading_engine_v2.py"],dependencies=[],
                base_branch="codex/trading-engine-v2-integration",
                base_sha="a"*40,task="original approved scope")


class RestartRecoveryTests(unittest.TestCase):
    def test_recovery_requires_new_boot_same_task_and_no_terminal_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            task=row()
            record=dict(row=task,boot="old",recovered=False)
            d.save(d.task_record(root,task),record)
            self.assertTrue(d.can_recover(root,task,"new"))
            self.assertFalse(d.can_recover(root,task,"old"))
            self.assertFalse(d.can_recover(root,task,None))
            self.assertFalse(d.can_recover(root,dict(task,task="changed"),"new"))
            (root/"issue-273-5.pr").touch()
            self.assertFalse(d.can_recover(root,task,"new"))
            (root/"issue-273-5.pr").unlink()
            (root/"receipts").mkdir()
            (root/"receipts/273-5.json").touch()
            self.assertFalse(d.can_recover(root,task,"new"))
            (root/"receipts/273-5.json").unlink()
            d.save(root/"checkpoint-273-5.json",{"provider_limit":True})
            self.assertFalse(d.can_recover(root,task,"new"))
            (root/"checkpoint-273-5.json").unlink()
            d.save(d.task_record(root,task),dict(record,recovered=True))
            self.assertFalse(d.can_recover(root,task,"new"))

    def test_scheduler_recovers_once_and_preserves_original_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            task=row()
            d.save(d.task_record(root,task),dict(row=task,boot="old",recovered=False))
            q=root/"queue.json"
            d.save(q,[task])
            results={"273:5":"reserved"}
            def work(root,script,item,allowance,publish):
                self.assertEqual(item,task)
                self.assertTrue(d.load(d.task_record(root,item),{})["recovered"])
                (root/"STOP").touch()
                return "draft_pr"
            a=SimpleNamespace(parallel=2,publish=False,remote=False,queue=q,
                              daily_reservation=None,per_task=60000)
            with patch.object(d,"boot_id",return_value="new"),patch.object(d,"run_task",side_effect=work) as runner:
                d.run_queue(a,root,root/"pilot.py",root/"budget.json",root/"results.json",{},results)
            self.assertEqual(runner.call_count,1)
            self.assertEqual(results["273:5"],"draft_pr")
            self.assertEqual(d.load(d.task_record(root,task),{})["boot"],"new")
            self.assertFalse(d.can_recover(root,task,"another"))

    def test_resume_preserves_checkout_and_passes_recovery_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            task=row()
            folder=root/"issue-273-5"
            folder.mkdir()
            (root/"task-273-5.txt").write_text(task["task"])
            (folder/"trading_engine_v2.py").write_text("preserved change")
            d.save(d.task_record(root,task),dict(row=task,boot="new",recovered=True))
            outputs=[b"a"*40+b"\n",b" M trading_engine_v2.py\n",b"recovered diff"]
            with patch.object(d.subprocess,"run",side_effect=lambda args,**kw: subprocess.CompletedProcess(args,0)) as runner,patch.object(d.subprocess,"check_output",side_effect=outputs),patch.object(d.controller_publish,"git",side_effect=[b"a"*40+b"\n",str(folder).encode(),b"controller/local-273-123\n"]):
                self.assertEqual(d.run_task(root,root/"pilot.py",task,60000),"review_required")
                self.assertIn("--recover",runner.call_args_list[-2].args[0])
                self.assertFalse(any("worktree" in call.args[0] for call in runner.call_args_list))
            self.assertEqual((folder/"trading_engine_v2.py").read_text(),"preserved change")

    def test_committed_checkout_is_not_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            task=row()
            (root/"issue-273-5").mkdir()
            (root/"task-273-5.txt").write_text(task["task"])
            d.save(d.task_record(root,task),dict(row=task,boot="new",recovered=True))
            with patch.object(d.subprocess,"run") as runner,patch.object(d.subprocess,"check_output",return_value=b"a"*40+b"\n"),patch.object(d.controller_publish,"git",return_value=b"b"*40+b"\n"):
                self.assertEqual(d.run_task(root,root/"pilot.py",task,60000),"blocked:interrupted")
                self.assertEqual(runner.call_count,1)

    def test_same_boot_keeps_interrupted_generation_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            task=row()
            d.save(d.task_record(root,task),dict(row=task,boot="same",recovered=False))
            q=root/"queue.json"
            d.save(q,[task])
            results={"273:5":"reserved"}
            a=SimpleNamespace(parallel=2,publish=False,remote=False,queue=q,
                              daily_reservation=None,per_task=60000)
            with patch.object(d,"boot_id",return_value="same"),patch.object(d,"run_task") as runner,patch.object(d.time,"sleep",side_effect=lambda _: (root/"STOP").touch()):
                d.run_queue(a,root,root/"pilot.py",root/"budget.json",root/"results.json",{},results)
            runner.assert_not_called()
            self.assertEqual(results["273:5"],"blocked:interrupted")


if __name__ == "__main__":
    unittest.main()
