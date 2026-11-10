#!/usr/bin/env python3
"""Read-only probe of writer's GraphQL query and item/field validation."""
import os
import sys

import projects_dryrun as dryrun
import projects_status_write_prototype as writer


def main():
    token = os.environ.get('ESCAPE_PROJECTS_TOKEN', '')
    if not token:
        raise writer.Blocked('missing credential')
    context = dryrun.main()
    graph = writer.GraphQL(token)
    current, _, _ = writer._status(graph(writer.READ, {'item': context['item_id']}), context)
    if current != context['request']['expected_status']:
        raise writer.Blocked('status changed')
    print('PASS: writerens GraphQL-læsequery og Status-felt er verificeret; ingen mutation.')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('BLOCKED: skriveprototypens read-only kontrol fejlede; ingen rå data udskrives.')
        sys.exit(1)
