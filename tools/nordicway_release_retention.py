"""Post-success release retention, preserving the latest fully verified backup."""
import ftplib
import secrets
import ssl
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import re
import tarfile
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timezone
import sys

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("redirect_denied")

BACKUP_NAME = re.compile(r'\d{8}-\d{6}-[A-Za-z0-9_-]+\Z')
APP = '/home/nordicr4/escape_app'
ROOT = '/home/nordicr4/.escape_backups'
MAX_MANIFEST_BYTES = 100_000
MAX_COMPRESSED_BACKUP_BYTES = 20_000_000_000


def backup_metadata(rows):
    return {name: tuple(row.get(key) for key in ('type', 'mode', 'size', 'mtime'))
            for name, row in rows.items()}


def inventory_size(row):
    size = row.get('size')
    if type(size) is int:
        return size
    if isinstance(size, str) and re.fullmatch(r'[0-9]{1,12}', size):
        return int(size)
    raise ValueError('invalid_backup_size')


def compressed_inventory(manifest):
    def unique_fields(pairs):
        fields = dict(pairs)
        if len(fields) != len(pairs):
            raise ValueError('invalid_backup_manifest')
        return fields

    try:
        expected = json.loads(manifest, object_pairs_hook=unique_fields)
    except (json.JSONDecodeError, RecursionError):
        raise ValueError('invalid_backup_manifest') from None

    def valid_hash(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value)

    if (not isinstance(expected, dict) or type(expected.get('format')) is not int
            or expected['format'] != 1 or expected.get('database_encoding') != 'gzip'
            or not valid_hash(expected.get('database_sha256'))
            or type(expected.get('database_bytes')) is not int
            or not 512 < expected['database_bytes'] <= MAX_COMPRESSED_BACKUP_BYTES):
        raise ValueError('invalid_backup_manifest')
    tree = {'': {'escape.db.gz': 'file', 'manifest.json': 'file'}}
    for field, prefix in (('files', 'code/'), ('keys', '')):
        entries = expected.get(field)
        if not isinstance(entries, dict) or len(entries) > 500:
            raise ValueError('invalid_backup_manifest')
        for name, digest in entries.items():
            parts = name.split('/')
            if (len(parts) > 16
                    or any(part in ('.', '..') or not re.fullmatch(r'[A-Za-z0-9_.-]+', part)
                           for part in parts)
                    or (field == 'keys' and name not in ('token.key', 'push_vapid.pem'))
                    or (digest is not None and not valid_hash(digest))):
                raise ValueError('invalid_backup_manifest')
            if digest is None:
                continue
            path = ''
            relative = (prefix + name).split('/')
            for index, part in enumerate(relative):
                kind = 'file' if index == len(relative) - 1 else 'dir'
                if tree.setdefault(path, {}).setdefault(part, kind) != kind:
                    raise ValueError('invalid_backup_manifest')
                path = path + '/' + part if path else part
    if len(tree) > 500 or sum(map(len, tree.values())) > 1000:
        raise ValueError('invalid_backup_manifest')
    return expected['database_bytes'], tree


def verify_archive(data, manifest_content, expected_size, name):
    """Validate every backup byte against its pre-existing signed-by-hash inventory."""
    expected = json.loads(manifest_content)
    if expected.get('format') != 1 or not re.fullmatch(r'[0-9a-f]{64}', expected.get('database_sha256', '')):
        raise ValueError('invalid_backup_manifest')
    hashes = {}; database_size = None; archived_manifest = None
    archive_input = {'name': data} if isinstance(data, str) else {'fileobj': io.BytesIO(data)}
    with tarfile.open(mode='r:gz', **archive_input) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if '..' in path.parts or member.issym() or member.islnk():
                raise ValueError('unsafe_archive_member')
            if member.isdir():
                continue
            if not member.isfile() or path.parts.count(name) != 1:
                raise ValueError('unexpected_archive_member')
            start = path.parts.index(name) + 1
            relative = '/'.join(path.parts[start:])
            if not relative or relative in hashes:
                raise ValueError('duplicate_archive_member')
            stream = archive.extractfile(member)
            if relative == 'manifest.json':
                if member.size > 100000:
                    raise ValueError('invalid_backup_manifest')
                archived_manifest = stream.read()
                hashes[relative] = hashlib.sha256(archived_manifest).hexdigest()
            else:
                digest = hashlib.sha256()
                while block := stream.read(1024 * 1024):
                    digest.update(block)
                hashes[relative] = digest.hexdigest()
            if relative == 'escape.db':
                database_size = member.size
    if archived_manifest != manifest_content.encode('utf-8') or database_size != expected_size:
        raise ValueError('backup_manifest_or_size_mismatch')
    wanted = {'escape.db': expected['database_sha256'], 'manifest.json': hashlib.sha256(archived_manifest).hexdigest()}
    for name, digest in expected.get('files', {}).items():
        if digest is not None:
            wanted['code/' + name] = digest
    for name, digest in expected.get('keys', {}).items():
        if digest is not None:
            wanted[name] = digest
    if hashes != wanted:
        raise ValueError('backup_hash_mismatch')
    return {'database_bytes': database_size, 'verified_files': len(hashes)}


