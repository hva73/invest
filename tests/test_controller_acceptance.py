import base64,json,plistlib,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from development import controller_remote as remote,controller_publish as publish,controller_mac as mac,controller_dispatch as dispatch

def row():
    return dict(issue=54,role="mobile",priority=1,status="ready",paths=["static/mobile.js"],base_sha="a"*40,base_branch="codex/escape-development",task="Fix approved mobile layout",generation=1)

class Acceptance(unittest.TestCase):
    def test_queue_authenticated_and_closed_issue(self):
        payload={"encoding":"base64","content":base64.b64encode(json.dumps([row()]).encode()).decode()}
        with tempfile.TemporaryDirectory() as d,patch.object(remote,"api",side_effect=[payload,{"state":"closed"}]) as api:
            p=Path(d)/"queue.json"
            remote.refresh(Path(d),p)
            self.assertEqual(json.loads(p.read_text())[0]["status"],"blocked")
            self.assertEqual(api.call_count,2)
    def test_bad_queue_never_replaces_existing(self):
        with tempfile.TemporaryDirectory() as d,patch.object(remote,"api",return_value={"encoding":"invalid"}):
            p=Path(d)/"queue.json";p.write_text("[]")
            with self.assertRaises(ValueError): remote.refresh(Path(d),p)
            self.assertEqual(p.read_text(),"[]")
    def test_publish_scope(self):
        for p in [".github/workflows/deploy.yml","static/mobile.js/../secret","static/private.key","development/controller_mac.py"]:
            self.assertFalse(publish.allowed(p,["static/","development/",".github/"]))
        self.assertTrue(publish.allowed("static/mobile.js",["static/mobile.js"]))
        self.assertFalse(publish.allowed("static/mobile.js.old",["static/mobile.js"]))
    def test_launch_configuration(self):
        cfg=mac.configuration(Path("/repo"),Path("/runtime"),"/usr/bin/python3","/bin",True)
        self.assertEqual(plistlib.loads(plistlib.dumps(cfg)),cfg)
        self.assertIn("--publish",cfg["ProgramArguments"])
        self.assertIn("--remote",cfg["ProgramArguments"])
        self.assertNotIn("--publish",mac.configuration(Path("/repo"),Path("/runtime"),"/python","/bin")["ProgramArguments"])
    def test_generation(self):
        self.assertNotEqual(dispatch.task_key(row()),dispatch.task_key(dict(row(),generation=2)))
        with self.assertRaises(ValueError): dispatch.task_key(dict(row(),generation="../"))
    def test_full_dispatch_mocked_model_and_publication(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def run(args,**kwargs):
                if "worktree" in args:
                    Path(args[-2]).mkdir()
                from subprocess import CompletedProcess
                return CompletedProcess(args,0)
            # Progress delivery has its own transport boundary; isolate it from git fixtures.
            with patch.object(dispatch,"progress") as progress,patch.object(dispatch.subprocess,"run",side_effect=run),patch.object(dispatch.subprocess,"check_output",side_effect=[b"a"*40+b"\n",b" M static/mobile.js\n",b"diff fixture"]) as git_output,patch.object(dispatch.controller_publish,"publish",return_value="https://github.com/hva73/invest/pull/999") as pub:
                result=dispatch.run_task(root,root/"development/controller_pilot.py",row(),60000,True)
                self.assertEqual(result,"draft_pr")
                pub.assert_called_once()
                progress.assert_called_once_with(root,row(),"STARTED",True)
                self.assertEqual(git_output.call_count,3)
                self.assertEqual((root/"issue-54-1.patch").read_bytes(),b"diff fixture")
                self.assertTrue((root/"issue-54-1.pr").exists())
                self.assertEqual(dispatch.run_task(root,root/"development/controller_pilot.py",row(),60000,True),"existing_checkout")
