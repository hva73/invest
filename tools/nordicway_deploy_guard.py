"""Separate SSH gate. Deployment remains unavailable until fully integrated."""
import json
import os
import re
PROTOCOL = 'escape-deploy-v1'


def dispatch(command):
    if command == PROTOCOL + ' ping':
        return {'status': 'ok', 'operation': 'ping'}
    if re.fullmatch(PROTOCOL + r' deploy ([0-9a-f]{40})', command):
        return {'status': 'blocked', 'operation': 'deploy', 'reason': 'deployment_not_ready'}
    raise ValueError('invalid_operation')


def main():
    try:
        result = dispatch(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    except (OSError, ValueError):
        result = {'status': 'failed', 'reason': 'operation_unavailable'}
    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
