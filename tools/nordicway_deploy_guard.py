"""Separate SSH gate. Deployment remains unavailable until fully integrated."""
import json
import os
import re
import sys
PROTOCOL = 'escape-deploy-v1'


def dispatch(command, runner=None, recovery=None):
    if command == PROTOCOL + ' ping':
        return {'status': 'ok', 'operation': 'ping'}
    match = re.fullmatch(PROTOCOL + r' deploy ([0-9a-f]{40})', command)
    if match:
        if runner is None:
            return {'status': 'blocked', 'operation': 'deploy', 'reason': 'deployment_not_ready'}
        return runner(match.group(1))
    match = re.fullmatch(PROTOCOL + r' resume ([0-9a-f]{40})', command)
    if match:
        if recovery is None:
            return {'status': 'blocked', 'operation': 'resume', 'reason': 'deployment_not_ready'}
        return recovery(match.group(1))
    raise ValueError('invalid_operation')


def main():
    try:
        command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
        runner = None
        recovery = None
        if re.fullmatch(PROTOCOL + r' (deploy|resume) [0-9a-f]{40}', command):
            # A reviewed copy of the runner and its dependencies must be installed
            # alongside this guard. The currently installed ping guard lacks it.
            sys.path.insert(0, '/home/nordicr4/.escape_deploy_bridge')
            import nordicway_deploy_runner
            runner = lambda sha: nordicway_deploy_runner.run_request(sha, sys.stdin.buffer)
            recovery = nordicway_deploy_runner.resume
        result = dispatch(command, runner, recovery)
    except (ImportError, OSError, ValueError):
        result = {'status': 'failed', 'reason': 'operation_unavailable'}
    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
