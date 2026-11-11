import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
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

    def test_rejects_duplicate_diskusage_rows(self):
        p = payload(); p['result']['data'].append(p['result']['data'][0])
        with self.assertRaisesRegex(ValueError, 'quota_unavailable'): q.parse(p)

if __name__ == '__main__': unittest.main()
