"""Test only the dedicated deploy identity's SSH ping. Cannot deploy."""
import json
import os
import subprocess
import tempfile
from pathlib import Path
from nordicway_hostkey import verify
from nordicway_readonly_client import _run_limited

HOST = 'nordicr4@cp14.nordicway.dk'


def ping(env=None, runner=_run_limited):
    env = os.environ if env is None else env
    if env.get('NORDICWAY_DEPLOY_PING_AUTHORIZED') != '1' or not env.get('SSH_AUTH_SOCK'):
        return {'status': 'blocked'}
    try:
        known = verify(env.get('NORDICWAY_KNOWN_HOST', ''), env.get('NORDICWAY_VERIFIED_FINGERPRINT', ''))
        with tempfile.TemporaryDirectory(prefix='escape-deploy-hostkey-') as tmp:
            hosts = Path(tmp) / 'known_hosts'
            hosts.write_text(known, encoding='ascii'); hosts.chmod(0o600)
            cmd = ['ssh', '-F', '/dev/null', '-T', '-p', '33', '-o', 'BatchMode=yes',
                   '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                   '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(hosts),
                   '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ForwardAgent=no',
                   '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10',
                   HOST, 'escape-deploy-v1 ping']
            result = runner(cmd, input=b'', capture_output=True, timeout=30, env=env)
        if result.returncode != 0 or len(result.stdout) > 1024:
            raise ValueError('ping_failed')
        data = json.loads(result.stdout)
        if data != {'status': 'ok', 'operation': 'ping'}:
            raise ValueError('unexpected_reply')
        return {'status': 'ok'}
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return {'status': 'failed'}


if __name__ == '__main__':
    result = ping()
    print(json.dumps(result, separators=(',', ':')))
    raise SystemExit(0 if result['status'] == 'ok' else 1)
