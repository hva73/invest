import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_maintenance_audit as audit
import nordicway_release_retention as retention


class MaintenanceAudit(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.rows = {
            retention.APP + '/var': [{'file':'escape.db','type':'file','size':'6516871168'}],
            retention.ROOT: [{'file':'20261124-120000-raw','type':'dir'},
                             {'file':'retained-20261123-120000-old.tar.gz','type':'file','size':500000000},
                             {'file':'unrelated','type':'file','size':1}],
            retention.ROOT + '/20261124-120000-raw': [{'file':'escape.db','type':'file','size':6000000000}],
            retention.APP + '/opdatering': [{'file':'.escape-release-known','type':'dir'},
                                             {'file':'unrelated','type':'dir'}],
        }
        self.quota = {'used_upper_bytes':7031949888,'limit_lower_bytes':20000000000,
                      'free_lower_bytes':12968050112}

    def uapi(self, op, params):
        self.calls.append(op)
        self.assertEqual(op, 'list_files')
        return self.rows[params['dir']]

    def test_only_read_operations_and_actual_reserve_deficit(self):
        report = audit.inspect(self.uapi, lambda:self.quota)
        self.assertEqual(report['raw_backups'], 1)
        self.assertEqual(report['compressed_backups'], 1)
        self.assertEqual(report['recognized_stages'], 1)
        self.assertEqual(report['raw_backup_database_bytes'], 6000000000)
        self.assertTrue(report['retention_attention'])
        self.assertLess(report['database_only_reserve_gap_bytes'], 0)
        self.assertFalse(report['reserve_is_full_deploy_preflight'])
        self.assertEqual(set(self.calls), {'list_files'})

    def test_duplicate_or_path_in_inventory_rejected(self):
        for name in ('escape.db','../unexpected'):
            self.rows[retention.APP + '/var'].append({'file':name})
            with self.assertRaisesRegex(ValueError,'invalid_inventory'):
                audit.inspect(self.uapi, lambda:self.quota)
            self.rows[retention.APP + '/var'].pop()

    def test_inconsistent_quota_rejected(self):
        self.quota['free_lower_bytes'] += 1
        with self.assertRaisesRegex(ValueError,'quota_unavailable'):
            audit.inspect(self.uapi, lambda:self.quota)

    def test_unknown_files_not_counted(self):
        self.rows[retention.ROOT] = [{'file':'unknown.tar.gz','type':'file','size':100}]
        report = audit.inspect(self.uapi, lambda:self.quota)
        self.assertEqual(report['compressed_backup_bytes'], 0)
        self.assertFalse(report['retention_attention'])

    def test_missing_database_backup_not_treated_as_safe(self):
        self.rows[retention.ROOT + '/20261124-120000-raw'] = []
        with self.assertRaisesRegex(ValueError,'invalid_backup_inventory'):
            audit.inspect(self.uapi, lambda:self.quota)


if __name__ == '__main__':
    unittest.main()
