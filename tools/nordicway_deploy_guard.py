"""Separate SSH gate. Deployment remains unavailable until fully integrated."""
import json
import os
import re
import stat
import sys
PROTOCOL = 'escape-deploy-v1'
PROBE_DIRECTORY = '/home/nordicr4/escape_app/var'
PROBE_FILENAME = '.escape-deploy-write-probe'
DEPLOY_ENABLED = '/home/nordicr4/.escape_deploy_bridge/deploy-enabled'
APP_PYTHON = '/home/nordicr4/virtualenv/escape_app/3.11/bin/python'
APP_ENTRY = '/home/nordicr4/.escape_deploy_bridge/nordicway_app_release_entry.py'


def deployment_enabled(path=DEPLOY_ENABLED):
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
        try:
            info = os.fstat(fd)
            return (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                    and not info.st_mode & 0o077 and os.read(fd, 4) == b'1\n')
        finally:
            os.close(fd)
    except OSError:
        return False


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


def dispatch(command, runner=None, recovery=None, probe=None, app_runner=None):
    if command == PROTOCOL + ' ping':
        return {'status': 'ok', 'operation': 'ping'}
    if command == PROTOCOL + ' write-probe':
        return (probe or write_probe)()
    match = re.fullmatch(PROTOCOL + r' app-deploy ([0-9a-f]{40})', command)
    if match:
        if app_runner is None:
            return {'status':'blocked','operation':'app-deploy','reason':'deployment_not_ready'}
        return app_runner(match.group(1))
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


def exit_code(result):
    """Only acknowledge a completed, unblocked deployment as successful."""
    if result.get('status') == 'ok':
        return 0
    if result.get('operation') == 'app-deploy' and result.get('status') == 'completed':
        return 0
    if (result.get('operation') == 'deploy'
            and result.get('status') == 'updated_stopped'
            and result.get('stage') == 'complete'
            and result.get('recovery_required') is False):
        return 0
    return 1


def main():
    try:
        command = os.environ.get('SSH_ORIGINAL_COMMAND', '')
        runner = None
        recovery = None
        app_runner = None
        if re.fullmatch(PROTOCOL + r' (deploy|resume|app-deploy|app-resume) [0-9a-f]{40}', command):
            if not deployment_enabled():
                print(json.dumps({'status': 'blocked', 'reason': 'deployment_not_ready'}, separators=(',', ':')))
                return 1
            if ' app-deploy ' in command or ' app-resume ' in command:
                sha=command.rsplit(' ',1)[1]
                # The forced-command guard runs with -I -S. The installed
                # application's own venv is required for its push dependencies.
                os.execv(APP_PYTHON,[APP_PYTHON,'-I',APP_ENTRY,sha]+(['resume'] if ' app-resume ' in command else []))
            # A reviewed copy of the runner and its dependencies must be installed
            # alongside this guard. The currently installed ping guard lacks it.
            sys.path.insert(0, '/home/nordicr4/.escape_deploy_bridge')
            import nordicway_deploy_runner
            runner = lambda sha: nordicway_deploy_runner.run_request(sha, sys.stdin.buffer)
            recovery = nordicway_deploy_runner.resume
        result = dispatch(command, runner, recovery, app_runner=app_runner)
    except (ImportError, OSError, ValueError):
        result = {'status': 'failed', 'reason': 'operation_unavailable'}
    print(json.dumps(result, separators=(',', ':'), sort_keys=True))
    return exit_code(result)


if __name__ == '__main__':
    raise SystemExit(main())
