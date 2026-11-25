"""Connect owner approval in the installed app to the existing deploy runner.

This module is not an SSH entry point by itself. It must be installed behind
the restricted deploy guard before a workflow can invoke it.

#263 static integration for the next release
Pass public_status_dir as a trusted absolute server-side setting. Provision
that dedicated directory outside the Passenger app and release tree, owned
by the runner account and readable by the webserver. Initialize
status.json to {"state":"normal"} followed by a newline after verifying
the current service. Keep the directory and its ancestors under trusted
administrative control and outside the updater's file manifest.
Use the same directory for all invocations of the guarded release entry point.
Omitting the setting preserves the legacy wrapper for the frozen release.

Map /escape-release/status.json directly to that file and
/escape-release/maintenance.html to a standalone static page. Configure
Apache/cPanel to serve both before Passenger routing, with Cache-Control:
no-store and no directory listing. At virtual-host level, evaluate the local
marker before handing app navigation to Passenger. Return HTTP 503 for
maintenance or recovery, with ErrorDocument 503 set to the local
/escape-release/maintenance.html URI. Use the same ErrorDocument for a 503
from Passenger. Keep the two
static URLs exempt from that routing and any service-worker navigation cache.
Missing or invalid status must not trigger a return to the app during an
outage. Keep the original navigation URL when serving the 503 page.

The maintenance page displays “Vi opdaterer ESCAPE”, “ESCAPE er midlertidigt
utilgængelig, mens vi installerer en ny version.” and “Forbindelsen
genoprettes automatisk.” Poll status.json without caching and retry the
original URL when state is normal. Show recovery separately, without a
countdown. After an interrupted run, reconcile the private release and
verify service health before an operator atomically resets a stale marker
under the same directory lock.
The cPanel paths, static routing and recovery wiring are server integration
steps and need verification with Passenger stopped.
"""
import fcntl
import os
import re
import secrets
import stat
from pathlib import Path

import release_approval


_STATUS_FILE = 'status.json'
_STATUS = {state: ('{"state":"' + state + '"}\n').encode('ascii')
           for state in ('normal', 'maintenance', 'recovery')}
_BEFORE_STOP = ('authorization', 'preflight', 'quota', 'stage', 'service_state')


def _open_status_directory(path):
    path = Path(path)
    if path.anchor != '/' or not path.parts[1:] or '..' in path.parts:
        raise ValueError('unsafe_public_status_directory')
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open('/', flags)
    try:
        for part in path.parts[1:]:
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        info = os.fstat(fd)
        if info.st_uid != os.getuid() or info.st_mode & 0o022:
            raise ValueError('unsafe_public_status_directory')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read_status(directory):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(_STATUS_FILE, flags, dir_fd=directory), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_mode & 0o022):
            raise ValueError('unsafe_public_status_file')
        return stream.read(64)


def _publish_status(directory, previous, state):
    if _read_status(directory) != _STATUS[previous]:
        raise ValueError('unexpected_public_release_status')
    temporary = '.status-' + secrets.token_hex(16)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    fd = os.open(temporary, flags, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(_STATUS[state])
            stream.flush()
            os.fchmod(stream.fileno(), 0o644)
            os.fsync(stream.fileno())
        os.replace(temporary, _STATUS_FILE, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass


def _final_public_state(result):
    if (isinstance(result, dict) and result.get('operation') == 'deploy'
            and type(result.get('service_restored')) is bool
            and result.get('recovery_required') is False):
        status, stage = result.get('status'), result.get('stage')
        restored = result.get('service_restored') is True
        if status == 'ok' and stage == 'complete' and restored:
            return 'normal'
        if status == 'failed' and (stage in _BEFORE_STOP or (stage in (
                'stop', 'drain', 'backup_and_apply', 'verify_backup', 'verify_install', 'start'
        ) and restored)):
            return 'normal'
    return 'recovery'


def _key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size != 32):
            raise ValueError('unsafe_owner_key')
        key = os.read(fd, 33)
        if len(key) != 32:
            raise ValueError('unsafe_owner_key')
        return key
    finally:
        os.close(fd)


def run(connect, sha, summary, cpanel_token, bridge, *, runner, create_proof,
        notify, lifetime=600, clock=None, sleep=None, public_status_dir=None):
    """Wait for authenticated owner approval, then call the installed runner.

    The token is passed only in memory. No SSH transport, credentials or
    installation is configured by importing this module.
    """
    if not isinstance(cpanel_token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', cpanel_token):
        raise ValueError('invalid_token')
    directory=Path(bridge)
    info=directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    with connect() as c:
        rows=c.execute("SELECT id FROM users WHERE username='owner' AND role='admin' AND active=1").fetchall()
    if len(rows)!=1:
        raise ValueError('owner_unavailable')
    owner_id=rows[0][0]
    def execute(approved_sha):
        # Proof is generated server-side only after the owner approves the
        # matching candidate; the deploy runner verifies and consumes it.
        proof=create_proof(approved_sha,_key(directory/'owner-approval-key'))
        if public_status_dir is None:
            return runner(approved_sha,cpanel_token,owner_request=proof)
        public_directory = _open_status_directory(public_status_dir)
        try:
            _publish_status(public_directory, 'normal', 'maintenance')
            try:
                result = runner(approved_sha, cpanel_token, owner_request=proof)
            except BaseException:
                _publish_status(public_directory, 'maintenance', 'recovery')
                raise
            _publish_status(public_directory, 'maintenance', _final_public_state(result))
            return result
        finally:
            os.close(public_directory)
    kwargs={'lifetime':lifetime}
    if clock is not None:kwargs['clock']=clock
    if sleep is not None:kwargs['sleep']=sleep
    return release_approval.stage_and_wait(connect,sha,summary,owner_id,notify,execute,**kwargs)
