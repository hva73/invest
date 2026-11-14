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
        return {r['file']: r for r in data if isinstance(r, dict) and r.get('file') not in ('.', '..')}
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
    before = listing(ROOT + '/' + NAME)
    DB_BYTES = int(before.get('escape.db', {}).get('size', 0))
    if not 512 < DB_BYTES <= 10_000_000_000:
        raise ValueError('invalid_backup_size')

    top = listing(ROOT)
    if NAME not in top:
        raise ValueError('original_backup_unavailable')
    before = listing(ROOT + '/' + NAME)
    if before.get('escape.db', {}).get('type') != 'file' or int(before['escape.db']['size']) != DB_BYTES:
        raise ValueError('original_backup_changed')
    manifest = content(ROOT + '/' + NAME, 'manifest.json')
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
    metadata = lambda rows: {name: {k: row.get(k) for k in ('file','type','mode','size','mtime')} for name,row in rows.items()}
    if metadata(before) != metadata(after) or manifest != content(ROOT + '/' + NAME, 'manifest.json'):
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