def choose_backup(rows, started):
    names = [n for n, row in rows.items() if BACKUP_NAME.fullmatch(n) and row.get('type') == 'dir']
    if not names:
        raise ValueError('fresh_backup_unavailable')
    name = max(names)
    stamp = datetime.strptime(name[:15], '%Y%m%d-%H%M%S').replace(tzinfo=timezone.utc).timestamp()
    if stamp < started - 5:
        raise ValueError('fresh_backup_unavailable')
    return name


def validate_result(result, sha):
    if not re.fullmatch(r'[0-9a-f]{40}', sha or ''):
        raise ValueError('invalid_release')
    if result.get('status') != 'ok' or result.get('operation') not in ('deploy', 'app-deploy'):
        raise ValueError('deployment_not_successful')
    if result.get('operation') == 'app-deploy' and result.get('sha') != sha:
        raise ValueError('release_mismatch')


def maintain(api, sha, started):
    uapi, request, download = api
    def listing(path):
        data = uapi('list_files', {'dir': path, 'show_hidden': 1})
        if not isinstance(data, list) or len(data) > 500:
            raise ValueError('invalid_inventory')
        rows = {}
        for row in data:
            if not isinstance(row, dict) or not isinstance(row.get('file'), str):
                raise ValueError('invalid_inventory')
            name = row['file']
            if name in ('.', '..'):
                continue
            if name in rows:
                raise ValueError('invalid_inventory')
            rows[name] = row
        return rows
    def content(directory, filename):
        data = uapi('get_file_content', {'dir': directory, 'file': filename,
            'from_charset': 'ISO-8859-1', 'to_charset': 'UTF-8', 'update_html_document_encoding': 0})
        if not isinstance(data, dict) or not isinstance(data.get('content'), str):
            raise ValueError('invalid_content_reply')
        return data['content']
    def current():
        if content(APP, 'BUILD_COMMIT').strip() != sha:
            raise ValueError('installed_release_changed')
    current()
    top = listing(ROOT)
    NAME = choose_backup(top, started)
    ARCHIVE = 'retained-' + NAME + '.tar.gz'
    directory = ROOT + '/' + NAME
    before = listing(directory)
    if 'escape.db.gz' in before:
        if 'escape.db' in before:
            raise ValueError('ambiguous_backup_database')
        manifest_row = before.get('manifest.json', {})
        if manifest_row.get('type') != 'file':
            raise ValueError('invalid_backup_manifest')
        manifest_size = inventory_size(manifest_row)
        if not 0 < manifest_size <= MAX_MANIFEST_BYTES:
            raise ValueError('invalid_backup_manifest')
        manifest = content(directory, 'manifest.json')
        if len(manifest.encode('utf-8')) != manifest_size:
            raise ValueError('invalid_backup_manifest')
        database_bytes, tree = compressed_inventory(manifest)

        def inventory(root_rows):
            snapshot = {}
            for path, expected in tree.items():
                rows = listing(directory + '/' + path) if path else root_rows
                if {name: row.get('type') for name, row in rows.items()} != expected:
                    raise ValueError('compressed_inventory_mismatch')
                for name, kind in expected.items():
                    if kind == 'file' and inventory_size(rows[name]) < 0:
                        raise ValueError('invalid_backup_size')
                snapshot[path] = backup_metadata(rows)
            return snapshot

        first = inventory(before)
        compressed_bytes = inventory_size(before['escape.db.gz'])
        if not 18 < compressed_bytes <= MAX_COMPRESSED_BACKUP_BYTES:
            raise ValueError('invalid_backup_size')
        if first != inventory(listing(directory)) or manifest != content(directory, 'manifest.json'):
            raise ValueError('original_backup_changed')
        final = listing(ROOT)
        if (choose_backup(final, started) != NAME
                or backup_metadata({NAME: final[NAME]}) != backup_metadata({NAME: top[NAME]})):
            raise ValueError('backup_changed_during_verification')
        current()
        # The release bridge verifies the backup bytes. Retention checks only Fileman metadata.
        result = {'status': 'compressed_directory_retained', 'retained_directory': NAME,
                  'verification': 'external_metadata_only', 'database_bytes': database_bytes,
                  'compressed_database_bytes': compressed_bytes}
        print(json.dumps(result), flush=True)
        return result

    DB_BYTES = int(before.get('escape.db', {}).get('size', 0))
    if not 512 < DB_BYTES <= 10_000_000_000:
        raise ValueError('invalid_backup_size')

    top = listing(ROOT)
    if NAME not in top:
        raise ValueError('original_backup_unavailable')
    before = listing(ROOT + '/' + NAME)
    if ('escape.db.gz' in before or before.get('escape.db', {}).get('type') != 'file'
            or int(before['escape.db']['size']) != DB_BYTES):
        raise ValueError('original_backup_changed')
    manifest = content(ROOT + '/' + NAME, 'manifest.json')
    if json.loads(manifest).get('database_encoding') == 'gzip':
        raise ValueError('compressed_inventory_mismatch')
    if ARCHIVE not in top and '.escape_backups' in top:
        nested = listing(ROOT + '/.escape_backups')
        if ARCHIVE in nested:
            uapi('move_file', {'source': ROOT + '/.escape_backups/' + ARCHIVE, 'destination': ROOT + '/' + ARCHIVE})
            if not listing(ROOT + '/.escape_backups'):
                uapi('delete_file', {'path': ROOT + '/.escape_backups'})
            top = listing(ROOT)
    if ARCHIVE not in top:
        params = {'cpanel_jsonapi_user': 'nordicr4', 'cpanel_jsonapi_apiversion': 2,
            'cpanel_jsonapi_module': 'Fileman', 'cpanel_jsonapi_func': 'fileop',
            'op': 'compress', 'sourcefiles': ROOT + '/' + NAME,
            'destfiles': ROOT + '/' + ARCHIVE, 'metadata': 'tar.gz', 'doubledecode': 0}
        result = request('json-api/cpanel', params).get('cpanelresult', {})
        if result.get('event', {}).get('result') not in (1, '1'):
            raise ValueError('archive_creation_failed')
    archive_row = listing(ROOT).get(ARCHIVE, {})
    size = int(archive_row.get('size', 0))
    if archive_row.get('type') != 'file' or not 1000 < size <= DB_BYTES * 2 + 10000000:
        raise ValueError('archive_size_unavailable')
    print(json.dumps({'status': 'archive_created', 'archive_bytes': size}), flush=True)
    with tempfile.TemporaryDirectory(prefix='escape-private-backup-') as temporary:
        archive_path = temporary + '/retained.tar.gz'
        download(ARCHIVE, archive_path, size)
        result = verify_archive(archive_path, manifest, DB_BYTES, NAME)
    result['archive_bytes'] = size
    print(json.dumps({'status': 'archive_hashes_verified', **result}), flush=True)
    after = listing(ROOT + '/' + NAME)
    if backup_metadata(before) != backup_metadata(after) or manifest != content(ROOT + '/' + NAME, 'manifest.json'):
        raise ValueError('original_backup_changed')
    # The archive is verified against the original per-file and DB SHA256s.
    # This deletes only the now-redundant uncompressed form, never production.
    current()
    if choose_backup(listing(ROOT), started) != NAME:
        raise ValueError('backup_changed_during_verification')
    uapi('delete_file', {'path': ROOT + '/' + NAME})
    final = listing(ROOT)
    if NAME in final or ARCHIVE not in final or int(final[ARCHIVE]['size']) != size:
        raise ValueError('backup_replacement_unverified')
    removed = 0
    for old, row in listing(ROOT).items():
        match = re.fullmatch(r'retained-(\d{8}-\d{6}-[A-Za-z0-9_-]+)\.tar\.gz', old)
        older_archive = match and match.group(1) < NAME and row.get('type') == 'file'
        older_raw = BACKUP_NAME.fullmatch(old) and old < NAME and row.get('type') == 'dir'
        if older_archive or older_raw:
            current()
            uapi('delete_file', {'path': ROOT + '/' + old})
            removed += 1
    stage_root = APP + '/opdatering'
    stages = listing(stage_root)
    current_stages = [n for n, row in stages.items()
        if re.fullmatch(r'\.escape-release-[A-Za-z0-9_-]+', n) and row.get('type') == 'dir'
        and content(stage_root + '/' + n, 'BUILD_COMMIT').strip() == sha]
    if not current_stages:
        raise ValueError('current_staging_unavailable')
    retained_stage = max(current_stages, key=lambda n: int(stages[n].get('mtime', 0)))
    for old, row in stages.items():
        if (old != retained_stage and re.fullmatch(r'\.escape-release-[A-Za-z0-9_-]+', old)
                and row.get('type') == 'dir' and int(row.get('mtime', 0)) < started
                and re.fullmatch(r'[0-9a-f]{40}', content(stage_root + '/' + old, 'BUILD_COMMIT').strip())):
            current()
            uapi('delete_file', {'path': stage_root + '/' + old})
            removed += 1
    remaining = listing(ROOT)
    if NAME in remaining or int(remaining.get(ARCHIVE, {}).get('size', 0)) != size:
        raise ValueError('final_backup_unverified')
    print(json.dumps({'status': 'verified', 'retained_archive': ARCHIVE, 'removed_old_entries': removed, **result}), flush=True)
    return result


