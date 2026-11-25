"""Post-success release retention, preserving the latest fully verified backup."""
import ftplib
import gzip
import secrets
import ssl
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
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



def _manifest_hashes(manifest_content):
    if len(manifest_content.encode('utf-8')) > 100000:
        raise ValueError('invalid_backup_manifest')
    expected = json.loads(manifest_content)
    if not isinstance(expected, dict) or expected.get('format') != 1:
        raise ValueError('invalid_backup_manifest')
    wanted = {'escape.db': expected.get('database_sha256'),
              'manifest.json': hashlib.sha256(manifest_content.encode('utf-8')).hexdigest()}
    for group, prefix in (('files', 'code/'), ('keys', '')):
        entries = expected.get(group, {})
        if not isinstance(entries, dict):
            raise ValueError('invalid_backup_manifest')
        for name, digest in entries.items():
            path = PurePosixPath(name)
            relative = prefix + name
            if (not path.parts or path.is_absolute() or '..' in path.parts
                    or path.as_posix() != name or relative in wanted):
                raise ValueError('invalid_backup_manifest')
            if digest is not None:
                wanted[relative] = digest
    if any(not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest)
           for digest in wanted.values()):
        raise ValueError('invalid_backup_manifest')
    return wanted


class _BoundedOutput:
    def __init__(self, stream, limit):
        self.stream = stream
        self.limit = limit
        self.size = 0

    def write(self, data):
        if len(data) > self.limit - self.size:
            raise ValueError('backup_output_cap_exceeded')
        written = self.stream.write(data)
        if written != len(data):
            raise OSError('incomplete_backup_write')
        self.size += written
        return written


def verify_local_backup_archive(path, manifest_content, expected_size, name):
    """Read back a local archive against the independently verified raw inventory."""
    wanted = _manifest_hashes(manifest_content)
    if not BACKUP_NAME.fullmatch(name):
        raise ValueError('invalid_backup_name')
    with gzip.open(path, 'rb') as compressed:
        with tarfile.open(fileobj=compressed, mode='r|', bufsize=512) as archive:
            remaining = {name + '/' + relative: digest for relative, digest in wanted.items()}
            while remaining:
                member = archive.next()
                if member is None or member.type != tarfile.REGTYPE or member.name not in remaining:
                    raise ValueError('unexpected_archive_member')
                if member.name == name + '/escape.db' and member.size != expected_size:
                    raise ValueError('backup_manifest_or_size_mismatch')
                digest = hashlib.sha256()
                with archive.extractfile(member) as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                if digest.hexdigest() != remaining.pop(member.name):
                    raise ValueError('backup_hash_mismatch')
            # Read the full tar terminator and force gzip CRC/size validation at EOF.
            archive.fileobj.seek(archive.offset)
            trailer_size = 1024 + (-(archive.offset + 1024) % tarfile.RECORDSIZE)
            if archive.fileobj.read(trailer_size) != bytes(trailer_size) or archive.fileobj.read(1):
                raise ValueError('unexpected_archive_member_or_tar_end')
    return {'database_bytes': expected_size, 'verified_files': len(wanted)}


def compress_verified_raw_backup(raw, destination, *, manifest_content, expected_size, available_bytes):
    """Publish a verified private tar.gz within the caller's hard byte allowance.

    The private bridge must hold its release lock and verify the quiesced raw
    snapshot before apply. Persist a phase marker binding the release, raw path,
    manifest hash and DB size. Resume must revalidate the marker and raw backup
    or read back an already published archive against the pinned inventory.
    Keep the existing deploy quota gate. Recalculate verified available quota
    for this separate phase, accounting for the raw and prior backups. Journal
    progress durably across restart, including restart/health and archive
    readback outcomes, before separate retention cleanup. No automatic DB restore.

    The caller owns the private directories and keeps the source immutable
    under the lock. Publication never replaces an existing archive.
    """
    raw, destination = Path(raw), Path(destination)
    if type(available_bytes) is not int or available_bytes < 0:
        raise ValueError('invalid_backup_output_cap')
    if not BACKUP_NAME.fullmatch(raw.name) or raw.is_symlink() or not raw.is_dir():
        raise ValueError('invalid_backup_source')
    if destination.parent.resolve().is_relative_to(raw.resolve()):
        raise ValueError('invalid_backup_destination')
    wanted = _manifest_hashes(manifest_content)
    identities = {}
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.backup-', delete=False) as output:
            temporary = output.name
            bounded = _BoundedOutput(output, available_bytes)
            with gzip.GzipFile(filename='', fileobj=bounded, mode='wb', mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.GNU_FORMAT) as archive:
                    for relative in wanted:
                        source = raw / relative
                        if source.resolve() != raw.resolve() / relative:
                            raise ValueError('invalid_backup_source')
                        with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
                            before = os.fstat(stream.fileno())
                            if not stat.S_ISREG(before.st_mode):
                                raise ValueError('invalid_backup_source')
                            info = tarfile.TarInfo(raw.name + '/' + relative)
                            info.size = before.st_size
                            info.mode = 0o600
                            archive.addfile(info, stream)
                            identities[source] = before
            output.flush()
            os.fsync(output.fileno())
        result = verify_local_backup_archive(temporary, manifest_content, expected_size, raw.name)
        for source, before in identities.items():
            after = source.lstat()
            if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                    != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)):
                raise ValueError('original_backup_changed')
        os.link(temporary, destination)
        directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return dict(result, archive_bytes=bounded.size)
    finally:
        if temporary is not None:
            os.unlink(temporary)


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


def maintain(api, sha, started, *, redundant_only=False, before_delete=None):
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
    if not redundant_only and ARCHIVE not in top and '.escape_backups' in top:
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
    if before_delete is not None:
        before_delete(NAME, ARCHIVE, size)
    uapi('delete_file', {'path': ROOT + '/' + NAME})
    final = listing(ROOT)
    if NAME in final or ARCHIVE not in final or int(final[ARCHIVE]['size']) != size:
        raise ValueError('backup_replacement_unverified')
    if redundant_only:
        print(json.dumps({'status': 'verified', 'removed_redundant_raw': 1, **result}), flush=True)
        return result
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
