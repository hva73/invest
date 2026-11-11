import fcntl, json, os, re, shutil, stat, subprocess, sys, tempfile
from pathlib import Path

HOME = Path('/home/nordicr4')
APP = HOME / 'escape_app'
BRIDGE = HOME / '.escape_deploy_bridge'
REPO = HOME / 'escape_deploy/invest'
SHA = 'b0fae95aa0d0342ef6de2145452829e2fb47825d'
sys.path.insert(0, str(BRIDGE))

import apply_update
import nordicway_deploy_runner as runner
import nordicway_release_preflight as preflight
import nordicway_release_stage as stage
import nordicway_release_backup as backup
import nordicway_uapi_quota as quota
import nordicway_release_service as service
import nordicway_deploy_health as health


def regular_size(path, optional=False):
    try:
        info = path.lstat()
    except FileNotFoundError:
        if optional:
            return 0
        raise ValueError('missing_file') from None
    if not stat.S_ISREG(info.st_mode):
        raise ValueError('unsafe_file')
    return info.st_size


def main():
    info = BRIDGE.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError('unsafe_bridge')
    if os.path.lexists(BRIDGE / 'deployment-incomplete.json'):
        raise ValueError('recovery_required')
    lock = os.open(APP / 'var/escape-deploy.lock', os.O_RDWR | getattr(os, 'O_NOFOLLOW', 0))
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with tempfile.TemporaryDirectory(prefix='release-check-', dir=BRIDGE) as directory:
            tmp = Path(directory)
            checkout = tmp / 'checkout'
            print('Kontrollerer Git og kandidatens staging...', flush=True)
            env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GIT_OPTIONAL_LOCKS': '0'}
            subprocess.run(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--quiet',
                            '--no-hardlinks', '--', str(REPO), str(checkout)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=120, check=True, env=env)
            runner.prepare_checkout(checkout, SHA)
            if preflight.manifest(checkout) != apply_update.FILES:
                raise ValueError('manifest_mismatch')
            if (checkout / 'requirements.txt').read_bytes() != (APP / 'requirements.txt').read_bytes():
                raise ValueError('requirements_changed')
            report = preflight.inspect(checkout, APP, SHA)
            if report.get('reason') or report.get('requested_sha') != SHA:
                raise ValueError('candidate_preflight_failed')
            dummy = tmp / 'stage-target'
            (dummy / 'var').mkdir(parents=True)
            (dummy / 'opdatering').mkdir()
            (dummy / 'var/escape.db').touch()
            result = stage.stage(checkout, dummy, SHA, approved_sha=SHA)
            if result.get('sha') != SHA or result.get('file_count') != len(apply_update.FILES):
                raise ValueError('staging_failed')
            source = result['total_bytes']
            db = APP / 'var/escape.db'
            db_size = regular_size(db)
            wal = regular_size(Path(str(db) + '-wal'), optional=True)
            journal = regular_size(Path(str(db) + '-journal'), optional=True)
            installed_size = sum(regular_size(APP / name) for name in apply_update.FILES)
            base = 2 * (db_size + wal + journal) + 2 * source + installed_size
            required = base + max(256 * 1024 * 1024, (base + 9) // 10)
            fs = os.statvfs(APP)
            fs_free = fs.f_bavail * fs.f_frsize
            uapi = shutil.which('uapi') or '/usr/local/cpanel/bin/uapi'
            result_uapi = subprocess.run([uapi, '--output=json', 'StatsBar', 'get_stats',
                                          'display=diskusage'], capture_output=True,
                                         text=True, timeout=20, check=True)
            account = quota.parse(json.loads(result_uapi.stdout))['free_lower_bytes']
            if min(account, fs_free) < required:
                raise ValueError('insufficient_space')
            print('Kontrollerer seneste backup; det kan tage lidt tid...', flush=True)
            root = HOME / '.escape_backups'
            info = root.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError('unsafe_backups')
            backups = sorted(p for p in root.iterdir() if backup.BACKUP_NAME.fullmatch(p.name))
            if not backups or backups[-1].is_symlink() or not backups[-1].is_dir():
                raise ValueError('backup_missing')
            latest = backups[-1]
            manifest = latest / 'manifest.json'
            if regular_size(manifest) > 2_000_000:
                raise ValueError('backup_manifest_invalid')
            records = json.loads(manifest.read_text(encoding='utf-8'))
            if records.get('format') != 1 or backup.verify_backup(latest, records) is not True:
                raise ValueError('backup_invalid')
            if backup._digest(latest / 'escape.db') != records.get('database_sha256'):
                raise ValueError('backup_digest_mismatch')
            installed = (APP / 'BUILD_COMMIT').read_text(encoding='ascii').strip()
            if service.status() != 'started' or health.web_health(installed) is not True:
                raise ValueError('health_unavailable')
            if os.path.lexists(BRIDGE / 'deployment-incomplete.json'):
                raise ValueError('recovery_required')
            print('Kandidat:', SHA)
            print('Installeret SHA:', installed)
            print('Kandidatfiler hentet og staged i isoleret test:', result['file_count'])
            print('Installerede filer sammenlignet:', report['installed_files_checked'])
            print('Installerede filer identiske med kandidat:', report['installed_files_matching'])
            print('Database/WAL/journal bytes:', db_size, wal, journal)
            print('Kandidat kildefiler bytes:', source)
            print('Anslået samlet pladsbehov bytes:', required)
            print('Ledig kontokvote mindst bytes:', account)
            print('Ledig filesystem-plads bytes:', fs_free)
            print('Seneste backup: integritet og manifest OK')
            print('App health og selector: OK')
            print('Recoverymarkør: ingen')
            print('PREFLIGHT: OK TIL REVIEW')
    finally:
        os.close(lock)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        safe = {'unsafe_bridge', 'recovery_required', 'missing_file', 'unsafe_file',
                'manifest_mismatch', 'requirements_changed', 'candidate_preflight_failed',
                'staging_failed', 'insufficient_space', 'unsafe_backups', 'backup_missing',
                'backup_manifest_invalid', 'backup_invalid', 'backup_digest_mismatch',
                'health_unavailable', 'checkout_not_clean', 'checkout_unavailable'}
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in safe else type(exc).__name__
        print('STOP:', reason)
        raise SystemExit(1) from None
