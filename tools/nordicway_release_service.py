"""Narrow CloudLinux service adapter; not exposed by the read-only guard.

Selector status is not proof of drained Passenger processes. The caller must
independently verify process quiescence before taking or restoring a snapshot.
"""
import json
import os
import subprocess

PROXY = '/bin/cagefs_enter.proxied'
SELECTOR = '/sbin/cloudlinux-selector'
APP_ROOT = 'escape_app'
STATES = {'started', 'stopped'}


def _invoke(operation, runner):
    args = [PROXY, SELECTOR, operation, '--json', '--interpreter', 'python']
    if operation != 'get':
        args += ['--app-root', APP_ROOT]
    # cagefs_enter.proxied may interpret SSH session metadata as its own
    # command context. The selector is a fixed local operation, so it must not
    # inherit the remote request or connection metadata.
    env = os.environ.copy()
    env.pop('SSH_ORIGINAL_COMMAND', None)
    env.pop('SSH_CONNECTION', None)
    try:
        result = runner(args, capture_output=True, text=True, timeout=30, check=False, env=env)
    except (OSError, subprocess.SubprocessError):
        raise ValueError('selector_exec_unavailable') from None
    if result.returncode != 0:
        raise ValueError('selector_exit_nonzero')
    if len(result.stdout) > 1_000_000:
        raise ValueError('selector_response_too_large')
    try:
        data = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise ValueError('selector_invalid_json') from None
    if not isinstance(data, dict) or data.get('result') != 'success':
        raise ValueError('selector_result_failed')
    return data


def _application_state(data):
    found = []
    def visit(node):
        if isinstance(node, dict):
            apps = node.get('applications')
            if isinstance(apps, dict):
                for key, value in apps.items():
                    if key in (APP_ROOT, '/home/nordicr4/' + APP_ROOT) and isinstance(value, dict):
                        found.append(value.get('app_status'))
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(data)
    if len(found) != 1 or found[0] not in STATES:
        raise ValueError('application_state_unknown')
    return found[0]


def status(runner=subprocess.run):
    return _application_state(_invoke('get', runner))


def transition(operation, runner=subprocess.run):
    if operation not in ('start', 'stop'):
        raise ValueError('invalid_operation')
    before = status(runner)
    desired = 'started' if operation == 'start' else 'stopped'
    if before == desired:
        return before
    _invoke(operation, runner)
    if status(runner) != desired:
        raise ValueError('selector_readback_failed')
    return desired
