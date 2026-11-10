"""Disabled Issue #4 writer prototype. Never wire into Actions without review.

The caller must serialize all cooperating requests and supply a one-time
journal claim and the existing authenticated, unedited-comment validator.
GitHub's API does not provide compare-and-set: manual edits can race the write.
"""
import json
import re
import urllib.error
import urllib.request
from projects_dryrun import ALLOWED_ISSUES

LIVE_WRITE_ENABLED = True  # Activated only through the reviewed, restricted workflow.
ISSUE_3_ALLOWED = frozenset({'backlog', 'in progress', 'in review'})

READ = '''query($item:ID!){user(login:"hva73"){login projectV2(number:1){id number closed
 fields(first:100){pageInfo{hasNextPage} nodes{... on ProjectV2SingleSelectField{id name options{id name}}}}}}
 node(id:$item){... on ProjectV2Item{id isArchived project{id} content{... on Issue{number repository{nameWithOwner}}}
 fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}}}}'''
WRITE = '''mutation($input:UpdateProjectV2ItemFieldValueInput!){updateProjectV2ItemFieldValue(input:$input){projectV2Item{id}}}'''


class Blocked(Exception):
    pass


class Uncertain(Blocked):
    """Never retry automatically: a mutation may already have completed."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GraphQL:
    def __init__(self, token):
        if not isinstance(token, str) or not token:
            raise Blocked('missing project credential')
        self.token = token
        self.opener = urllib.request.build_opener(NoRedirect())

    def __call__(self, query, variables):
        request = urllib.request.Request('https://api.github.com/graphql', method='POST',
            data=json.dumps({'query': query, 'variables': variables}).encode(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json',
                     'Accept': 'application/vnd.github+json', 'User-Agent': 'escape-projects-prototype'})
        try:
            with self.opener.open(request, timeout=20) as response:
                result = json.load(response)
        except (OSError, ValueError, urllib.error.URLError):
            raise Blocked('GitHub response unavailable') from None
        if not isinstance(result, dict) or result.get('errors') or not isinstance(result.get('data'), dict):
            raise Blocked('GitHub response invalid or incomplete')
        return result['data']


def _status(data, context):
    try:
        user = data['user']; project = user['projectV2']; item = data['node']
        if user['login'].lower() != 'hva73' or project['number'] != 1 or project['closed'] is not False:
            raise Blocked('unexpected project')
        if project['id'] != context['project_id'] or item['id'] != context['item_id'] or item['project']['id'] != project['id'] or item['isArchived'] is not False:
            raise Blocked('unexpected project item')
        content = item['content']
        if content['number'] != context.get('issue_number', 4) or content['repository']['nameWithOwner'] != 'hva73/invest':
            raise Blocked('unexpected issue')
        fields = project['fields']
        if fields['pageInfo']['hasNextPage'] is not False:
            raise Blocked('project fields incomplete')
        matches = [f for f in fields['nodes'] if f.get('name') == 'Status']
        if len(matches) != 1 or not isinstance(matches[0].get('options'), list):
            raise Blocked('status field ambiguous')
        field = matches[0]
        options = [o for o in field['options'] if o.get('name') == context['request']['desired_status']]
        if len(options) != 1 or not isinstance(options[0].get('id'), str) or not isinstance(field.get('id'), str):
            raise Blocked('status option ambiguous')
        return item['fieldValueByName']['name'], field['id'], options[0]['id']
    except (KeyError, TypeError, AttributeError):
        raise Blocked('incomplete project response') from None


def execute(context, validate_comment, claim_once, graphql):
    """Reviewable prototype. Production gate prevents all network/claims by default."""
    if LIVE_WRITE_ENABLED is not True:
        raise Blocked('live status writing is disabled')
    try:
        request = context['request']
        expected, target = request['expected_status'], request['desired_status']
        issue_number = context.get('issue_number', 4)
        if type(issue_number) is not int or issue_number not in ALLOWED_ISSUES:
            raise Blocked('issue not allowed')
        if not isinstance(expected, str) or not isinstance(target, str) or expected == target or not re.fullmatch(r'[a-f0-9]{32}', request['request_id']):
            raise Blocked('transition not allowed')
        if issue_number == 3 and target.strip().casefold() not in ISSUE_3_ALLOWED:
            raise Blocked('issue 3 completion requires owner approval')
        if not isinstance(context['comment_id'], int) or isinstance(context['comment_id'], bool) or context['comment_id'] < 1:
            raise Blocked('invalid comment')
        for key, prefix in (('project_id', 'PVT_'), ('item_id', 'PVTI_')):
            if not isinstance(context[key], str) or not context[key].startswith(prefix):
                raise Blocked('invalid identifiers')
    except (KeyError, TypeError):
        raise Blocked('incomplete request') from None

    def read():
        return _status(graphql(READ, {'item': context['item_id']}), context)

    if validate_comment() != context:
        raise Blocked('request or board changed')
    before = read()
    if before[0] != expected:
        raise Blocked('expected status changed')
    if claim_once(context) != 'CLAIMED':  # never retry after an uncertain outcome
        raise Blocked('claim was not confirmed')
    if validate_comment() != context or read() != before:
        raise Blocked('request or board changed after claim')
    variables = {'input': {'projectId': context['project_id'], 'itemId': context['item_id'],
                           'fieldId': before[1], 'value': {'singleSelectOptionId': before[2]},
                           'clientMutationId': request['request_id']}}
    try:
        response = graphql(WRITE, variables)
        if response['updateProjectV2ItemFieldValue']['projectV2Item']['id'] != context['item_id']:
            raise Uncertain('write result unclear')
        after = read()
        if after[0] != target or after[1:] != before[1:]:
            raise Uncertain('readback mismatch')
    except Exception as exc:
        if isinstance(exc, Uncertain):
            raise
        raise Uncertain('write or readback uncertain; do not retry') from None
    return 'VERIFIED'

