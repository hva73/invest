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
        if not isinstance(body, str) or not body.startswith(PREFIX) or len(body) > 2048:
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
        if not isinstance(data, dict) or set(data) not in ({'operation', 'sha'}, {'operation', 'sha', 'approval'}, {'operation', 'sha', 'summary'}):
            return None
        operation, sha = data['operation'], data['sha']
        if operation not in ('deploy', 'resume', 'app-deploy'):
            return None
    else:
        return None
    if operation == 'app-deploy':
        if (event_name != 'issue_comment' or set(data) != {'operation','sha','summary'}
                or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha)
                or not isinstance(data['summary'],str) or not 1<=len(data['summary'].strip())<=500
                or '\n' in data['summary'] or '\r' in data['summary']):
            return None
        return {'operation':operation,'sha':sha,'summary':data['summary'].strip()}
    if operation == 'deploy':
        # A signed owner approval is supplied as a bounded public proof, never
        # as the underlying passphrase or key. Server verifies its MAC.
        if event_name != 'issue_comment' or set(data) != {'operation','sha','approval'}:
            return None
        proof = data['approval']
        if (not isinstance(proof, dict) or set(proof) != {'nonce','expires','mac'}
                or not isinstance(proof['nonce'], str) or not re.fullmatch(r'[0-9a-f]{32}', proof['nonce'])
                or type(proof['expires']) is not int or not 0 < proof['expires'] < 10**11
                or not isinstance(proof['mac'], str) or not re.fullmatch(r'[0-9a-f]{64}', proof['mac'])
                or not isinstance(sha,str) or not re.fullmatch(r'[0-9a-f]{40}',sha)):
            return None
        return {'operation': operation, 'sha': sha, 'approval': proof}
    if event_name == 'issue_comment' and set(data) != {'operation','sha'}:
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
            if 'approval' in request:
                output.write('approval=' + json.dumps(request['approval'], separators=(',', ':')) + '\n')
            if 'summary' in request:
                output.write('summary=' + request['summary'] + '\n')
    except (OSError, KeyError, ValueError, TypeError, AttributeError):
        raise SystemExit('Deployment request rejected.') from None
    print('Fixed deployment request accepted; server authorization remains required.')


if __name__ == '__main__':
    main()
