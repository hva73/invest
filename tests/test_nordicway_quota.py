import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_quota as q


def response(used=100, limit=1000, status=1):
    obj = {'cpanelresult': {'module':'DiskUsage', 'func':'fetchdiskusagewithextras',
           'event':{'result':status}, 'data':[{'quotaused':used, 'quotalimit':limit}]}}
    return SimpleNamespace(returncode=0, stdout=json.dumps(obj).encode())


class QuotaTests(unittest.TestCase):
    def test_account_and_filesystem_space_both_required(self):
        fs = Mock(return_value=SimpleNamespace(f_bavail=100, f_frsize=10))
        run = Mock(return_value=response())
        self.assertEqual(q.verify_space('/tmp', 500, run, fs)['account_free_bytes'], 900)
        with self.assertRaisesRegex(ValueError, 'insufficient_space'):
            q.verify_space('/tmp', 901, run, fs)
        fs.return_value.f_bavail = 20
        with self.assertRaisesRegex(ValueError, 'insufficient_space'):
            q.verify_space('/tmp', 500, run, fs)
        self.assertEqual(run.call_args.args[0], [
            '/usr/local/cpanel/bin/cpapi2', '--user=nordicr4', '--output=json',
            'DiskUsage', 'fetchdiskusagewithextras'])

    def test_unknown_or_failed_quota_fails_closed(self):
        for used, limit, status in ((100, None, 1), (100, 0, 1), (100, 1000, 0), (True, 1000, 1)):
            with self.assertRaisesRegex(ValueError, 'quota_unavailable'):
                q.read_quota(Mock(return_value=response(used, limit, status)))
        with self.assertRaisesRegex(ValueError, 'quota_unavailable'):
            q.read_quota(Mock(return_value=SimpleNamespace(returncode=1, stdout=b'')))

if __name__ == '__main__':
    unittest.main()
