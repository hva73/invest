"""Hold a deliberately incomplete request on the restricted SSH identity.

Requires verified host key and an already-loaded SSH agent. Does not send a
valid JSON request or a token. The owner can observe the remote guard while
this process keeps the SSH stdin pipe open; EOF causes JSON rejection.
"""
import os
import re
import subprocess
import tempfile
import time
from pathlib import Path

from nordicway_hostkey import verify


def hold(env=None, timeout=120, popen=subprocess.Popen):
    env = os.environ if env is None else env
    if env.get('NORDICWAY_DEPLOY_PING_AUTHORIZED') != '1' or not env.get('SSH_AUTH_SOCK'):
        raise ValueError('restricted_identity_unavailable')
    challenge=env.get('ESCAPE_OBSERVE_CHALLENGE','')
    if not re.fullmatch('[0-9a-f]{40}',challenge) or challenge=='0'*40:
        raise ValueError('invalid_observation_challenge')
    known = verify(env.get('NORDICWAY_KNOWN_HOST', ''), env.get('NORDICWAY_VERIFIED_FINGERPRINT', ''))
    with tempfile.TemporaryDirectory(prefix='escape-observe-hostkey-') as tmp:
        hosts = Path(tmp) / 'known_hosts'
        hosts.write_text(known, encoding='ascii'); hosts.chmod(0o600)
        cmd = ['ssh', '-F', '/dev/null', '-T', '-p', '33', '-o', 'BatchMode=yes',
               '-o', 'PasswordAuthentication=no', '-o', 'KbdInteractiveAuthentication=no',
               '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(hosts),
               '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'ForwardAgent=no',
               '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=10',
               'nordicr4@cp14.nordicway.dk',
               'escape-deploy-v1 deploy '+challenge]
        process = popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL, env=env)
        try:
            process.stdin.write(b'{'); process.stdin.flush()
            print('Observation window opened; remote guard is not yet confirmed.', flush=True)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise ValueError('ssh_ended_before_observation')
                time.sleep(min(1, max(0, deadline-time.monotonic())))
            process.stdin.close()
            code = process.wait(timeout=10)
            if code == 0:
                raise ValueError('unexpected_success')
            print('Connection ended after incomplete input; remote result not verified.', flush=True)
        finally:
            if process.poll() is None:
                process.kill(); process.wait(timeout=10)


if __name__ == '__main__':
    try:
        hold()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print('Observation stopped: ' + (str(exc) if isinstance(exc, ValueError) else 'transport_failed'))
        raise SystemExit(1) from None
