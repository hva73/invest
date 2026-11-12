"""Connect owner approval in the installed app to the existing deploy runner.

This module is not an SSH entry point by itself. It must be installed behind
the restricted deploy guard before a workflow can invoke it.
"""
import os
import json
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


def run_request(sha, stream, connect, bridge, *, runner, create_proof, notify,
                lifetime=600, clock=None, sleep=None):
    """Read the fixed payload over SSH stdin; never log the token or payload."""
    raw=stream.read(4097)
    if not isinstance(raw,bytes) or len(raw)>4096:
        raise ValueError('invalid_request')
    def unique(pairs):
        out={}
        for key,value in pairs:
            if key in out:raise ValueError('duplicate_key')
            out[key]=value
        return out
    try:
        payload=json.loads(raw,object_pairs_hook=unique)
    except (ValueError,UnicodeError):
        raise ValueError('invalid_request') from None
    if not isinstance(payload,dict) or set(payload)!={'cpanel_token','summary'}:
        raise ValueError('invalid_request')
    result=run(connect,sha,payload['summary'],payload['cpanel_token'],bridge,
               runner=runner,create_proof=create_proof,notify=notify,
               lifetime=lifetime,clock=clock,sleep=sleep)
    return {'operation':'app-deploy','status':result['status'],'sha':sha}


def resume_app(connect, sha, *, resume):
    """Reconcile app status only after the existing runner verifies recovery."""
    result = resume(sha)
    if (not isinstance(result, dict) or result.get('operation') != 'resume'
            or result.get('status') != 'ok' or result.get('recovery_required') is not False):
        return {'operation':'resume','status':'failed','recovery_required':True,'backup_cleanup':'not_run'}
    try:
        release_approval.reconcile_recovery(connect, sha, result)
    except Exception:
        return {'operation':'resume','status':'failed','recovery_required':True,'backup_cleanup':'not_run'}
    return result
