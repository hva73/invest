import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
import nordicway_uapi_quota as q


def payload(used='8022.09', limit='10240', unit='MB', normalized=1):
    return {'result':{'status':1,'data':[{'id':'diskusage','_count':used,'_max':limit,'units':unit,'normalized':normalized}]}}


class QuotaTests(unittest.TestCase):
    def test_conservative_rounded_bounds(self):
        value = q.parse(payload())
        self.assertGreaterEqual(value['used_upper_bytes'], 8022.09 * 1048576)
        self.assertLess(value['limit_lower_bytes'], 10240 * 1000000)
        self.assertGreater(value['free_lower_bytes'], 0)

    def test_unknown_shapes_fail_closed(self):
        for p in (payload('NaN'), payload('12','unlimited'), payload('12','100','GB'),
                  payload('12','100','MB',0), {'status':0}, payload('120','100')):
            with self.subTest(p=p), self.assertRaisesRegex(ValueError, 'quota_unavailable'):
                q.parse(p)

    def test_https_response_and_filesystem_both_required(self):
        class Response(io.BytesIO):
            status = 200
            def __enter__(self): return self
            def __exit__(self, *args): self.close()
        opener = Mock(); opener.open.return_value = Response(json.dumps(payload()).encode())
        fs = Mock(return_value=SimpleNamespace(f_bavail=2_000_000_000, f_frsize=1))
        result = q.verify_space('/tmp', 1_000_000, 'a'*40, opener=opener, statvfs=fs)
        self.assertGreater(result['account_free_lower_bytes'], 1_000_000)
        self.assertNotIn('a'*40, str(result))
        opener.open.return_value = Response(json.dumps(payload()).encode())
        fs.return_value.f_bavail = 10
        with self.assertRaisesRegex(ValueError, 'insufficient_space'):
            q.verify_space('/tmp', 1_000_000, 'a'*40, opener=opener, statvfs=fs)

    def test_invalid_token_does_not_call_network(self):
        opener = Mock()
        with self.assertRaisesRegex(ValueError, 'quota_unavailable'):
            q.read('bad', opener)
        opener.open.assert_not_called()

    def test_rejects_duplicate_diskusage_rows(self):
        p = payload(); p['result']['data'].append(p['result']['data'][0])
        with self.assertRaisesRegex(ValueError, 'quota_unavailable'): q.parse(p)

if __name__ == '__main__': unittest.main()
