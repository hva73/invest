"""Preserve the sole old backup as a hash-verified private tar.gz to free quota."""
import hashlib
import io
import json
import os
from pathlib import PurePosixPath
import re
import tarfile
import urllib.parse
import urllib.request
from nordicway_storage_inventory import NoRedirect

NAME = '20261113-181931-xhdz28wf'
ROOT = '/home/nordicr4/.escape_backups'
ARCHIVE = 'retained-' + NAME + '.tar.gz'
DB_BYTES = 2331734016


def verify_archive(data, manifest_content, expected_size=DB_BYTES):
    """Validate every backup byte against its pre-existing signed-by-hash inventory."""
    expected = json.loads(manifest_content)
    if expected.get('format') != 1 or not re.fullmatch(r'[0-9a-f]{64}', expected.get('database_sha256', '')):
        raise ValueError('invalid_backup_manifest')
    hashes = {}; database_size = None; archived_manifest = None
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if '..' in path.parts or member.issym() or member.islnk():
                raise ValueError('unsafe_archive_member')
            if member.isdir():
                continue
            if not member.isfile() or path.parts.count(NAME) != 1:
                raise ValueError('unexpected_archive_member')
            start = path.parts.index(NAME) + 1
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
    return {'database_bytes': database_size, 'verified_files': len(hashes), 'archive_bytes': len(data)}


def main():
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
    def listing(path):
        data = uapi('list_files', {'dir': path, 'show_hidden': 1})
        if not isinstance(data, list):
            raise ValueError('invalid_inventory')
        return {r['file']: r for r in data if isinstance(r, dict) and r.get('file') not in ('.', '..')}
    def content(directory, filename, limit=2000000):
        data = uapi('get_file_content', {'dir': directory, 'file': filename,
            'from_charset': 'ISO-8859-1', 'to_charset': 'UTF-8', 'update_html_document_encoding': 0}, limit)
        if not isinstance(data, dict) or not isinstance(data.get('content'), str):
            raise ValueError('invalid_content_reply')
        return data['content']
    top = listing(ROOT)
    if NAME not in top:
        raise ValueError('original_backup_unavailable')
    before = listing(ROOT + '/' + NAME)
    if before.get('escape.db', {}).get('type') != 'file' or int(before['escape.db']['size']) != DB_BYTES:
        raise ValueError('original_backup_changed')
    manifest = content(ROOT + '/' + NAME, 'manifest.json')
    if ARCHIVE not in top:
        params = {'cpanel_jsonapi_user': 'nordicr4', 'cpanel_jsonapi_apiversion': 2,
            'cpanel_jsonapi_module': 'Fileman', 'cpanel_jsonapi_func': 'fileop',
            'op': 'compress', 'sourcefiles': '.escape_backups/' + NAME,
            'destfiles': '.escape_backups/' + ARCHIVE, 'metadata': 'tar.gz', 'doubledecode': 0}
        result = request('json-api/cpanel', params).get('cpanelresult', {})
        if result.get('event', {}).get('result') not in (1, '1'):
            raise ValueError('archive_creation_failed')
    archive_row = listing(ROOT).get(ARCHIVE, {})
    size = int(archive_row.get('size', 0))
    if archive_row.get('type') != 'file' or not 1000 < size <= 300000000:
        raise ValueError('archive_size_unavailable')
    print(json.dumps({'status': 'archive_created', 'archive_bytes': size}), flush=True)
    data = content(ROOT, ARCHIVE, 1800000000).encode('latin-1')
    if len(data) != size:
        raise ValueError('archive_download_incomplete')
    result = verify_archive(data, manifest)
    print(json.dumps({'status': 'archive_hashes_verified', **result}), flush=True)
    after = listing(ROOT + '/' + NAME)
    metadata = lambda rows: {name: {k: row.get(k) for k in ('file','type','mode','size','mtime')} for name,row in rows.items()}
    if metadata(before) != metadata(after) or manifest != content(ROOT + '/' + NAME, 'manifest.json'):
        raise ValueError('original_backup_changed')
    # The archive is verified against the original per-file and DB SHA256s.
    # This deletes only the now-redundant uncompressed form, never production.
    uapi('delete_file', {'path': ROOT + '/' + NAME})
    final = listing(ROOT)
    if NAME in final or ARCHIVE not in final or int(final[ARCHIVE]['size']) != size:
        raise ValueError('backup_replacement_unverified')
    print(json.dumps({'status': 'verified', 'retained_archive': ARCHIVE, **result}), flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        reason = str(exc)
        print(json.dumps({'status': 'failed', 'category': reason if isinstance(exc, ValueError) and re.fullmatch('[a-z_]{1,80}', reason) else type(exc).__name__}), flush=True)
        raise SystemExit(1) from None
