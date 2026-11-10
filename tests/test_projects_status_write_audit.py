import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'development'))
import projects_status_write_audit as audit


class Response(io.BytesIO):
    def __init__(self, data, status=200):
        super().__init__(json.dumps(data).encode())
        self.status = status


class AuditTest(unittest.TestCase):
    def test_fixed_result_is_recorded_without_secret(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [Response([]), Response({}, 201)]
            self.assertEqual(audit.post('secret-credential', 'a' * 32, 'uncertain', '123'), 'RECORDED')
            req = factory.return_value.open.call_args.args[0]
            self.assertNotIn('secret-credential', req.data.decode())
            self.assertIn('Udfaldet er usikkert', json.loads(req.data)['body'])

    def test_duplicate_bot_audit_is_not_posted_again(self):
        marker = '<!-- escape-project-status:' + 'a' * 32 + ':verified -->'
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.return_value = Response([{'user': {'id': 41898282}, 'body': marker}])
            self.assertEqual(audit.post('fake', 'a' * 32, 'verified', '123'), 'RECORDED')
            self.assertEqual(factory.return_value.open.call_count, 1)

    def test_failure_is_uncertain_and_not_retried(self):
        with patch('urllib.request.build_opener') as factory:
            factory.return_value.open.side_effect = [Response([]), OSError('network')]
            with self.assertRaises(audit.AuditFailed): audit.post('fake', 'a' * 32, 'verified', '123')
            self.assertEqual(factory.return_value.open.call_count, 2)


if __name__ == '__main__': unittest.main()
