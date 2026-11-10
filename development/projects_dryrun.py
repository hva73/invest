#!/usr/bin/env python3
"""Manual dry-run of an issue comment request; never changes GitHub state."""
import json
import os
import re
import sys
import urllib.request
import urllib.error

OWNER_ID = 351122234
PREFIX = 'ESCAPE_PROJECTS_DRYRUN_V1 '
QUERY = '''query($cursor:String){user(login:"hva73"){login projectV2(number:1){number closed
 fields(first:100){pageInfo{hasNextPage} nodes{... on ProjectV2SingleSelectField{name options{name}}}}
 items(first:100,after:$cursor){pageInfo{hasNextPage endCursor} nodes{isArchived
 content{... on Issue{number repository{nameWithOwner}}}
 fieldValueByName(name:"Status"){... on ProjectV2ItemFieldSingleSelectValue{name}}}}}}}'''


class Blocked(Exception):
    pass


def parse_request(body):
    if not isinstance(body, str) or not body.startswith(PREFIX):
        return None
    try:
        value = json.loads(body[len(PREFIX):], object_pairs_hook=unique_keys)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {'request_id', 'expected_status', 'desired_status'}:
        return None
    if not isinstance(value['request_id'], str) or not re.fullmatch(r'[a-f0-9]{32}', value['request_id']):
        return None
    if any(not isinstance(value[k], str) or not re.fullmatch(r'[A-Za-z0-9 _/-]{1,60}', value[k]) for k in ('expected_status', 'desired_status')):
        return None
    return value


def unique_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def validate_request(comments, comment_id, current_status, options):
    selected = [c for c in comments if c.get('id') == comment_id]
    if len(selected) != 1:
        raise Blocked('Anmodningen findes ikke entydigt på Issue #4.')
    comment = selected[0]
    if (comment.get('user') or {}).get('id') != OWNER_ID or comment.get('author_association') != 'OWNER':
        raise Blocked('Anmodningens afsender er ikke godkendt.')
    if not comment.get('created_at') or comment.get('updated_at') != comment.get('created_at'):
        raise Blocked('Redigerede anmodninger afvises.')
    request = parse_request(comment.get('body'))
    if request is None:
        raise Blocked('Anmodningen har ugyldigt format.')
    found = [parse_request(c.get('body')) for c in comments]
    if sum(bool(r and r['request_id'] == request['request_id']) for r in found) != 1:
        raise Blocked('Dubleret anmodnings-ID på Issue #4.')
    if request['expected_status'] != current_status:
        raise Blocked('Forventet status stemmer ikke med den aktuelle status.')
    if request['desired_status'] not in options or request['expected_status'] not in options:
        raise Blocked('Status er ikke en gyldig projektoption.')
    if request['desired_status'] == current_status:
        raise Blocked('Ønsket status er allerede aktuel.')
    return request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    if os.environ.get('GITHUB_ACTOR_ID') != str(OWNER_ID) or os.environ.get('GITHUB_TRIGGERING_ACTOR', '').lower() != 'hva73':
        raise Blocked('Workflowets afsender er ikke godkendt.')
    if os.environ.get('GITHUB_REPOSITORY') != 'hva73/invest' or os.environ.get('GITHUB_REF') != 'refs/heads/codex/escape-development':
        raise Blocked('Forkert repository eller branch.')
    raw_id = os.environ.get('REQUEST_COMMENT_ID', '')
    if not re.fullmatch(r'[1-9][0-9]{0,19}', raw_id):
        raise Blocked('Kommentar-ID mangler eller er ugyldigt.')
    token = os.environ.pop('ESCAPE_PROJECTS_TOKEN', '')
    if not token:
        raise Blocked('Projects-secret er ikke tilgængeligt.')
    opener = urllib.request.build_opener(NoRedirect())

    def get_json(url, payload=None, authenticated=False):
        headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'escape-projects-dryrun'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + token
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        with opener.open(req, timeout=20) as response:
            return json.load(response)

    def comments():
        result = []
        for page in range(1, 101):
            values = get_json(f'https://api.github.com/repos/hva73/invest/issues/4/comments?per_page=100&page={page}')
            if not isinstance(values, list):
                raise Blocked('Kommentarlisten kunne ikke læses komplet.')
            result.extend(values)
            if len(values) < 100:
                return result
        raise Blocked('Kommentarlisten overstiger sikker grænse.')

    first = comments()
    matches, cursor, seen, options = [], None, set(), None
    while True:
        result = get_json('https://api.github.com/graphql', {'query': QUERY, 'variables': {'cursor': cursor}}, True)
        if result.get('errors'):
            raise Blocked('GraphQL-opslaget fejlede eller var ufuldstændigt.')
        user = (result.get('data') or {}).get('user') or {}
        project = user.get('projectV2') or {}
        if user.get('login', '').lower() != 'hva73' or project.get('number') != 1 or project.get('closed') is not False:
            raise Blocked('Projektet kunne ikke verificeres.')
        fields = project['fields']
        if fields['pageInfo']['hasNextPage']:
            raise Blocked('Projektets felter er ikke fuldt indlæst.')
        statuses = [f for f in fields['nodes'] if f.get('name') == 'Status' and isinstance(f.get('options'), list)]
        if len(statuses) != 1:
            raise Blocked('Statusfeltet er ikke entydigt.')
        options = [o.get('name') for o in statuses[0]['options']]
        items = project['items']
        for item in items['nodes']:
            content = item.get('content') or {}
            if content.get('number') == 4 and (content.get('repository') or {}).get('nameWithOwner') == 'hva73/invest':
                matches.append(item)
        if not items['pageInfo']['hasNextPage']:
            break
        cursor = items['pageInfo'].get('endCursor')
        if not cursor or cursor in seen:
            raise Blocked('Projektlisten er ufuldstændig.')
        seen.add(cursor)
    if len(matches) != 1 or matches[0].get('isArchived') is not False:
        raise Blocked('Projektkortet er ikke entydigt og aktivt.')
    current = (matches[0].get('fieldValueByName') or {}).get('name')
    request = validate_request(first, int(raw_id), current, options)
    second = comments()
    if validate_request(second, int(raw_id), current, options) != request:
        raise Blocked('Anmodningen blev ændret under kontrollen.')
    print('DRY RUN: afsender, kort, statusoption og synlige dubletter kontrolleret.')
    print('Ingen status blev ændret. Replay mellem kørsler er IKKE beskyttet.')


if __name__ == '__main__':
    try:
        main()
    except Blocked as error:
        print('BLOCKED: ' + str(error))
        sys.exit(1)
    except Exception:
        print('BLOCKED: Opslag fejlede; ingen rå svardata er udskrevet.')
        sys.exit(1)
