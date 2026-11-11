"""Fixed SSH transport for the restricted runner; no arbitrary commands."""
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from nordicway_deploy_ping import HOST
from nordicway_hostkey import verify
from nordicway_readonly_client import _run_limited

STAGES = {'authorization', 'preflight', 'quota', 'stage', 'service_state',
          'stop', 'drain', 'backup_and_apply', 'verify_backup', 'verify_install',
          'start', 'health', 'complete', 'runner'}


def run(env=None, transport=_run_limited):
    env = os.environ if env is None else env
    sha, token = env.get('ESCAPE_RELEASE_SHA', ''), env.get('ESCAPE_CPANEL_API_TOKEN', '')
    operation = env.get('ESCAPE_DEPLOY_OPERATION', 'deploy')
    if (env.get('ESCAPE_DEPLOY_AUTHORIZED') != '1' or not env.get('SSH_AUTH_SOCK')
            or not re.fullmatch(r'[0-9a-f]{40}', sha)
            or operation not in ('deploy', 'resume')
            or (operation == 'deploy' and not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token))):
        return {'status': 'blocked', 'reason': 'configuration_unavailable'}
    try:
        known = verify(env.get('NORDICWAY_KNOWN_HOST', ''), env.get('NORDICWAY_VERIFIED_FINGERPRINT', ''))
        with tempfile.TemporaryDirectory(prefix='escape-deploy-hostkey-') as tmp:
            hosts = Path(tmp) / 'known_hosts'
            hosts.write_text(known, encoding='ascii')
            hosts.chmod(0o600)
            command = ['ssh', '-F', '/dev/null', '-T', '-p', '33', '-o', 'BatchMode=yes',
                       '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
                       '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(hosts),
                       '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ForwardAgent=no',
                       '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10',
                       HOST, 'escape-deploy-v1 ' + operation + ' ' + sha]
            # Token is sent only over SSH stdin, never in command arguments or logs.
            payload = json.dumps({'cpanel_token': token}, separators=(',', ':')).encode() if operation == 'deploy' else b''
            result = transport(command, input=payload, capture_output=True, timeout=900, env=env)
        if len(result.stdout) > 1024:
            raise ValueError('invalid_reply')
        reply = json.loads(result.stdout)
        if operation == 'resume':
            if (not isinstance(reply, dict) or set(reply) != {'operation', 'status', 'recovery_required'}
                    or reply['operation'] != 'resume' or reply['status'] not in ('ok', 'failed')
                    or type(reply['recovery_required']) is not bool
                    or (reply['status'] == 'ok' and (result.returncode != 0 or reply['recovery_required']))):
                raise ValueError('invalid_reply')
            return reply
        if (not isinstance(reply, dict) or set(reply) != {'operation', 'status', 'stage',
                'service_restored', 'recovery_required'} or reply['operation'] != 'deploy'
                or reply['status'] not in ('ok', 'failed', 'updated_stopped')
                or reply['stage'] not in STAGES or type(reply['service_restored']) is not bool
                or type(reply['recovery_required']) is not bool
                or (reply['status'] == 'ok' and (result.returncode != 0
                    or reply['stage'] != 'complete' or reply['recovery_required']))):
            raise ValueError('invalid_reply')
        return reply
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        # The remote process may have continued after a lost SSH connection.
        return {'status': 'unknown', 'reason': 'transport_or_reply_failed', 'recovery_required': True}


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0 if result.get('status') == 'ok' else 1)