def transport_api():
    token = os.environ.get('ESCAPE_CPANEL_API_TOKEN', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{10,256}', token):
        raise ValueError('credential_unavailable')
    opener = urllib.request.build_opener(NoRedirect())
    def request(path, params, limit=2000000):
        url = 'https://cp14.nordicway.dk:2083/' + path + '?' + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={'Authorization': 'cpanel nordicr4:' + token, 'Accept': 'application/json'})
        with opener.open(req, timeout=240) as response:
            data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('reply_too_large')
        return json.loads(data)
    def uapi(operation, params, limit=2000000):
        payload = request('execute/Fileman/' + operation, params, limit)
        result = payload.get('result', payload)
        if result.get('status') not in (1, '1'):
            raise ValueError('file_api_rejected')
        return result.get('data')
    def download(archive_name, destination, size):
        username = 'escapeverify' + secrets.token_hex(4)
        password = secrets.token_urlsafe(40)
        domain = 'nordic-response.dk'
        def ftp_api(operation, params):
            payload = request('execute/Ftp/' + operation, params)
            result = payload.get('result', payload)
            if result.get('status') not in (1, '1'):
                raise ValueError('temporary_ftp_api_rejected')
            return result.get('data')
        try:
            ftp_api('add_ftp', {'user': username, 'pass': password, 'domain': domain,
                'homedir': '.escape_backups', 'quota': 1})
            count = 0
            with ftplib.FTP_TLS(context=ssl.create_default_context(), timeout=120) as ftp:
                ftp.connect('cp14.nordicway.dk', 21)
                ftp.login(username + '@' + domain, password)
                ftp.prot_p()
                with open(destination, 'wb') as target:
                    def save(block):
                        nonlocal count
                        count += len(block)
                        if count > size:
                            raise ValueError('archive_download_incomplete')
                        target.write(block)
                    ftp.retrbinary('RETR ' + archive_name, save, blocksize=1024 * 1024)
            if count != size:
                raise ValueError('archive_download_incomplete')
        finally:
            ftp_api('delete_ftp', {'user': username, 'domain': domain, 'destroy': 0})
    return uapi, request, download


def main():
    with open(os.environ['ESCAPE_DEPLOY_RESULT_FILE']) as stream:
        result = json.load(stream)
    sha = os.environ.get('ESCAPE_RELEASE_SHA', '')
    validate_result(result, sha)
    started = int(os.environ['ESCAPE_RELEASE_STARTED_AT'])
    now = datetime.now(timezone.utc).timestamp()
    if not now - 3600 <= started <= now:
        raise ValueError('invalid_release_start')
    maintain(transport_api(), sha, started)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        reason = str(exc)
        print(json.dumps({'status': 'failed', 'category': reason if isinstance(exc, ValueError) and re.fullmatch('[a-z_]{1,80}', reason) else type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
