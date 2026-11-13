"""Read-only observation of a concurrent restricted SSH guard; redacted output."""
import hashlib, json, os, re, subprocess, sys, time
from pathlib import Path

ROOT=Path('/home/nordicr4')
REPO=ROOT/'escape_deploy/invest'
BRIDGE=ROOT/'.escape_deploy_bridge'
OLD='c1b6db6ca1ded2f3a81601608bdfa455145798f2'
GUARD=BRIDGE/'nordicway_deploy_guard.py'

def same_old_code():
    for name in ('nordicway_deploy_guard.py','nordicway_deploy_runner.py'):
        path=BRIDGE/name
        if path.is_symlink() or not path.is_file(): return False
        result=subprocess.run(['git','-c','core.hooksPath=/dev/null',
            '-c','core.fsmonitor=false','-C',str(REPO),'show',OLD+':tools/'+name],
            capture_output=True,timeout=15,check=False,
            env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_OPTIONAL_LOCKS':'0'})
        if result.returncode or not result.stdout or path.read_bytes()!=result.stdout: return False
    return True

def inspect(challenge):
    own=os.getuid(); matches=[]; unreadable=False
    pid_ns=os.readlink('/proc/self/ns/pid'); mount_ns=os.readlink('/proc/self/ns/mnt')
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit() or int(entry.name)==os.getpid(): continue
        try:
            status=(entry/'status').read_text()
            uid=re.search(r'^Uid:\s*(\d+)',status,re.MULTILINE)
            state=re.search(r'^State:\s*([A-Z])',status,re.MULTILINE)
            if not uid or not state: unreadable=True; continue
            if int(uid.group(1))!=own or state.group(1)=='Z': continue
            raw=(entry/'cmdline').read_bytes()
            if not raw: unreadable=True; continue
            if os.fsencode(str(GUARD)) not in raw.split(b'\0'): continue
            environment=(entry/'environ').read_bytes().split(b'\0')
            expected=b'SSH_ORIGINAL_COMMAND=escape-deploy-v1 deploy '+challenge.encode('ascii')
            matches.append((os.readlink(entry/'ns/pid')==pid_ns,
                            os.readlink(entry/'ns/mnt')==mount_ns,
                            environment.count(expected)==1))
        except FileNotFoundError:
            if entry.exists(): unreadable=True
        except OSError:
            unreadable=True
    return {'guard_found':len(matches)==1, 'guard_count':len(matches),
            'same_pid_namespace':len(matches)==1 and matches[0][0],
            'same_mount_namespace':len(matches)==1 and matches[0][1],
            'challenge_matches':len(matches)==1 and matches[0][2],
            'inspection_complete':not unreadable}

def state():
    gate=BRIDGE/'deploy-enabled'; build=ROOT/'escape_app/BUILD_COMMIT'
    approved=BRIDGE/'approved-sha'
    if approved.is_symlink() or not approved.is_file(): raise ValueError('approval_unavailable')
    return {'gate_enabled':not gate.is_symlink() and gate.is_file() and gate.read_bytes()==b'1\n',
            'recovery_present':os.path.lexists(BRIDGE/'deployment-incomplete.json'),
            'setup_present':os.path.lexists(BRIDGE/'first-release-setup-incomplete.json'),
            'ticket_present':os.path.lexists(BRIDGE/'approval-ticket.json'),
            'approved_hash':hashlib.sha256(approved.read_bytes()).digest(),
            'installed_old_release':not build.is_symlink() and build.is_file() and
                build.read_text().strip()=='483a4b55ce4381e42ffb828125c9bcc0807cc8ba'}

def main(challenge, wait_seconds=180, drain_seconds=150, pause=.25):
    if not re.fullmatch('[0-9a-f]{40}',challenge) or challenge=='0'*40:
        print(json.dumps({'status':'invalid_challenge'})); return 1
    if not same_old_code():
        print(json.dumps({'old_code_matches':False})); return 1
    before=state(); baseline=inspect(challenge)
    if (not before['gate_enabled'] or before['recovery_present'] or before['setup_present'] or before['ticket_present']
        or not before['installed_old_release'] or baseline['guard_count'] or not baseline['inspection_complete']):
        print(json.dumps({'status':'baseline_unavailable'})); return 1
    print(json.dumps({'status':'observation_ready'}),flush=True)
    deadline=time.monotonic()+wait_seconds; observed=None
    while time.monotonic()<deadline:
        observed=inspect(challenge)
        if not observed['inspection_complete'] or observed['guard_count']>1:
            print(json.dumps({'status':'observation_unavailable'})); return 1
        if observed['guard_found']: break
        time.sleep(pause)
    else:
        print(json.dumps({'status':'guard_not_observed'})); return 1
    if not observed['same_pid_namespace'] or not observed['same_mount_namespace'] or not observed['challenge_matches']:
        print(json.dumps({'status':'namespace_mismatch'})); return 1
    deadline=time.monotonic()+drain_seconds
    while time.monotonic()<deadline:
        after=inspect(challenge)
        if not after['inspection_complete'] or after['guard_count']>1:
            print(json.dumps({'status':'drain_unavailable'})); return 1
        if after['guard_count']==0: break
        if not after['same_pid_namespace'] or not after['same_mount_namespace'] or not after['challenge_matches']:
            print(json.dumps({'status':'namespace_mismatch'})); return 1
        time.sleep(pause)
    else:
        print(json.dumps({'status':'guard_still_present'})); return 1
    unchanged=before==state() and same_old_code()
    print(json.dumps({'status':'observed' if unchanged else 'state_changed',
        'old_code_matches':unchanged,'one_guard_seen':True,'same_uid':True,
        'same_pid_namespace':True,'same_mount_namespace':True,'challenge_matches':True,
        'guard_disappeared':True,'state_unchanged':unchanged},sort_keys=True))
    return 0 if unchanged else 1

if __name__=='__main__':
    try: raise SystemExit(main(sys.argv[1] if len(sys.argv)==2 else ''))
    except (OSError,subprocess.SubprocessError,ValueError):
        print(json.dumps({'status':'unavailable'})); raise SystemExit(1) from None
