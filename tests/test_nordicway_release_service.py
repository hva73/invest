import json
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

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


if __name__ == '__main__': unittest.main()
