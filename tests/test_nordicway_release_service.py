import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_release_service as service


def response(state):
    return {'result': 'success', 'available_versions': {'3.11': {'users': {'nordicr4': {
        'applications': {'escape_app': {'app_status': state, 'env_vars': {'SECRET': 'private-value'}}}
    }}}}}


def result(data, code=0):
    return subprocess.CompletedProcess([], code, json.dumps(data), '')


class Service(unittest.TestCase):
    def test_exact_application_and_fixed_commands(self):
        runner = Mock(side_effect=[result(response('started')), result({'result': 'success'}), result(response('stopped'))])
        self.assertEqual(service.transition('stop', runner), 'stopped')
        self.assertEqual(runner.call_args_list[1].args[0], [service.PROXY, service.SELECTOR, 'stop', '--json', '--interpreter', 'python', '--app-root', 'escape_app'])
        self.assertNotIn('private-value', str(runner.call_args_list))

    def test_ambiguous_missing_or_unexpected_status_fails_closed(self):
        duplicate = response('started')
        apps = duplicate['available_versions']['3.11']['users']['nordicr4']['applications']
        apps['/home/nordicr4/escape_app'] = {'app_status': 'started'}
        for payload in (duplicate, {'result': 'success'}, response('unknown')):
            with self.assertRaises(ValueError): service.status(Mock(return_value=result(payload)))

    def test_transition_requires_readback_and_rejects_free_commands(self):
        runner = Mock(side_effect=[result(response('started')), result({'result': 'success'}), result(response('started'))])
        with self.assertRaisesRegex(ValueError, 'selector_readback_failed'): service.transition('stop', runner)
        runner = Mock()
        with self.assertRaisesRegex(ValueError, 'invalid_operation'): service.transition('stop; id', runner)
        runner.assert_not_called()

    def test_noop_does_not_restart_or_stop_an_already_correct_state(self):
        runner = Mock(return_value=result(response('stopped')))
        self.assertEqual(service.transition('stop', runner), 'stopped')
        self.assertEqual(runner.call_count, 1)

    def test_selector_failure_categories_do_not_expose_output(self):
        cases = [
            (Mock(side_effect=OSError('secret path')), 'selector_exec_unavailable'),
            (Mock(return_value=subprocess.CompletedProcess([], 1, 'secret output', 'secret error')), 'selector_exit_nonzero'),
            (Mock(return_value=subprocess.CompletedProcess([], 0, 'secret output', '')), 'selector_invalid_json'),
            (Mock(return_value=result({'result': 'failure', 'secret': 'private-value'})), 'selector_result_failed'),
            (Mock(return_value=subprocess.CompletedProcess([], 0, 'x' * 1000001, '')), 'selector_response_too_large'),
        ]
        for runner, category in cases:
            with self.subTest(category=category):
                with self.assertRaises(ValueError) as error:
                    service.status(runner)
                self.assertEqual(str(error.exception), category)

    def test_selector_does_not_inherit_ssh_request_metadata(self):
        def invoke(args, **kwargs):
            env = kwargs['env']
            self.assertNotIn('SSH_ORIGINAL_COMMAND', env)
            self.assertNotIn('SSH_CONNECTION', env)
            self.assertEqual(env['ESCAPE_TEST_PRESERVED'], 'yes')
            return result(response('started'))
        with patch.dict(os.environ, {'SSH_ORIGINAL_COMMAND': 'escape-deploy-v1 deploy ' + 'a' * 40,
                                     'SSH_CONNECTION': '127.0.0.1 12345 127.0.0.1 33',
                                     'ESCAPE_TEST_PRESERVED': 'yes'}):
            self.assertEqual(service.status(invoke), 'started')
            self.assertIn('SSH_ORIGINAL_COMMAND', os.environ)
            self.assertIn('SSH_CONNECTION', os.environ)


if __name__ == '__main__': unittest.main()
