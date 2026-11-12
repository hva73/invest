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
SERVICE_STATE_REASONS = {'selector_failed', 'application_state_unknown',
                         'selector_exec_unavailable', 'selector_exit_nonzero',
                         'selector_response_too_large', 'selector_invalid_json', 'selector_result_failed',
                         'service_status_unknown', 'state_record_failed', 'service_state_unavailable'}
DRAIN_REASONS = {'cron_unverified', 'database_unavailable', 'passenger_active', 'database_in_use',
                 'process_inspection_unavailable', 'quiescence_unverified',
                 'motor_stop_timeout', 'drain_unavailable'}


def run(env=None, transport=_run_limited):
    env = os.environ if env is None else env
    sha, token = env.get('ESCAPE_RELEASE_SHA', ''), env.get('ESCAPE_CPANEL_API_TOKEN', '')
    operation = env.get('ESCAPE_DEPLOY_OPERATION', 'deploy')
    approval_json = env.get('ESCAPE_OWNER_APPROVAL_PROOF', '')
    access = (env.get('ESCAPE_WRITE_PROBE_AUTHORIZED') == '1' if operation == 'write-probe'
              else env.get('ESCAPE_DEPLOY_AUTHORIZED') == '1')
    if (not access or not env.get('SSH_AUTH_SOCK')
            or operation not in ('deploy', 'resume', 'write-probe')
            or (operation in ('deploy', 'resume') and not re.fullmatch(r'[0-9a-f]{40}', sha))
            or (operation == 'write-probe' and bool(sha))
            or (operation == 'deploy' and (not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token)
                or not approval_json or len(approval_json) > 512))):
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
                       HOST, 'escape-deploy-v1 ' + operation + ((' ' + sha) if sha else '')]
            # Token is sent only over SSH stdin, never in command arguments or logs.
            payload = b''
            if operation == 'deploy':
                approval = json.loads(approval_json)
                if not isinstance(approval, dict) or set(approval) != {'nonce', 'expires', 'mac'}:
                    raise ValueError('invalid_approval')
                payload = json.dumps({'cpanel_token': token, 'approval': approval}, separators=(',', ':')).encode()
            result = transport(command, input=payload, capture_output=True, timeout=900, env=env)
        if len(result.stdout) > 1024:
            raise ValueError('invalid_reply')
        reply = json.loads(result.stdout)
        if operation == 'write-probe':
            if result.returncode != 0 or reply != {'status': 'ok', 'operation': 'write_probe'}:
                raise ValueError('invalid_reply')
            return reply
        if operation == 'resume':
            if (not isinstance(reply, dict) or set(reply) not in ({'operation', 'status', 'recovery_required'},
                    {'operation', 'status', 'recovery_required', 'backup_cleanup'})
                    or reply['operation'] != 'resume' or reply['status'] not in ('ok', 'failed')
                    or type(reply['recovery_required']) is not bool
                    or ('backup_cleanup' in reply and reply['backup_cleanup'] not in ('ok', 'failed', 'not_run'))
                    or (reply['status'] == 'ok' and (result.returncode != 0 or reply['recovery_required']))):
                raise ValueError('invalid_reply')
            # Older bridge versions have no retention status. Never imply
            # that backup cleanup ran when a legacy reply omits the field.
            reply.setdefault('backup_cleanup', 'unknown')
            return reply
        expected = {'operation', 'status', 'stage', 'service_restored', 'recovery_required'}
        if (not isinstance(reply, dict) or set(reply) not in (expected, expected | {'backup_cleanup'},
                expected | {'reason'}, expected | {'backup_cleanup', 'reason'})
                or ('backup_cleanup' in reply and reply['backup_cleanup'] not in ('ok', 'failed', 'not_run'))
                or ('reason' in reply and (reply['status'] != 'failed' or
                    not ((reply['stage'] == 'service_state' and reply['reason'] in SERVICE_STATE_REASONS)
                         or (reply['stage'] == 'drain' and reply['reason'] in DRAIN_REASONS))))
                or reply['operation'] != 'deploy'
                or reply['status'] not in ('ok', 'failed', 'updated_stopped')
                or reply['stage'] not in STAGES or type(reply['service_restored']) is not bool
                or type(reply['recovery_required']) is not bool
                or (reply['status'] in ('ok', 'updated_stopped') and (result.returncode != 0
                    or reply['stage'] != 'complete' or reply['recovery_required']))):
            raise ValueError('invalid_reply')
        reply.setdefault('backup_cleanup', 'unknown')
        return reply
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        # The remote process may have continued after a lost SSH connection.
        return {'status': 'unknown', 'reason': 'transport_or_reply_failed', 'recovery_required': True}


def exit_code(result):
    if result.get('status') == 'ok':
        return 0
    if (result.get('operation') == 'deploy' and result.get('status') == 'updated_stopped'
            and result.get('stage') == 'complete' and result.get('recovery_required') is False):
        return 0
    return 1


if __name__ == '__main__':
    result = run()
    print(json.dumps(result, sort_keys=True, separators=(',', ':')))
    raise SystemExit(exit_code(result))
