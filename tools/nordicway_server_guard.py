"""Forced-command entry point for a separately provisioned read-only SSH key.

Install this and its two fixed modules in an owner-controlled directory only
after an independent host-key check and explicit approval. Never execute stdin.
"""
import json
import os
import re
import sys

PROTOCOL = 'escape-readonly-v1'
INSTALL_DIR = '/home/nordicr4/.escape_bridge'


def dispatch(command, diagnostics, preflight):
    if command == PROTOCOL + ' diagnostics':
        operation, report = 'diagnostics', diagnostics()
    else:
        match = re.fullmatch(PROTOCOL + r' preflight ([0-9a-f]{40})', command)
        if not match:
            raise ValueError('invalid_operation')
        operation, report = 'release_preflight', preflight(match.group(1))
    return {'protocol': PROTOCOL, 'operation': operation, 'report': report}


def main():
    # The forced command should invoke python3 -I -S with this absolute path.
    # Explicitly trust only the independently provisioned server-side modules.
    sys.path.insert(0, INSTALL_DIR)
    try:
        import nordicway_readonly_diagnostics as diagnostic
        import nordicway_release_preflight as release
        result = dispatch(os.environ.get('SSH_ORIGINAL_COMMAND', ''),
                          diagnostic.inspect,
                          lambda sha: release.inspect(release.CHECKOUT, release.TARGET, sha))
        print(json.dumps(result, sort_keys=True, separators=(',', ':')))
        return 0
    except Exception:
        print('{"status":"failed","reason":"guard_failed"}')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
