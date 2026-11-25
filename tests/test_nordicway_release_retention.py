import hashlib
import gzip
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

class CompressedFiles(Files):
    directory = r.ROOT + '/' + NAME

    def __init__(self):
        super().__init__()
        db = b'SQLite format 3\x00' + b'x' * 2048
        self.compressed_size = len(gzip.compress(db, compresslevel=6))
        manifest = json.loads(self.manifest)
        manifest.update(database_encoding='gzip', database_bytes=len(db))
        manifest['files']['static/scripts/app.js'] = hashlib.sha256(b'app').hexdigest()
        manifest['files']['absent.py'] = None
        manifest['keys']['push_vapid.pem'] = None
        self.set_manifest(manifest)
        self.rows[self.directory].extend([
            self.row('escape.db.gz', 'file', self.compressed_size),
            self.row('code', 'dir'), self.row('token.key', 'file', 7),
        ])
        self.rows[self.directory + '/code'] = [
            self.row('BUILD_COMMIT', 'file', 40), self.row('static', 'dir'),
        ]
        self.rows[self.directory + '/code/static'] = [self.row('scripts', 'dir')]
        self.rows[self.directory + '/code/static/scripts'] = [self.row('app.js', 'file', 3)]

    @staticmethod
    def row(name, kind, size=0):
        return {'file': name, 'type': kind, 'size': str(size), 'mtime': START + 1, 'mode': '0600'}

    def set_manifest(self, manifest):
        self.manifest = json.dumps(manifest)
        rows = self.rows[self.directory]
        rows[:] = [row for row in rows if row['file'] not in ('escape.db', 'manifest.json')]
        rows.append(self.row('manifest.json', 'file', len(self.manifest)))

    def uapi(self, operation, params):
        if operation == 'get_file_content':
            assert params['file'] in ('manifest.json', 'BUILD_COMMIT')
        else:
            assert operation == 'list_files', operation
        return super().uapi(operation, params)

    def api(self):
        return self.uapi, self.unexpected_call, self.unexpected_call

    @staticmethod
    def unexpected_call(*args):
        raise AssertionError('Compressed retention must only use Fileman readbacks')


class Retention(unittest.TestCase):
    def test_compressed_directory_retained_without_mutations_or_transfer(self):
        files = CompressedFiles()
        original = {path: list(rows) for path, rows in files.rows.items()}
        result = r.maintain(files.api(), SHA, START)
        self.assertEqual(result, {
            'status': 'compressed_directory_retained', 'retained_directory': NAME,
            'verification': 'external_metadata_only', 'database_bytes': 2064,
            'compressed_database_bytes': files.compressed_size,
        })
        self.assertEqual(files.rows, original)

    def test_invalid_compressed_manifest(self):
        for changes in (
            {'format': True}, {'database_encoding': 'raw'}, {'database_bytes': '2064'},
            {'database_bytes': 0}, {'database_sha256': 1}, {'files': {'../app.py': 'a' * 64}},
            {'keys': {'token.key': 'bad'}},
        ):
            with self.subTest(changes=changes):
                files = CompressedFiles()
                files.set_manifest({**json.loads(files.manifest), **changes})
                with self.assertRaisesRegex(ValueError, 'invalid_backup_manifest'):
                    r.maintain(files.api(), SHA, START)

    def test_compressed_directory_rejects_duplicate_database(self):
        files = CompressedFiles()
        files.rows[files.directory].append(files.row('escape.db', 'file', 2064))
        with self.assertRaisesRegex(ValueError, 'ambiguous_backup_database'):
            r.maintain(files.api(), SHA, START)

    def test_compressed_directory_rejects_invalid_gzip_metadata(self):
        for kind, size, error in (
            ('dir', 50, 'compressed_inventory_mismatch'),
            ('file', 18, 'invalid_backup_size'),
            ('file', 20_000_000_001, 'invalid_backup_size'),
        ):
            with self.subTest(kind=kind, size=size):
                files = CompressedFiles()
                rows = files.rows[files.directory]
                rows[:] = [row for row in rows if row['file'] != 'escape.db.gz']
                rows.append(files.row('escape.db.gz', kind, size))
                with self.assertRaisesRegex(ValueError, error):
                    r.maintain(files.api(), SHA, START)

    def test_invalid_compressed_inventory(self):
        for entry, error in (
            (CompressedFiles.row('unexpected.js', 'file', 1), 'compressed_inventory_mismatch'),
            (CompressedFiles.row('app.js', 'symlink', 3), 'compressed_inventory_mismatch'),
            (CompressedFiles.row('app.js', 'file', -1), 'invalid_backup_size'),
        ):
            with self.subTest(entry=entry):
                files = CompressedFiles()
                files.rows[files.directory + '/code/static/scripts'] = [entry]
                with self.assertRaisesRegex(ValueError, error):
                    r.maintain(files.api(), SHA, START)

    def test_compressed_directory_rechecks_nested_metadata_current_sha_and_freshness(self):
        for change, error in (
            ('nested', 'original_backup_changed'), ('sha', 'installed_release_changed'),
            ('new_backup', 'backup_changed_during_verification'),
        ):
            with self.subTest(change=change):
                files = CompressedFiles()
                path = files.directory + '/code/static/scripts'
                changed = False

                def readback(operation, params):
                    nonlocal changed
                    if params.get('dir') == path and not changed:
                        result = files.uapi(operation, params)
                        changed = True
                        if change == 'nested':
                            files.rows[path] = [files.row('app.js', 'file', 9)]
                        if change == 'new_backup':
                            files.rows[r.ROOT].append(files.row('20261114-200002-other', 'dir'))
                        return result
                    if changed and change == 'sha' and params.get('file') == 'BUILD_COMMIT':
                        return {'content': 'b' * 40}
                    return files.uapi(operation, params)

                with self.assertRaisesRegex(ValueError, error):
                    r.maintain((readback, files.unexpected_call, files.unexpected_call), SHA, START)

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
