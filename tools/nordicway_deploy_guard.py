"""Separate SSH gate. Deployment remains unavailable until fully integrated."""
import json
import os
import re
import stat
import sys
PROTOCOL = 'escape-deploy-v1'
PROBE_DIRECTORY = '/home/nordicr4/escape_app/var'
PROBE_FILENAME = '.escape-deploy-write-probe'


def write_probe(directory=PROBE_DIRECTORY):
    flags = os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0) | getattr(os, 'O_NOFOLLOW', 0)
    directory_fd = os.open(directory, flags)
    try:
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('unsafe_probe_directory')
        fd = os.open(PROBE_FILENAME, os.O_CREAT | os.O_EXCL | os.O_RDWR |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600, dir_fd=directory_fd)
        try:
            with os.fdopen(fd, 'w+b') as output:
                output.write(b'escape-deploy-write-probe-v1\n')
                output.flush()
                os.fsync(output.fileno())
                output.seek(0)
                if output.read() != b'escape-deploy-write-probe-v1\n':
                    raise ValueError('probe_readback_failed')
        finally:
            os.unlink(PROBE_FILENAME, dir_fd=directory_fd)
        return {'status': 'ok', 'operation': 'write_probe'}
    finally:
        os.close(directory_fd)


def dispatch(command, runner=None, recovery=None, probe=None):
    if command == PROTOCOL + ' ping':
        return {'status': 'ok', 'operation': 'ping'}
    if command == PROTOCOL + ' write-probe':
        return (probe or write_probe)()
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
