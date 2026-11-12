"""Version-bound release approval records, independent of deployment execution.

The caller must authenticate the administrator before calling approve.  A
record alone neither starts deployment nor changes the server bridge.
"""
import re
import secrets
import time

SHA = re.compile(r'^[0-9a-f]{40}$')


def init(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS release_approvals (
        id TEXT PRIMARY KEY, sha TEXT NOT NULL, summary TEXT NOT NULL,
        owner_id INTEGER NOT NULL, created REAL NOT NULL, expires REAL NOT NULL,
        status TEXT NOT NULL, approved_at REAL)''')


def prepare(connect, sha, summary, owner_id, *, now=None, lifetime=3600):
    now = time.time() if now is None else now
    if (not isinstance(sha, str) or not SHA.fullmatch(sha) or
        not isinstance(summary, str) or not 1 <= len(summary.strip()) <= 2000 or
        type(owner_id) is not int or owner_id <= 0 or
        type(lifetime) is not int or not 1 <= lifetime <= 86400):
        raise ValueError('invalid_candidate')
    candidate_id = secrets.token_hex(16)
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT 1 FROM release_approvals WHERE status IN ('claimed','recovery') LIMIT 1").fetchone():
            raise ValueError('release_in_progress')
        c.execute("UPDATE release_approvals SET status='superseded' WHERE status IN ('pending','approved')")
        c.execute('INSERT INTO release_approvals VALUES(?,?,?,?,?,?,?,NULL)',
                  (candidate_id, sha, summary.strip(), owner_id, now, now + lifetime, 'pending'))
    return {'id': candidate_id, 'sha': sha, 'summary': summary.strip(), 'expires': now + lifetime}


def approve(connect, candidate_id, sha, user_id, *, now=None):
    now = time.time() if now is None else now
    if not isinstance(candidate_id, str) or not re.fullmatch(r'[0-9a-f]{32}', candidate_id):
        raise ValueError('invalid_candidate')
    if not isinstance(sha, str) or not SHA.fullmatch(sha) or type(user_id) is not int:
        raise ValueError('invalid_candidate')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        changed = c.execute("""UPDATE release_approvals SET status='approved', approved_at=?
            WHERE id=? AND sha=? AND owner_id=? AND status='pending' AND expires>?""",
            (now, candidate_id, sha, user_id, now)).rowcount
        if changed != 1:
            raise ValueError('approval_unavailable')
    return {'id': candidate_id, 'sha': sha, 'status': 'approved'}


def pending(connect, owner_id, *, now=None):
    now = time.time() if now is None else now
    with connect() as c:
        row = c.execute("""SELECT id,sha,summary,expires FROM release_approvals
            WHERE owner_id=? AND status='pending' AND expires>? ORDER BY created DESC LIMIT 1""",
            (owner_id, now)).fetchone()
    if row is None:
        return None
    return dict(zip(('id', 'sha', 'summary', 'expires'), row))



def current(connect, owner_id, *, now=None):
    """Owner-scoped latest candidate and durable observed installation state."""
    now = time.time() if now is None else now
    with connect() as c:
        row = c.execute("""SELECT id,sha,summary,expires,status FROM release_approvals
            WHERE owner_id=? ORDER BY created DESC, rowid DESC LIMIT 1""", (owner_id,)).fetchone()
    if row is None:
        return None
    result = dict(zip(('id', 'sha', 'summary', 'expires', 'status'), row))
    if result['status'] in ('pending', 'approved') and result['expires'] <= now:
        result['status'] = 'expired'
    return result


def claim(connect, candidate_id, sha, *, now=None):
    """Claim a single approved, current candidate before starting installation.

    A claimed record is deliberately not retried automatically after a crash;
    the existing deploy recovery process must resolve any uncertain outcome.
    """
    now = time.time() if now is None else now
    if (not isinstance(candidate_id, str) or not re.fullmatch(r'[0-9a-f]{32}', candidate_id)
            or not isinstance(sha, str) or not SHA.fullmatch(sha)):
        raise ValueError('invalid_candidate')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        changed = c.execute("""UPDATE release_approvals SET status='claimed'
            WHERE id=? AND sha=? AND status='approved' AND expires>?""",
            (candidate_id, sha, now)).rowcount
        if changed != 1:
            raise ValueError('approval_unavailable')
    return {'id': candidate_id, 'sha': sha, 'status': 'claimed'}


def finish(connect, candidate_id, sha, *, verified):
    """Record a verified deployment or retain an uncertain outcome for recovery."""
    if type(verified) is not bool:
        raise ValueError('invalid_result')
    status = 'completed' if verified else 'recovery'
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        changed = c.execute("UPDATE release_approvals SET status=? WHERE id=? AND sha=? AND status='claimed'",
                            (status, candidate_id, sha)).rowcount
        if changed != 1:
            raise ValueError('approval_unavailable')
    return {'id': candidate_id, 'sha': sha, 'status': status}


def reconcile_recovery(connect, sha, result):
    """Clear an app claim only after the existing runner verifies resumption.

    This is a server-side bridge function, not an HTTP endpoint. A failed or
    uncertain resume leaves the previous claim blocked for operator review.
    """
    if (not isinstance(sha, str) or not SHA.fullmatch(sha)
            or not isinstance(result, dict) or result.get('operation') != 'resume'
            or result.get('status') != 'ok' or result.get('recovery_required') is not False):
        raise ValueError('recovery_unverified')
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        rows = c.execute("SELECT id FROM release_approvals WHERE sha=? AND status IN ('claimed','recovery')", (sha,)).fetchall()
        if len(rows) != 1:
            raise ValueError('recovery_unavailable')
        changed = c.execute("UPDATE release_approvals SET status='completed' WHERE id=? AND sha=? AND status IN ('claimed','recovery')", (rows[0][0], sha)).rowcount
        if changed != 1:
            raise ValueError('recovery_unavailable')
    return {'id': rows[0][0], 'sha': sha, 'status': 'completed'}


def start_approved(connect, candidate_id, sha, deploy, *, now=None):
    """Claim once before invoking a supplied deployment runner.

    This function does not locate credentials or start a runner itself. A
    transport loss or incomplete response is left in recovery, not retried.
    """
    claim(connect, candidate_id, sha, now=now)
    try:
        result = deploy(sha)
        verified = (isinstance(result, dict) and result.get('operation') == 'deploy'
                    and result.get('status') == 'ok' and result.get('stage') == 'complete'
                    and result.get('recovery_required') is False
                    and result.get('service_restored') is True)
        # The existing runner identifies failures before service stop, with no
        # mutation and no recovery marker. They may be retried after correction.
        no_mutation = (isinstance(result, dict) and result.get('operation') == 'deploy'
                       and result.get('status') == 'failed'
                       and result.get('stage') in ('authorization', 'preflight', 'quota', 'stage', 'service_state')
                       and result.get('recovery_required') is False)
    except Exception:
        verified = False
        no_mutation = False
    if no_mutation:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            changed = c.execute("UPDATE release_approvals SET status='failed' WHERE id=? AND sha=? AND status='claimed'",
                                (candidate_id, sha)).rowcount
            if changed != 1:
                raise ValueError('approval_unavailable')
        return {'id': candidate_id, 'sha': sha, 'status': 'failed'}
    return finish(connect, candidate_id, sha, verified=verified)


def stage_and_wait(connect, sha, summary, owner_id, notify, deploy, *,
                   lifetime=600, clock=time.time, sleep=time.sleep, poll_seconds=2):
    """Stage a candidate, notify the owner and run only after their approval.

    The calling transport owns the runner and credentials.  Notification
    failure is nonfatal: the owner can still use the administrator entry.
    """
    candidate = prepare(connect, sha, summary, owner_id, now=clock(), lifetime=lifetime)
    try:
        notify(owner_id)
    except Exception:
        pass
    while clock() < candidate['expires']:
        with connect() as c:
            row = c.execute('SELECT status FROM release_approvals WHERE id=? AND sha=?',
                            (candidate['id'], sha)).fetchone()
        if not row or row[0] != 'pending':
            if row and row[0] == 'approved':
                return start_approved(connect, candidate['id'], sha, deploy, now=clock())
            return {'id':candidate['id'], 'sha':sha, 'status':'unavailable'}
        sleep(poll_seconds)
    return {'id':candidate['id'], 'sha':sha, 'status':'expired'}
