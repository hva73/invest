from contextlib import nullcontext
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch, MagicMock, mock_open
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import nordicway_release_retention as r

NAME = '20261114-200001-new'
SHA = 'a' * 40
START = 1794686400  # 2026-11-14 20:00:00 UTC

class Files:
    def __init__(self, corrupt=False, race=False):
        db = b'SQLite format 3\x00' + b'x' * 2048
        digest = lambda b: hashlib.sha256(b).hexdigest()
        manifest = {'format': 1, 'database_sha256': digest(db),
                    'files': {'BUILD_COMMIT': digest(b'b' * 40)}, 'keys': {'token.key': digest(b'private')}}
        self.manifest = json.dumps(manifest)
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w:gz') as t:
            for n, b in {'escape.db': db if not corrupt else b'y' * len(db), 'manifest.json': self.manifest.encode(),
                         'code/BUILD_COMMIT': b'b' * 40, 'token.key': b'private'}.items():
                info = tarfile.TarInfo(NAME + '/' + n); info.size = len(b); t.addfile(info, io.BytesIO(b))
        self.archive = stream.getvalue()
        # Production archives are >1KB; pad gzip trailing bytes without changing tar.
        self.archive += b'\x00' * 1200
        self.deleted = []; self.downloads = 0; self.race = race
        self.compressions = 0
        row = lambda n, typ, size=0, mtime=START-100: {'file': n, 'type': typ, 'size': str(size), 'mtime': mtime, 'mode': 0}
        self.rows = {
            r.ROOT: [row(NAME, 'dir'), row('retained-20261113-200001-old.tar.gz', 'file', 100), row('unrelated', 'file')],
            r.ROOT + '/' + NAME: [row('escape.db', 'file', len(db)), row('manifest.json', 'file', len(self.manifest)),
                                  row('code', 'dir'), row('token.key', 'file', 7)],
            r.ROOT + '/' + NAME + '/code': [row('BUILD_COMMIT', 'file', 40)],
            r.APP + '/opdatering': [row('.escape-release-old', 'dir'), row('.escape-release-new', 'dir', mtime=START+1),
                                    row('.escape-release-future', 'dir', mtime=START+100), row('var', 'dir')]}
    def uapi(self, operation, params):
        if operation == 'list_files': return list(self.rows[params['dir']])
        if operation == 'get_file_content':
            if params['file'] == 'manifest.json': return {'content': self.manifest}
            return {'content': ('c' * 40 if self.race and self.downloads and params['dir'] == r.APP
                                else SHA if params['dir'] in (r.APP, r.APP + '/opdatering/.escape-release-new') else 'b' * 40)}
        if operation == 'delete_file':
            path = params['path']; self.deleted.append(path)
            parent, name = path.rsplit('/', 1)
            self.rows[parent] = [x for x in self.rows[parent] if x['file'] != name]
            return None
        raise AssertionError(operation)
    def request(self, path, params):
        self.compressions += 1
        self.add_archive()
        return {'cpanelresult': {'event': {'result': 1}}}
    def add_archive(self):
        self.rows[r.ROOT].append({'file': 'retained-' + NAME + '.tar.gz', 'type': 'file', 'size': len(self.archive), 'mtime': START, 'mode': 0})
    def download(self, name, path, size):
        self.downloads += 1; Path(path).write_bytes(self.archive)
    def api(self): return self.uapi, self.request, self.download

def capacity(free, limit=10_000_000_000):
    return {'used_upper_bytes': limit - free, 'limit_lower_bytes': limit, 'free_lower_bytes': free}


