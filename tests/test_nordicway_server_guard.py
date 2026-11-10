import sys
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_server_guard as guard


class ServerGuard(unittest.TestCase):
    def test_only_two_fixed_operations(self):
        diagnostic = Mock(return_value={'scope': 'read_only_aggregate'})
        preflight = Mock(return_value={'status': 'blocked'})
        result = guard.dispatch('escape-readonly-v1 diagnostics', diagnostic, preflight)
        self.assertEqual(result['operation'], 'diagnostics')
        self.assertEqual(result['protocol'], guard.PROTOCOL)
        preflight.assert_not_called()
        result = guard.dispatch('escape-readonly-v1 preflight ' + 'a' * 40, diagnostic, preflight)
        self.assertEqual(result['report']['status'], 'blocked')
        preflight.assert_called_once_with('a' * 40)

    def test_shell_commands_and_malformed_sha_are_rejected_without_side_effects(self):
        for command in ('', 'python3 -', 'escape-readonly-v1 diagnostics; id',
                        'escape-readonly-v1 diagnostics\nid',
                        'escape-readonly-v1 preflight ' + 'a' * 40 + '; id',
                        'escape-readonly-v1 preflight $(id)',
                        'escape-readonly-v1 preflight ' + 'A' * 40):
            diagnostic, preflight = Mock(), Mock()
            with self.assertRaises(ValueError):
                guard.dispatch(command, diagnostic, preflight)
            diagnostic.assert_not_called()
            preflight.assert_not_called()


if __name__ == '__main__':
    unittest.main()
