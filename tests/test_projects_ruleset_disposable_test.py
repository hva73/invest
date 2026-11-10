import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_ruleset_disposable_test as test


class Response(io.BytesIO):
    status = 200
    def __init__(self, value): super().__init__(json.dumps(value).encode())


def rule(include):
    return {'id': test.RULESET, 'enforcement': 'active', 'conditions': {'ref_name': {'include': include, 'exclude': []}},
            'rules': [{'type': 'deletion'}, {'type': 'non_fast_forward'}], 'bypass_actors': [], 'current_user_can_bypass': 'never'}


class RuleTest(unittest.TestCase):
    def test_expected_rejections_and_readback(self):
        head = 'a' * 40
        methods = []
        values = iter([Response(rule([test.REF])), Response({'object': {'sha': head}}), Response({'parents': [{'sha': 'b' * 40}]}), Response({'object': {'sha': head}}), Response({'object': {'sha': head}})])
        def open_(req, timeout):
            methods.append(req.get_method())
            if req.get_method() in ('DELETE', 'PATCH'):
                self.assertIn(test.BRANCH, req.full_url)
                raise HTTPError(req.full_url, 422, '', {}, io.BytesIO(b'{"message":"GH013 repository rule violation"}'))
            return next(values)
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'hva73/invest', 'RULE_TEST_TOKEN': 'fake'}, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = open_
            test.main()
        self.assertEqual(methods, ['GET', 'GET', 'GET', 'DELETE', 'GET', 'PATCH', 'GET'])

    def test_uncovered_branch_stops_before_mutations(self):
        calls = []
        def open_(req, timeout):
            calls.append(req.get_method())
            return Response(rule(['refs/heads/codex/projects-replay-isolated-test']))
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'hva73/invest', 'RULE_TEST_TOKEN': 'fake'}, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = open_
            with self.assertRaises(test.Blocked): test.main()
        self.assertEqual(calls, ['GET'])

    def test_permission_failure_is_not_a_rule_pass(self):
        head = 'a' * 40
        values = iter([Response(rule([test.REF])), Response({'object': {'sha': head}}), Response({'parents': [{'sha': 'b' * 40}]})])
        def open_(req, timeout):
            if req.get_method() == 'DELETE':
                raise HTTPError(req.full_url, 403, '', {}, io.BytesIO(b'{"message":"Resource not accessible by integration"}'))
            return next(values)
        with patch.dict(os.environ, {'GITHUB_REPOSITORY': 'hva73/invest', 'RULE_TEST_TOKEN': 'fake'}, clear=True), patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = open_
            with self.assertRaises(test.Blocked): test.main()


if __name__ == '__main__': unittest.main()
