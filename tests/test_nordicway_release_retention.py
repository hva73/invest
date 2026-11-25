import gzip
import hashlib
import io
import json
import random
from pathlib import Path
import sys
import tarfile
import tempfile
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

class LocalCompression(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.raw = self.root / NAME
        (self.raw / 'code').mkdir(parents=True)
        self.destination = self.root / ('retained-' + NAME + '.tar.gz')
        self.previous = self.root / 'previous.tar.gz'
        self.previous.write_bytes(b'previous')
        self.make_raw(b'SQLite format 3\0' + b'x' * 16384)

    def make_raw(self, database):
        self.files = {'escape.db': database, 'code/BUILD_COMMIT': SHA.encode(),
                      'token.key': b'synthetic'}
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in self.files.items()}
        self.manifest = json.dumps({'format': 1, 'database_sha256': hashes['escape.db'],
                                    'files': {'BUILD_COMMIT': hashes['code/BUILD_COMMIT']},
                                    'keys': {'token.key': hashes['token.key'], 'push_vapid.pem': None}})
        self.files['manifest.json'] = self.manifest.encode()
        for name, data in self.files.items():
            (self.raw / name).write_bytes(data)

    def compress(self, limit=100000):
        return r.compress_verified_raw_backup(
            self.raw, self.destination, manifest_content=self.manifest,
            expected_size=len(self.files['escape.db']), available_bytes=limit)

    def assert_preserved(self):
        self.assertEqual(self.previous.read_bytes(), b'previous')
        self.assertEqual(list(self.root.glob('.backup-*')), [])
        for name, data in self.files.items():
            self.assertEqual((self.raw / name).read_bytes(), data)

    def test_recovery_hashes_and_exact_cap(self):
        result = self.compress()
        size = result['archive_bytes']
        self.assertEqual(size, self.destination.stat().st_size)
        self.destination.unlink()
        with self.assertRaisesRegex(ValueError, 'backup_output_cap_exceeded'):
            self.compress(size - 1)
        self.assertFalse(self.destination.exists())
        self.assertEqual(self.compress(size), result)
        with tarfile.open(self.destination, 'r:gz') as archive:
            actual = {member.name: hashlib.sha256(archive.extractfile(member).read()).hexdigest()
                      for member in archive}
        self.assertEqual(actual, {NAME + '/' + name: hashlib.sha256(data).hexdigest()
                                  for name, data in self.files.items()})
        archive_bytes = self.destination.read_bytes()
        with self.assertRaises(FileExistsError):
            self.compress(size)
        self.assertEqual(self.destination.read_bytes(), archive_bytes)
        self.assert_preserved()

    def test_incompressible_input_aborts_at_cap(self):
        self.make_raw(random.Random(57).randbytes(256 * 1024))
        with self.assertRaisesRegex(ValueError, 'backup_output_cap_exceeded'):
            self.compress(1024)
        self.assertFalse(self.destination.exists())
        self.assert_preserved()

    def test_corrupt_gzip_trailer_prevents_publication(self):
        verify = r.verify_local_backup_archive

        def corrupt(path, *args):
            with open(path, 'r+b') as stream:
                stream.seek(-8, io.SEEK_END)
                byte = stream.read(1)
                stream.seek(-1, io.SEEK_CUR)
                stream.write(bytes([byte[0] ^ 1]))
            return verify(path, *args)

        with patch.object(r, 'verify_local_backup_archive', side_effect=corrupt):
            with self.assertRaises(gzip.BadGzipFile):
                self.compress()
        self.assertFalse(self.destination.exists())
        self.assert_preserved()

    def test_unexpected_member_prevents_publication(self):
        addfile = tarfile.TarFile.addfile

        def add_extra(archive, info, stream=None):
            addfile(archive, info, stream)
            if info.name.endswith('/token.key'):
                addfile(archive, tarfile.TarInfo(NAME + '/extra'))

        with patch.object(tarfile.TarFile, 'addfile', add_extra):
            with self.assertRaisesRegex(ValueError, 'unexpected_archive_member'):
                self.compress()
        self.assertFalse(self.destination.exists())
        self.assert_preserved()

    def test_changed_source_hash_prevents_publication(self):
        self.files['escape.db'] = b'z' * len(self.files['escape.db'])
        (self.raw / 'escape.db').write_bytes(self.files['escape.db'])
        with self.assertRaisesRegex(ValueError, 'backup_hash_mismatch'):
            self.compress()
        self.assertFalse(self.destination.exists())
        self.assert_preserved()

    def test_source_change_after_compression_prevents_publication(self):
        verify = r.verify_local_backup_archive

        def change_source(*args):
            self.files['escape.db'] += b'changed'
            (self.raw / 'escape.db').write_bytes(self.files['escape.db'])
            return verify(*args)

        with patch.object(r, 'verify_local_backup_archive', side_effect=change_source):
            with self.assertRaisesRegex(ValueError, 'original_backup_changed'):
                self.compress()
        self.assertFalse(self.destination.exists())
        self.assert_preserved()


if __name__ == '__main__': unittest.main()
