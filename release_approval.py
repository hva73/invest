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
        if c.execute("SELECT 1 FROM release_approvals WHERE status='claimed' LIMIT 1").fetchone():
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