class Retention(unittest.TestCase):
    def setUp(self):
        self.quota_read = MagicMock(return_value=capacity(8_000_000_000))
        self.bounds = (928_000_000_000, 0)

    def maintain(self, api):
        return r.maintain(api, SHA, START, quota_reader=self.quota_read,
                          maintenance_guard=nullcontext(self.bounds))

    def assert_deferred(self, files, category):
        result = self.maintain(files.api())
        self.assertEqual(result, {'status': 'maintenance_deferred', 'category': category})
        self.assertEqual((files.compressions, files.downloads, files.deleted), (0, 0, []))

    def test_post_success_entrypoint_defers_before_opening_transport(self):
        environment = {'ESCAPE_DEPLOY_RESULT_FILE': 'synthetic-result.json',
                       'ESCAPE_RELEASE_SHA': SHA, 'ESCAPE_RELEASE_STARTED_AT': str(START)}
        result = json.dumps({'status': 'ok', 'operation': 'app-deploy', 'sha': SHA})
        with patch.object(r.os, 'environ', environment), \
             patch('builtins.open', mock_open(read_data=result)), \
             patch.object(r, 'datetime') as clock, \
             patch.object(r, 'transport_api') as transport:
            clock.now.return_value.timestamp.return_value = START + 1
            r.main()
        transport.assert_not_called()

    def test_missing_writer_exclusion_defers_even_for_existing_archive(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                files = Files()
                if existing:
                    files.add_archive()
                before = list(files.rows[r.ROOT])
                result = r.maintain(files.api(), SHA, START, quota_reader=self.quota_read)
                self.assertEqual(result, {'status': 'maintenance_deferred',
                                          'category': 'maintenance_guard_unavailable'})
                self.assertEqual(files.rows[r.ROOT], before)
                self.assertEqual((files.compressions, files.downloads, files.deleted), (0, 0, []))
        self.quota_read.assert_not_called()

    def test_unknown_host_or_compression_scratch_defers(self):
        for bounds in ((None, 0), (928_000_000_000, None)):
            with self.subTest(bounds=bounds):
                self.bounds = bounds
                self.assert_deferred(Files(), 'archive_host_bound_unavailable')
        self.quota_read.assert_not_called()

    def test_20gb_cap_with_large_raw_backup_and_scratch(self):
        files = Files()
        files.rows[r.ROOT + '/' + NAME][0]['size'] = '6836097024'
        self.quota_read.return_value = capacity(20_000_000_000 - 7_826_571_264, 20_000_000_000)
        self.bounds = (928_000_000_000, 6_836_097_024)
        before = list(files.rows[r.ROOT])
        self.assert_deferred(files, 'archive_reserve_insufficient')
        self.assertEqual(files.rows[r.ROOT], before)

    def test_host_and_account_must_each_cover_peak_archive_and_scratch(self):
        required = 4096 + 7 * 65536
        required += (required + 7) // 8 + 65536 + r.ARCHIVE_HEADROOM + 4096
        self.bounds = (required - 1, 4096)
        self.quota_read.return_value = capacity(required, r.ACCOUNT_BUDGET)
        self.assert_deferred(Files(), 'archive_reserve_insufficient')
        self.bounds = (required, 4096)
        self.quota_read.return_value = capacity(required - 1, r.ACCOUNT_BUDGET)
        self.assert_deferred(Files(), 'archive_reserve_insufficient')
        self.quota_read.return_value = capacity(required, r.ACCOUNT_BUDGET)
        files = Files()
        self.assertEqual(self.maintain(files.api())['verified_files'], 4)
        self.assertEqual(files.compressions, 1)

    def test_unknown_quota_defers_without_changes(self):
        self.quota_read.side_effect = OSError('unavailable')
        self.assert_deferred(Files(), 'quota_unavailable')

    def test_reserve_includes_all_members_overhead_and_headroom(self):
        # Four files, one code directory, the root and end records.
        tar_upper = 4096 + 7 * 65536
        required = tar_upper + (tar_upper + 7) // 8 + 65536 + r.ARCHIVE_HEADROOM
        for free in (required - 1, required - r.ARCHIVE_HEADROOM):
            self.quota_read.return_value = capacity(free)
            self.assert_deferred(Files(), 'archive_reserve_insufficient')
        self.quota_read.return_value = capacity(required)
        files = Files()
        self.assertEqual(self.maintain(files.api())['verified_files'], 4)
        self.assertEqual(files.compressions, 1)

    def test_owner_budget_caps_reported_free_space(self):
        self.quota_read.return_value = capacity(4_000_000_000, 24_000_000_000)
        self.assert_deferred(Files(), 'archive_reserve_insufficient')

    def test_changed_quota_defers_without_changes(self):
        self.quota_read.side_effect = [capacity(8_000_000_000), capacity(7_999_999_999)]
        self.assert_deferred(Files(), 'archive_quota_changed')

    def test_unexpected_missing_and_unknown_metadata_defer(self):
        for change in ('unexpected', 'missing', 'unknown', 'duplicate', 'symlink'):
            with self.subTest(change=change):
                files = Files()
                rows = files.rows[r.ROOT + '/' + NAME + '/code']
                if change == 'unexpected':
                    rows.append(dict(rows[0], file='.extra'))
                elif change == 'missing':
                    rows.clear()
                elif change == 'unknown':
                    rows[0]['size'] = None
                elif change == 'duplicate':
                    rows.append(dict(rows[0]))
                else:
                    rows[0]['type'] = 'link'
                category = 'invalid_inventory' if change == 'duplicate' else 'invalid_backup_inventory'
                self.assert_deferred(files, category)

    def test_nested_inventory_change_during_final_quota_read_defers(self):
        files = Files()
        def changed(*args):
            if self.quota_read.call_count == 2:
                files.rows[r.ROOT + '/' + NAME + '/code'][0]['mtime'] += 1
            return capacity(8_000_000_000)
        self.quota_read.side_effect = changed
        self.assert_deferred(files, 'archive_inventory_changed')
        self.assertEqual(self.quota_read.call_count, 2)

    def test_stale_measurement_defers_without_changes(self):
        with patch.object(r.time, 'monotonic', side_effect=[0, 61]):
            self.assert_deferred(Files(), 'archive_quota_changed')

    def test_nested_change_during_archive_verification_preserves_backups(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                files = Files()
                if existing:
                    files.add_archive()

                def download_then_change(*args):
                    files.download(*args)
                    files.rows[r.ROOT + '/' + NAME + '/code'][0]['mtime'] += 1

                with self.assertRaisesRegex(ValueError, 'original_backup_changed'):
                    self.maintain((files.uapi, files.request, download_then_change))
                self.assertEqual(files.deleted, [])

    def test_existing_archive_replacement_during_verification_preserves_backups(self):
        files = Files()
        files.add_archive()

        def download_then_replace(*args):
            files.download(*args)
            files.rows[r.ROOT][-1]['mtime'] = START + 1

        with self.assertRaisesRegex(ValueError, 'backup_changed_during_verification'):
            self.maintain((files.uapi, files.request, download_then_replace))
        self.assertEqual(files.deleted, [])

    def test_existing_archive_still_requires_hashes_but_no_reserve(self):
        self.bounds = (None, None)
        self.quota_read.side_effect = AssertionError('existing archive does not need quota')
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt):
                files = Files(corrupt=corrupt)
                files.add_archive()
                if corrupt:
                    with self.assertRaisesRegex(ValueError, 'backup_hash_mismatch'):
                        self.maintain(files.api())
                    self.assertEqual(files.deleted, [])
                else:
                    self.assertEqual(self.maintain(files.api())['verified_files'], 4)
                self.assertEqual(files.compressions, 0)

    def test_complete_release_preserves_latest_and_unknown_and_future(self):
        files = Files(); result = self.maintain(files.api())
        self.assertEqual(result['verified_files'], 4)
        self.assertEqual(files.deleted, [r.ROOT + '/' + NAME,
            r.ROOT + '/retained-20261113-200001-old.tar.gz', r.APP + '/opdatering/.escape-release-old'])
        self.assertNotIn(r.APP + '/var/escape.db', files.deleted)
    def test_bad_archive_never_deletes_original_or_old_backup(self):
        files = Files(corrupt=True)
        with self.assertRaisesRegex(ValueError, 'backup_hash_mismatch'):
            self.maintain(files.api())
        self.assertEqual(files.deleted, [])
    def test_concurrent_version_change_preserves_original(self):
        files = Files(race=True)
        with self.assertRaisesRegex(ValueError, 'installed_release_changed'):
            self.maintain(files.api())
        self.assertEqual(files.deleted, [])
    def test_old_backup_is_not_a_fresh_deployment_backup(self):
        with self.assertRaisesRegex(ValueError, 'fresh_backup_unavailable'):
            r.choose_backup({'20261113-200001-old': {'type': 'dir'}}, START)
    def test_failed_or_different_release_is_rejected(self):
        for result in ({'status':'failed','operation':'app-deploy','sha':SHA},
                       {'status':'ok','operation':'app-deploy','sha':'b'*40},
                       {'status':'ok','operation':'resume'}):
            with self.assertRaises(ValueError): r.validate_result(result, SHA)
        r.validate_result({'status':'ok','operation':'app-deploy','sha':SHA}, SHA)
    def test_transfer_failure_preserves_all_backups(self):
        files = Files()
        def fail(*args): raise OSError('transfer failed')
        with self.assertRaises(OSError): self.maintain((files.uapi, files.request, fail))
        self.assertEqual(files.deleted, [])
    def test_scoped_transfer_account_is_revoked_on_connection_failure(self):
        calls = []
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit): return b'{"status":1,"data":{}}'
        opener = MagicMock()
        def open_request(req, **kwargs):
            calls.append(req.full_url)
            return Response()
        opener.open.side_effect = open_request
        ftp = MagicMock(); ftp.__enter__.return_value = ftp
        ftp.connect.side_effect = OSError('connection failed')
        with patch.dict(r.os.environ, {'ESCAPE_CPANEL_API_TOKEN':'test_token_12345'}), \
             patch.object(r.urllib.request, 'build_opener', return_value=opener), \
             patch.object(r.ftplib, 'FTP_TLS', return_value=ftp):
            api = r.transport_api()
            with self.assertRaises(OSError): api[2]('retained-test.tar.gz', 'unused', 100)
        self.assertEqual(len(calls), 2)
        self.assertIn('/Ftp/add_ftp?', calls[0])
        self.assertIn('homedir=.escape_backups', calls[0])
        self.assertIn('/Ftp/delete_ftp?', calls[1])
        self.assertIn('destroy=0', calls[1])

    def test_workflow_runs_retention_only_after_successful_client(self):
        workflow = (Path(__file__).resolve().parents[1] / '.github/workflows/escape-deploy-ping.yml').read_text()
        self.assertIn("if: success() && (steps.release_request.outputs.operation == 'deploy'", workflow)
        self.assertIn('group: escape-production-deployment', workflow)
        self.assertLess(workflow.index('python tools/nordicway_deploy_client.py'), workflow.index('python tools/nordicway_release_retention.py'))

if __name__ == '__main__': unittest.main()
