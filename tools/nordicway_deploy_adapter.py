"""Bridge the deployment sequence to existing release and backup code.

Not wired to SSH. Caller must supply an independently authorized SHA,
verified quota requirement, a real quiescence check and runtime health check.
"""
import fcntl
import os
import re
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import apply_update
import nordicway_autostart
import nordicway_deploy_health
import nordicway_uapi_quota
import nordicway_quiescence
import nordicway_writer_check
from nordicway_deploy_sequence import BackupVerificationFailure
import nordicway_release_backup
import nordicway_release_preflight
import nordicway_release_service
import nordicway_release_stage


def estimate_required_bytes(checkout, target):
    """Conservative reservation for DB backup/journal, code and two stages."""
    checkout, target = Path(checkout), Path(target)
    database = target / 'var' / 'escape.db'
    if database.is_symlink() or not database.is_file():
        raise ValueError('database_unavailable')
    names = nordicway_release_preflight.manifest(checkout)
    source_total = 0
    existing_total = 0
    for name in names:
        source = checkout / name
        installed = target / name
        if source.is_symlink() or not source.is_file() or installed.is_symlink():
            raise ValueError('unsafe_manifest_file')
        source_total += source.stat().st_size
        if installed.exists():
            if not installed.is_file():
                raise ValueError('unsafe_manifest_file')
            existing_total += installed.stat().st_size
    base = database.stat().st_size * 2 + source_total * 2 + existing_total
    return base + max(256 * 1024 * 1024, (base + 9) // 10)


class Adapter:
    def __init__(self, checkout, target, approved_sha, required_bytes,
                 quiescence_check, health_check, service=nordicway_release_service, quota_reader=None, cpanel_token=None):
        self.checkout = Path(checkout)
        self.target = Path(target)
        self.approved_sha = approved_sha
        self.required_bytes = required_bytes
        self.quiescence_check = quiescence_check
        self.health_check = health_check
        self.quota_reader = quota_reader
        self.cpanel_token = cpanel_token
        self.service = service
        self.inventory = None
        self.started_at = None
        self.backup_observer = None
        self.state_observer = None

    @contextmanager
    def lock(self):
        var = self.target / 'var'
        if var.is_symlink() or not var.is_dir():
            raise ValueError('unsafe_var_directory')
        fd = os.open(var / 'escape-deploy.lock', os.O_CREAT | os.O_RDWR |
                     getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)

    def authorize(self, sha):
        if (not isinstance(sha, str) or not re.fullmatch(r'[0-9a-f]{40}', sha)
                or sha != self.approved_sha):
            raise ValueError('unapproved_release')
        marker = self.target / 'BUILD_COMMIT'
        if marker.is_symlink():
            raise ValueError('unsafe_marker')
        if marker.is_file() and marker.read_text(encoding='ascii').strip() == sha:
            raise ValueError('already_installed')

    def preflight(self, sha):
        result = nordicway_release_preflight.inspect(self.checkout, self.target, sha)
        # "blocked" is not approval; the sequence separately checks gates.
        if result.get('status') != 'blocked' or 'reason' in result:
            raise ValueError('preflight_failed')

    def check_quota(self):
        required = max(self.required_bytes, estimate_required_bytes(self.checkout, self.target))
        if self.quota_reader is not None:
            result = self.quota_reader(self.target, required)
        else:
            result = nordicway_uapi_quota.verify_space(self.target, required, self.cpanel_token)
        if (not isinstance(result, dict) or result.get('required_bytes') != required
                or type(result.get('account_free_lower_bytes')) is not int
                or type(result.get('filesystem_free_bytes')) is not int
                or result['account_free_lower_bytes'] < required
                or result['filesystem_free_bytes'] < required):
            raise ValueError('quota_unavailable')
        return result

    def stage(self, sha):
        return nordicway_release_stage.stage(self.checkout, self.target, sha, approved_sha=self.approved_sha)

    def service_status(self):
        status = self.service.status()
        if self.state_observer is not None and status in ('started', 'stopped'):
            self.state_observer(status)
        return status

    def stop_service(self):
        if self.service.transition('stop') != 'stopped':
            raise ValueError('service_stop_failed')

    @contextmanager
    def quiescence(self):
        with nordicway_quiescence.stopped_motor(self.target / 'var'):
            # Separate check must cover Passenger, cron and other writers.
            check = (self.quiescence_check() if self.quiescence_check is not None else
                     nordicway_writer_check.verify(self.target / 'var' / 'escape.db'))
            if check is not True:
                raise ValueError('quiescence_unverified')
            yield

    def backup_and_apply(self, release):
        names = apply_update.FILES
        self.inventory = nordicway_release_backup.inventory(self.target, names)
        def verify_before_replace(backup):
            try:
                if self.verify_backup(backup) is not True:
                    raise ValueError('backup_unverified')
                if self.backup_observer is not None:
                    self.backup_observer(backup)
            except Exception as exc:
                raise BackupVerificationFailure('backup_unverified') from exc
            return True
        with nordicway_autostart.preserve(self.target / 'var'):
            return apply_update.apply(release['path'], self.target,
                                      verify_backup=verify_before_replace)

    def verify_backup(self, backup):
        return nordicway_release_backup.verify_backup(backup, self.inventory)

    def verify_installed(self, sha):
        report = nordicway_release_preflight.inspect(self.checkout, self.target, sha)
        if (report.get('reason') or report.get('requested_sha') != sha
                or report.get('installed_files_checked') != len(apply_update.FILES)
                or report.get('installed_files_matching') != len(apply_update.FILES)):
            raise ValueError('installed_content_mismatch')

    def start_service(self):
        self.started_at = datetime.now(timezone.utc)
        if self.service.transition('start') != 'started':
            raise ValueError('service_start_failed')

    def verify_health(self, sha):
        if self.started_at is None:
            raise ValueError('service_start_unverified')
        check = (self.health_check(sha) if self.health_check is not None else
                 nordicway_deploy_health.wait(self.target, sha, self.started_at))
        if check is not True:
            raise ValueError('health_unverified')
