"""Connect owner approval in the installed app to the existing deploy runner.

This module is not an SSH entry point by itself. It must be installed behind
the restricted deploy guard before a workflow can invoke it.
"""
import os
import re
import stat
from pathlib import Path

import release_approval


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
        notify, lifetime=600, clock=None, sleep=None):
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
        return runner(approved_sha,cpanel_token,owner_request=proof)
    kwargs={'lifetime':lifetime}
    if clock is not None:kwargs['clock']=clock
    if sleep is not None:kwargs['sleep']=sleep
    return release_approval.stage_and_wait(connect,sha,summary,owner_id,notify,execute,**kwargs)
