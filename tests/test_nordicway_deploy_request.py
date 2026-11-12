import copy
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('deploy_request', Path(__file__).resolve().parents[1] / 'tools/nordicway_deploy_request.py')
request = importlib.util.module_from_spec(spec)
spec.loader.exec_module(request)


class DeployRequestTests(unittest.TestCase):
    def setUp(self):
        self.sha = 'a' * 40
        self.proof = {'nonce':'1'*32,'expires':2000,'mac':'b'*64}
        self.event = {'action': 'created', 'sender': {'id': request.OWNER},
                      'issue': {'number': 16}, 'comment': {'user': {'id': request.OWNER},
                      'author_association': 'OWNER', 'body': request.PREFIX + json.dumps({'operation': 'deploy', 'sha': self.sha, 'approval': self.proof})}}

    def parse(self, event, actor=None, ref=request.BRANCH):
        return request.parse(event, 'issue_comment', ref, actor or str(request.OWNER))

    def test_only_owner_fixed_issue_and_fixed_operation(self):
        self.assertEqual(self.parse(self.event), {'operation': 'deploy', 'sha': self.sha, 'approval': self.proof})
        for field in ('sender', 'author', 'issue', 'action', 'pull_request', 'association', 'extra', 'duplicate', 'sha', 'shell', 'probe'):
            e = copy.deepcopy(self.event)
            if field == 'sender': e['sender']['id'] = 1
            if field == 'author': e['comment']['user']['id'] = 1
            if field == 'issue': e['issue']['number'] = 15
            if field == 'action': e['action'] = 'edited'
            if field == 'pull_request': e['issue']['pull_request'] = {}
            if field == 'association': e['comment']['author_association'] = 'MEMBER'
            if field == 'extra': e['comment']['body'] = request.PREFIX + json.dumps({'operation': 'deploy', 'sha': self.sha, 'cmd': 'id'})
            if field == 'duplicate': e['comment']['body'] = request.PREFIX + '{"operation":"deploy","sha":"' + self.sha + '","sha":"' + self.sha + '"}'
            if field == 'sha': e['comment']['body'] = request.PREFIX + json.dumps({'operation': 'deploy', 'sha': self.sha + ';id'})
            if field == 'shell': e['comment']['body'] = request.PREFIX + '$(id)'
            if field == 'probe': e['comment']['body'] = request.PREFIX + json.dumps({'operation': 'write-probe', 'sha': ''})
            with self.subTest(field=field): self.assertIsNone(self.parse(e))
        self.assertIsNone(self.parse(self.event, actor='3'))
        self.assertIsNone(self.parse(self.event, ref='refs/heads/other'))

    def test_dispatch_and_resume(self):
        e = {'sender': {'id': request.OWNER}, 'inputs': {'operation': 'write-probe', 'release_sha': ''}}
        self.assertEqual(request.parse(e, 'workflow_dispatch', request.BRANCH, str(request.OWNER)), {'operation': 'write-probe', 'sha': ''})
        e['inputs'] = {'operation': 'deploy', 'release_sha': self.sha}
        self.assertIsNone(request.parse(e, 'workflow_dispatch', request.BRANCH, str(request.OWNER)))
        self.event['comment']['body'] = request.PREFIX + json.dumps({'operation': 'resume', 'sha': self.sha})
        self.assertEqual(self.parse(self.event)['operation'], 'resume')
        self.event['comment']['body'] = request.PREFIX + json.dumps({'operation': 'app-resume', 'sha': self.sha})
        self.assertEqual(self.parse(self.event)['operation'], 'app-resume')

    def test_app_deploy_requires_single_line_summary_and_sha(self):
        for summary, valid in [('Mobil og datakilder',True),('',False),('x\nsha=evil',False),('x'*501,False)]:
            e=copy.deepcopy(self.event)
            e['comment']['body']=request.PREFIX+json.dumps({'operation':'app-deploy','sha':self.sha,'summary':summary})
            result=self.parse(e)
            if valid:self.assertEqual(result,{'operation':'app-deploy','sha':self.sha,'summary':summary})
            else:self.assertIsNone(result)

    def test_event_file_outputs_only_validated_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            event, output = Path(tmp) / 'event', Path(tmp) / 'output'
            event.write_text(json.dumps(self.event))
            env = {**os.environ, 'GITHUB_EVENT_PATH': str(event), 'GITHUB_OUTPUT': str(output),
                   'GITHUB_EVENT_NAME': 'issue_comment', 'GITHUB_REF': request.BRANCH, 'GITHUB_ACTOR_ID': str(request.OWNER)}
            run = subprocess.run([sys.executable, request.__file__], env=env, capture_output=True, text=True)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertEqual(output.read_text(), 'operation=deploy\nsha=' + self.sha + '\napproval=' + json.dumps(self.proof, separators=(',', ':')) + '\n')
            output.unlink()
            env['GITHUB_ACTOR_ID'] = '3'
            run = subprocess.run([sys.executable, request.__file__], env=env, capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
