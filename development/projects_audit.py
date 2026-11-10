#!/usr/bin/env python3
"""Audit one GitHub Project and optionally add one existing Issue without changing status."""
import argparse
import json
import subprocess
import sys

OWNER = 'hva73'
REPO = 'hva73/invest'
TITLE = 'ESCAPE Development'
ITEMS = '''query($id:ID!,$cursor:String){node(id:$id){... on ProjectV2{
 items(first:100,after:$cursor,archivedStates:[ARCHIVED,NOT_ARCHIVED]){pageInfo{hasNextPage endCursor} nodes{id isArchived
 content{... on Issue{number url repository{nameWithOwner}}}
 fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}
 }}}}}'''
ISSUE = '''query($number:Int!){repository(owner:"hva73",name:"invest"){
 issue(number:$number){id url}}}'''
ADD = '''mutation($project:ID!,$content:ID!){addProjectV2ItemById(
 input:{projectId:$project,contentId:$content}){item{id}}}'''


def gh(*args):
    result = subprocess.run(['gh', *args], capture_output=True, text=True, check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or 'gh command failed')
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError('GitHub returned invalid JSON') from exc
    if isinstance(data, dict) and data.get('errors'):
        raise RuntimeError('GraphQL returned errors: ' + str(data['errors']))
    return data


def graphql(query, *variables):
    return gh('api', 'graphql', '-f', 'query=' + query, *variables)['data']


def project():
    projects = gh('project', 'list', '--owner', OWNER, '--format', 'json', '--limit', '1000')['projects']
    if len(projects) >= 1000:
        raise RuntimeError('Project listing may be incomplete; refusing to choose a project')
    matches = [p for p in projects if p.get('title') == TITLE and not p.get('closed')]
    if len(matches) != 1:
        raise RuntimeError(f'Expected exactly one open {TITLE!r} project, found {len(matches)}')
    detail = gh('project', 'view', str(matches[0]['number']), '--owner', OWNER, '--format', 'json')
    if detail.get('title') != TITLE or not detail.get('id'):
        raise RuntimeError('Project identity cannot be verified')
    return detail


def items(project_id):
    cursor = None
    found = []
    seen = set()
    while True:
        variables = ['-f', 'id=' + project_id]
        if cursor:
            variables += ['-f', 'cursor=' + cursor]
        data = graphql(ITEMS, *variables)
        node = data.get('node')
        if not node or not isinstance(node.get('items'), dict):
            raise RuntimeError('Project items unavailable or access denied')
        page = node['items']
        found.extend(page['nodes'])
        info = page['pageInfo']
        if not info['hasNextPage']:
            return found
        cursor = info.get('endCursor')
        if not cursor or cursor in seen:
            raise RuntimeError('Project pagination incomplete')
        seen.add(cursor)


def matching(rows, number):
    return [row for row in rows if (row.get('content') or {}).get('number') == number
            and ((row.get('content') or {}).get('repository') or {}).get('nameWithOwner') == REPO]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--add-one', type=int, choices=range(3, 12), metavar='ISSUE',
                        help='explicitly add exactly one missing issue (3–11); does not set status')
    args = parser.parse_args()
    p = project()
    rows = items(p['id'])
    report = []
    for number in range(3, 12):
        matches = matching(rows, number)
        report.append({'issue': number, 'matches': len(matches), 'items': [
            {'id': row['id'], 'archived': row.get('isArchived'),
             'status': (row.get('fieldValueByName') or {}).get('name')} for row in matches]})
    print(json.dumps({'project': p['title'], 'number': p['number'], 'issues': report}, indent=2))
    if args.add_one is None:
        return
    # Re-read the complete project immediately before mutation; GitHub's add
    # operation is idempotent for an already-added issue. Never set status.
    if matching(items(p['id']), args.add_one):
        print('Already present (including archived); no changes made.')
        return
    issue = graphql(ISSUE, '-F', f'number={args.add_one}')['repository']['issue']
    if not issue or not issue.get('id'):
        raise RuntimeError('Issue is not accessible; no changes made')
    result = graphql(ADD, '-f', 'project=' + p['id'], '-f', 'content=' + issue['id'])
    item_id = result['addProjectV2ItemById']['item']['id']
    confirmed = matching(items(p['id']), args.add_one)
    if not any(item['id'] == item_id for item in confirmed):
        raise RuntimeError('Add returned but readback did not confirm membership')
    print('Added and verified one existing issue; no status field was edited.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, TypeError) as error:
        print('ERROR: ' + str(error), file=sys.stderr)
        sys.exit(1)
