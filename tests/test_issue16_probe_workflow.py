import os
import subprocess
import tempfile
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parents[1] / '.github/workflows/escape-deploy-public-key.yml'
FINGERPRINT = 'SHA256:U8MQZwyzMoDmDyRnBIqFqN14BVifmGKNSi+7B8OACDI'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        text = WORKFLOW.read_text()
        job = text.split('\n  write_probe:\n', 1)[1]
        self.assertIn("github.event.comment.body == '/escape-deploy-write-probe'", job)
        self.assertIn('vars.ESCAPE_WRITE_PROBE_AUTHORIZED', job)
        script = job.split('        run: |\n', 1)[1]
        self.script = '\n'.join(line[10:] for line in script.splitlines() if line.startswith('          '))
        self.mock('ssh-keyscan', 'echo hostkey')
        self.mock('ssh-keygen', "echo '256 " + FINGERPRINT + " host (ED25519)'")
        self.mock('ssh', "echo \"$*\" > \"$RUNNER_TEMP/called\"\necho '{\"operation\":\"write_probe\",\"status\":\"ok\"}'")
        self.env = {**os.environ, 'PATH': str(self.bin) + ':' + os.environ['PATH'],
                    'RUNNER_TEMP': str(self.root), 'DEPLOY_PRIVATE_KEY': 'synthetic-key',
                    'WRITE_PROBE_AUTHORIZED': '1'}

    def tearDown(self):
        self.temp.cleanup()

    def mock(self, name, text):
        path = self.bin / name
        path.write_text('#!/bin/sh\n' + text + '\n')
        path.chmod(0o755)

    def run_script(self):
        return subprocess.run(['bash', '-e', '-u', '-c', self.script], env=self.env,
                              capture_output=True, text=True)

    def test_authorized_probe_uses_fixed_command_and_removes_key(self):
        result = self.run_script()
        self.assertEqual((result.returncode, result.stdout.strip()), (0, 'write_probe:ok'))
        self.assertTrue((self.root / 'called').read_text().strip().endswith('escape-deploy-v1 write-probe'))
        self.assertFalse((self.root / 'deploy-probe-key').exists())

    def test_without_separate_authorization_no_ssh_occurs(self):
        self.env['WRITE_PROBE_AUTHORIZED'] = '0'
        self.assertNotEqual(self.run_script().returncode, 0)
        self.assertFalse((self.root / 'called').exists())
