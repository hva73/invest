"""Owner-only recovery for the 39a609 pre-backup drain failure.

This never restores or writes the application database. It requires exact
installed files and healthy original runtime, archives the recovery marker,
and installs the reviewed bridge while the deploy lock is held.
"""
import ast
import fcntl
import json
import os
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

HOME = Path('/home/nordicr4')
RELEASE = '39a609ebdc315e818e0ef991764e8defb301f9e2'
INSTALLED = 'b0fae95aa0d0342ef6de2145452829e2fb47825d'
BUNDLE = 'cd36ad3ce5559728fc7f96b06d5b2b17c18b5310'
PREVIOUS_BUNDLE = 'ca06628b46abcfce8a270ee4e7349725c27c8059'
HEALTH = 'https://escape.nordic-response.dk/api/health'


def _git(repo, *args):
    return subprocess.check_output(['git', '-c', 'core.hooksPath=/dev/null',
                                    '-c', 'core.fsmonitor=false', '-C', str(repo), *args],
                                   stderr=subprocess.DEVNULL, timeout=30)


def _private_file(path, limit=4096):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > limit):
            raise ValueError('unsafe_private_file')
        return os.read(fd, limit + 1)
    finally:
        os.close(fd)


def _manifest(repo):
    tree = ast.parse(_git(repo, 'show', INSTALLED + ':apply_update.py').decode('utf-8'))
    nodes = [n.value for n in tree.body if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'FILES']
    if len(nodes) != 1:
        raise ValueError('manifest_unavailable')
    files = ast.literal_eval(nodes[0])
    if not isinstance(files, tuple) or not files or len(files) > 500 or len(files) != len(set(files)):
        raise ValueError('manifest_invalid')
    for name in files:
        if not isinstance(name, str) or not name or name.startswith('/'):
            raise ValueError('manifest_invalid')
        if any(part in ('', '.', '..', 'var', '.git') for part in name.split('/')):
            raise ValueError('manifest_invalid')
    return files


def _verify_files(repo, app):
    if app.is_symlink() or not app.is_dir():
        raise ValueError('unsafe_app')
    for name in _manifest(repo):
        target = app
        for part in name.split('/'):
            target = target / part
            if target.is_symlink():
                raise ValueError('unsafe_app_file')
        if not target.is_file() or target.stat().st_size > 50_000_000:
            raise ValueError('installed_file_missing')
        expected = (INSTALLED + '\n').encode('ascii') if name == 'BUILD_COMMIT' else _git(repo, 'show', INSTALLED + ':' + name)
        if target.read_bytes() != expected:
            raise ValueError('installed_file_mismatch')


def _verify_bridge_modules(repo, bridge):
    for name in ('nordicway_autostart.py', 'nordicway_readonly_diagnostics.py',
                 'nordicway_release_service.py'):
        if _private_file(bridge / name, 1_000_000) != _git(repo, 'show', PREVIOUS_BUNDLE + ':tools/' + name):
            raise ValueError('installed_bridge_changed')


def _verify_runtime(app, bridge):
    sys.path.insert(0, str(bridge))
    import nordicway_autostart
    import nordicway_readonly_diagnostics
    import nordicway_release_service
    var = app / 'var'
    if var.is_symlink() or not var.is_dir():
        raise ValueError('unsafe_var')
    if (not nordicway_autostart._present(var / 'hotwatch-autostart.enabled')
            or nordicway_autostart._present(var / 'hotwatch-autostart.disabled')):
        raise ValueError('motor_state_changed')
    if nordicway_release_service.status() != 'started':
        raise ValueError('service_not_started')
    with urlopen(Request(HEALTH, headers={'Cache-Control': 'no-cache'}), timeout=8) as response:
        if response.status != 200 or response.geturl() != HEALTH:
            raise ValueError('web_unavailable')
        raw = response.read(4097)
    if len(raw) > 4096:
        raise ValueError('web_unavailable')
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get('status') != 'ok' or payload.get('database') is not True:
        raise ValueError('web_unavailable')
    report = nordicway_readonly_diagnostics.inspect(root=app, now=datetime.now(timezone.utc))
    if report.get('installation', {}).get('declared_commit') != INSTALLED:
        raise ValueError('installed_version_changed')
    database, processes = report.get('database', {}), report.get('processes', {})
    if database.get('status') != 'ok' or processes.get('status') != 'ok':
        raise ValueError('runtime_unavailable')
    counts = processes.get('counts', {})
    for name in ('worker', 'supervisor'):
        item = database.get(name, {})
        age = item.get('age_seconds')
        if (item.get('status') != 'running' or type(age) not in (int, float) or not 0 <= age <= 60
                or type(counts.get(name)) is not int or counts[name] < 1):
            raise ValueError('motor_unavailable')


