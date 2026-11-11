"""Validate a fixed owner request; the server separately approves the SHA."""
import json
import os
import re
from pathlib import Path

OWNER = 351122234
BRANCH = 'refs/heads/codex/escape-development'
PREFIX = 'ESCAPE_DEPLOY_V1 '


def parse(event, event_name, ref, actor_id):
    if actor_id != str(OWNER) or ref != BRANCH or not isinstance(event, dict):
        return None
    if not isinstance(event.get('sender'), dict) or event['sender'].get('id') != OWNER:
        return None
    if event_name == 'workflow_dispatch':
        inputs = event.get('inputs')
        if not isinstance(inputs, dict):
            return None
        operation, sha = inputs.get('operation'), inputs.get('release_sha', '')
    elif event_name == 'issue_comment':
        issue, comment = event.get('issue'), event.get('comment')
        if (event.get('action') != 'created' or not isinstance(issue, dict)
                or issue.get('number') != 16 or 'pull_request' in issue
                or not isinstance(comment, dict) or not isinstance(comment.get('user'), dict)
                or comment['user'].get('id') != OWNER or comment.get('author_association') != 'OWNER'):
            return None
        body = comment.get('body')
        if not isinstance(body, str) or not body.startswith(PREFIX) or len(body) > 256:
            return None
        def unique(pairs):
            data = {}
            for key, value in pairs:
                if key in data:
                    raise ValueError('duplicate key')
                data[key] = value
            return data
        try:
            data = json.loads(body[len(PREFIX):], object_pairs_hook=unique)
        except (ValueError, TypeError):
            return None
        if not isinstance(data, dict) or set(data) != {'operation', 'sha'}:
            return None
        operation, sha = data['operation'], data['sha']
        if operation not in ('deploy', 'resume'):
            return None
    else:
        return None
    if event_name == 'workflow_dispatch' and operation == 'write-probe' and sha == '':
        return {'operation': operation, 'sha': ''}
    if operation in ('deploy', 'resume') and isinstance(sha, str) and re.fullmatch(r'[0-9a-f]{40}', sha):
        return {'operation': operation, 'sha': sha}
    return None


def main():
    try:
        raw = Path(os.environ['GITHUB_EVENT_PATH']).read_bytes()
        if len(raw) > 1048576:
            raise ValueError('oversized event')
        request = parse(json.loads(raw), os.environ.get('GITHUB_EVENT_NAME'),
                        os.environ.get('GITHUB_REF'), os.environ.get('GITHUB_ACTOR_ID'))
        if request is None:
            raise ValueError('invalid request')
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as output:
            output.write('operation=' + request['operation'] + '\nsha=' + request['sha'] + '\n')
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        raise SystemExit('Deployment request rejected.') from None
    print('Fixed deployment request accepted; server authorization remains required.')


if __name__ == '__main__':
    main()
