import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from development import controller_dispatch as dispatch, controller_events as events, controller_pilot as pilot, controller_progress as progress, controller_publish as publish
from development.controller_queue import plan

def row(issue,role,generation,path,priority=1,dependencies=()):
    return dict(issue=issue,role=role,generation=generation,paths=[path],priority=priority,
                status="ready",dependencies=list(dependencies),task="Scoped fixture",base_sha="a"*40,
                base_branch="codex/escape-development")

class LiveControllerTests(unittest.TestCase):
    def test_stream_real_child_and_test_phase_without_raw_agent_output(self):
        lines=[
            {"type":"thread.started","thread_id":"12345678-1234-1234-1234-123456789abc"},
            {"type":"item.started","item":{"type":"command_execution","command":"python -B -m unittest tests.test_fixture"}},
            {"type":"item.completed","item":{"type":"command_execution","aggregated_output":"PRIVATE FIXTURE"}},
            {"type":"item.completed","item":{"type":"agent_message","text":"Done\nESCAPE_DRAFT_READY"}},
            {"type":"turn.completed","usage":{"input_tokens":230000,"cached_input_tokens":220000,"output_tokens":4068}},
        ]
        program="import sys,json; sys.stdin.read(); rows="+repr(lines)+"; [print(json.dumps(x),flush=True) for x in rows]"
        phases=[]
        result=events.run([sys.executable,"-c",program],"fixture",os.environ.copy(),5,phases.append)
        self.assertEqual(result.returncode,0)
        self.assertTrue(result.draft_ready)
        self.assertEqual(phases,["TESTING"])
        self.assertNotIn("PRIVATE FIXTURE",result.stdout)
        self.assertEqual(pilot.continuation_usage(pilot.usage_breakdown(result.stdout),234068),14068)
        self.assertEqual(pilot.continuation_usage({"uncached_plus_output":None},234068),234068)
    def test_stream_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            events.run([sys.executable,"-c","import time; time.sleep(5)"],"",os.environ.copy(),0.1)
    def test_scope_release_only_exact_allowlist(self):
        p="tools/nordicway_deploy_client.py"
        self.assertTrue(publish.allowed(p,[p],"release"))
        self.assertFalse(publish.allowed(p,["tools/"],"release"))
        self.assertFalse(publish.allowed(p,[p],"mobile"))
        self.assertFalse(publish.allowed(".github/workflows/escape-deploy-ping.yml",[".github/"],"release"))
        self.assertFalse(publish.allowed("tools/nordicway_deploy_guard.py",["tools/nordicway_deploy_guard.py"],"release"))
    def test_active_scope_survives_remote_queue_replacement(self):
        one=row(57,"release",1,"a.py")
        two=row(57,"release",2,"b.py")
        effective=dispatch.effective_rows([two],{"57:1":"reserved"},[one])
        self.assertEqual(plan(effective),[])
        done=dispatch.effective_rows([one,dict(two,dependencies=["57:1"])],{"57:1":"draft_pr"},[])
        self.assertEqual(plan(done),[])
    def test_scheduler_starts_next_generation_while_other_worker_runs(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            rows=[row(57,"release",1,"a.py"),row(57,"release",2,"b.py"),
                  row(14,"data",1,"feed.py")]
            q=root/"queue.json";q.write_text(json.dumps(rows))
            next_started=threading.Event()
            data_started=threading.Event()
            calls=[]
            def worker(root,script,task,allowance,publish):
                key=dispatch.task_key(task);calls.append(key)
                if key=="14:1":
                    data_started.set()
                    if not next_started.wait(5):raise RuntimeError("worker idle barrier")
                elif key=="57:1":
                    if not data_started.wait(5):raise RuntimeError("parallel start failed")
                elif key=="57:2":
                    next_started.set()
                    (root/"STOP").touch()
                return "draft_pr"
            a=SimpleNamespace(parallel=2,publish=False,remote=False,queue=q,daily_reservation=None,per_task=60000)
            with patch.object(dispatch,"run_task",side_effect=worker),patch.object(dispatch.time,"sleep",side_effect=AssertionError("unexpected idle")):
                dispatch.run_queue(a,root,root/"pilot.py",root/"budget.json",root/"results.json",{}, {})
            self.assertTrue(next_started.is_set())
            self.assertEqual(set(calls),{"57:1","57:2","14:1"})
            self.assertEqual(json.loads((root/"results.json").read_text()),{"57:1":"draft_pr","57:2":"draft_pr","14:1":"draft_pr"})
    def test_context_handover_continues_original_task_and_stops_on_ready_marker(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);task=root/"task.txt";task.write_text("same scoped task")
            sid="12345678-1234-1234-1234-123456789abc"
            first=SimpleNamespace(returncode=1,stdout='{"type":"turn.failed","error":{"message":"context_length_exceeded"}}',draft_ready=False)
            second=SimpleNamespace(returncode=0,stdout=json.dumps({"type":"thread.started","thread_id":sid})+"\n"+json.dumps({"type":"turn.completed","usage":{"input_tokens":200,"cached_input_tokens":100,"output_tokens":50}}),draft_ready=True)
            args=["pilot","--role","release","--issue","57","--generation","2","--task-file",str(task),"--progress-root",str(root),"--checkpoint",str(root/"checkpoint.json"),"--allowed-paths-json",'["a.py"]',"--execute"]
            with patch.object(sys,"argv",args),patch.object(pilot,"git",side_effect=[b"controller/local-57-123\n",b""]),patch.object(pilot,"fingerprint",return_value="fingerprint"),patch.object(pilot,"scoped_changes",return_value=True),patch.object(pilot.subprocess,"run",return_value=SimpleNamespace(returncode=0,stdout="Logged in using ChatGPT",stderr="")),patch.object(pilot.controller_events,"run",side_effect=[first,second]) as runner:
                pilot.main()
            self.assertEqual(runner.call_count,2)
            for call in runner.call_args_list:
                self.assertNotIn("resume",call.args[0])
                self.assertIn("same scoped task",call.args[1])
            self.assertTrue((root/"progress/57-2-HANDOVER.json").is_file())
            self.assertTrue(json.loads((root/"checkpoint.json").read_text())["completed_turn"])
    def test_provider_limit_is_not_context_handover(self):
        raw='{"type":"turn.failed","error":{"code":"usage_limit_reached"}}'
        self.assertTrue(pilot.provider_limited(raw))
        self.assertFalse(pilot.context_exhausted(raw))
    def test_progress_order_and_deduplication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            progress.record(root,57,3,"STARTED")
            progress.record(root,57,3,"WORKING")
            with patch.object(progress.subprocess,"check_output",return_value="") as gh:
                progress.flush(root)
                messages=[x.args[0][-1] for x in gh.call_args_list if x.args[0][1]=="issue"]
                self.assertIn("STARTED",messages[0])
                self.assertIn("WORKING",messages[1])
                progress.flush(root)
                self.assertEqual(gh.call_count,4)
