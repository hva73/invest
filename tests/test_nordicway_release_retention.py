import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch, MagicMock
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
        row = lambda n, typ, size=0, mtime=START-100: {'file': n, 'type': typ, 'size': str(size), 'mtime': mtime, 'mode': 0}
        self.rows = {
            r.ROOT: [row(NAME, 'dir'), row('retained-20261113-200001-old.tar.gz', 'file', 100), row('unrelated', 'file')],
            r.ROOT + '/' + NAME: [row('escape.db', 'file', len(db)), row('manifest.json', 'file', len(self.manifest))],
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
        self.rows[r.ROOT].append({'file': 'retained-' + NAME + '.tar.gz', 'type': 'file', 'size': len(self.archive)})
        return {'cpanelresult': {'event': {'result': 1}}}
    def download(self, name, path, size):
        self.downloads += 1; Path(path).write_bytes(self.archive)
    def api(self): return self.uapi, self.request, self.download

class Retention(unittest.TestCase):
    def test_complete_release_preserves_latest_and_unknown_and_future(self):
        files = Files(); result = r.maintain(files.api(), SHA, START)
        self.assertEqual(result['verified_files'], 4)
        self.assertEqual(files.deleted, [r.ROOT + '/' + NAME,
            r.ROOT + '/retained-20261113-200001-old.tar.gz', r.APP + '/opdatering/.escape-release-old'])
        self.assertNotIn(r.APP + '/var/escape.db', files.deleted)
    def test_bad_archive_never_deletes_original_or_old_backup(self):
        files = Files(corrupt=True)
        with self.assertRaisesRegex(ValueError, 'backup_hash_mismatch'):
            r.maintain(files.api(), SHA, START)
        self.assertEqual(files.deleted, [])
    def test_concurrent_version_change_preserves_original(self):
        files = Files(race=True)
        with self.assertRaisesRegex(ValueError, 'installed_release_changed'):
            r.maintain(files.api(), SHA, START)
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
        with self.assertRaises(OSError): r.maintain((files.uapi, files.request, fail), SHA, START)
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
