"""Restricted SSH gateway; release authorization remains the runner's duty."""
import json
import os
import re
import stat
import subprocess
from pathlib import Path

RUNNER = Path('/home/nordicr4/.escape_deploy_bridge/deploy_runner.py')
PYTHON = '/home/nordicr4/virtualenv/escape_app/3.11/bin/python'
PROTOCOL = 'escape-deploy-v1'


def dispatch(command, runner=RUNNER, python=PYTHON, execute=subprocess.run):
    if command == PROTOCOL + ' ping':
        return {'status': 'ok', 'operation': 'ping'}
    match = re.fullmatch(PROTOCOL + r' deploy ([0-9a-f]{40})', command)
    if not match:
        raise ValueError('invalid_operation')
    runner = Path(runner)
    parent = runner.parent
    if parent.is_symlink() or runner.is_symlink():
        raise ValueError('runner_unavailable')
    try:
        directory, info = parent.stat(), runner.stat()
    except OSError:
        raise ValueError('runner_unavailable') from None
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid()
            or directory.st_mode & 0o022 or not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid() or info.st_mode & 0o022):
        raise ValueError('runner_unavailable')
    result = execute([python, '-I', '-S', str(runner), match.group(1)],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=900, check=False)
    return {'status': 'ok' if result.returncode == 0 else 'failed',
            'operation': 'deploy', 'sha': match.group(1)}


def main():
    try:
        result = dispatch(os.environ.get('SSH_ORIGINAL_COMMAND', ''))
    except (OSError, ValueError, subprocess.SubprocessError):
        result = {'status': 'failed', 'reason': 'operation_unavailable'}
    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