def _create(path, content):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(content)
        output.flush()
        os.fsync(output.fileno())


def _sync(path):
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare(repo, bridge, app, *, verify_runtime=_verify_runtime, verify_files=_verify_files, install=None):
    repo, bridge, app = Path(repo), Path(bridge), Path(app)
    info = bridge.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    var = app / 'var'
    if app.is_symlink() or var.is_symlink() or not var.is_dir():
        raise ValueError('unsafe_var')
    fd = os.open(var / 'escape-deploy.lock', os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('unsafe_lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        marker = bridge / 'deployment-incomplete.json'
        if _private_file(bridge / 'approved-sha') != (RELEASE + '\n').encode():
            raise ValueError('approval_changed')
        if _private_file(bridge / 'deploy-enabled') != b'1\n':
            raise ValueError('enable_changed')
        original = _private_file(marker, 1024)
        record = json.loads(original)
        if record != {'format': 1, 'sha': RELEASE, 'state': 'started',
                      'motor_enabled': True, 'motor_disabled': False} or type(record.get('format')) is not int \
                or type(record.get('motor_enabled')) is not bool or type(record.get('motor_disabled')) is not bool:
            raise ValueError('unexpected_recovery')
        _verify_bridge_modules(repo, bridge)
        # Keep the recovery marker while closing the remote gate for all checks.
        (bridge / 'deploy-enabled').unlink()
        _sync(bridge)
        verify_files(repo, app)
        verify_runtime(app, bridge)

        if install is None:
            data = _git(repo, 'show', BUNDLE + ':tools/nordicway_install_bridge.py')
            expected = _git(repo, 'rev-parse', BUNDLE + ':tools/nordicway_install_bridge.py').strip()
            actual = subprocess.check_output(['git', 'hash-object', '--stdin'], input=data).strip()
            if actual != expected:
                raise ValueError('installer_hash_mismatch')
            tmpfd, name = tempfile.mkstemp(prefix='bootstrap-', dir=bridge)
            try:
                with os.fdopen(tmpfd, 'wb') as output:
                    output.write(data)
                    output.flush()
                    os.fsync(output.fileno())
                result = subprocess.run([sys.executable, '-I', '-S', '-B', name, '--sha', BUNDLE],
                                        capture_output=True, text=True, timeout=180, check=False)
                if (result.returncode != 0 or 'Bridge: installed_disabled' not in result.stdout
                        or ('Source commit: ' + BUNDLE) not in result.stdout):
                    raise ValueError('bridge_install_failed')
            finally:
                Path(name).unlink(missing_ok=True)
        else:
            install(repo, bridge, BUNDLE)

        verify_files(repo, app)
        verify_runtime(app, bridge)
        if _private_file(marker, 1024) != original:
            raise ValueError('recovery_changed')
        archive_fd, archive_name = tempfile.mkstemp(prefix='recovery-reviewed-', suffix='.json', dir=bridge)
        with os.fdopen(archive_fd, 'wb') as output:
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
        if _private_file(Path(archive_name), 1024) != original:
            raise ValueError('archive_failed')
        _sync(bridge)
        try:
            marker.unlink()
            _sync(bridge)
            _create(bridge / 'deploy-enabled', b'1\n')
        except Exception:
            (bridge / 'deploy-enabled').unlink(missing_ok=True)
            if not os.path.lexists(marker):
                _create(marker, original)
            raise
        return {'status': 'ready', 'bundle': BUNDLE, 'release': RELEASE}
    finally:
        os.close(fd)


def main():
    try:
        result = prepare(HOME / 'escape_deploy/invest', HOME / '.escape_deploy_bridge', HOME / 'escape_app')
    except Exception as exc:
        allowed = {'unsafe_bridge', 'unsafe_var', 'unsafe_lock', 'approval_changed', 'enable_changed',
                   'unexpected_recovery', 'recovery_changed', 'archive_failed', 'bridge_install_failed',
                   'installed_file_mismatch', 'installed_file_missing', 'motor_state_changed',
                   'service_not_started', 'web_unavailable', 'runtime_unavailable', 'motor_unavailable',
                   'installed_bridge_changed'}
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in allowed else 'check_failed'
        print('STOP:', reason)
        raise SystemExit(1) from None
    print('Recovery marker archived; bridge:', result['bundle'])
    print('Approved release:', result['release'])
    print('Ready for one controlled deployment.')


if __name__ == '__main__':
    main()

