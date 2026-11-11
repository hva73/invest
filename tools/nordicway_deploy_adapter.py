"""Bridge the deployment sequence to existing release and backup code.

Not wired to SSH. Caller must supply an independently authorized SHA,
verified quota requirement, a real quiescence check and runtime health check.
"""
import fcntl
import os
import re
from contextlib import contextmanager
from pathlib import Path

import apply_update
import nordicway_autostart
import nordicway_quota
import nordicway_release_backup
import nordicway_release_preflight
import nordicway_release_service
import nordicway_release_stage


class Adapter:
    def __init__(self, checkout, target, approved_sha, required_bytes,
                 quiescence_check, health_check, service=nordicway_release_service):
        self.checkout = Path(checkout)
        self.target = Path(target)
        self.approved_sha = approved_sha
        self.required_bytes = required_bytes
        self.quiescence_check = quiescence_check
        self.health_check = health_check
        self.service = service
        self.inventory = None

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
        return nordicway_quota.verify_space(self.target, self.required_bytes)

    def stage(self, sha):
        return nordicway_release_stage.stage(self.checkout, self.target, sha, approved_sha=self.approved_sha)

    def service_status(self):
        return self.service.status()

    def stop_service(self):
        if self.service.transition('stop') != 'stopped':
            raise ValueError('service_stop_failed')

    def wait_for_quiescence(self):
        if self.quiescence_check() is not True:
            raise ValueError('quiescence_unverified')

    def backup_and_apply(self, release):
        names = apply_update.FILES
        self.inventory = nordicway_release_backup.inventory(self.target, names)
        with nordicway_autostart.preserve(self.target / 'var'):
            return apply_update.apply(release['path'], self.target)

    def verify_backup(self, backup):
        return nordicway_release_backup.verify_backup(backup, self.inventory)

    def verify_installed(self, sha):
        report = nordicway_release_preflight.inspect(self.checkout, self.target, sha)
        if (report.get('reason') or report.get('requested_sha') != sha
                or report.get('installed_files_checked') != len(apply_update.FILES)
                or report.get('installed_files_matching') != len(apply_update.FILES)):
            raise ValueError('installed_content_mismatch')

    def start_service(self):
        if self.service.transition('start') != 'started':
            raise ValueError('service_start_failed')

    def verify_health(self, sha):
        if self.health_check(sha) is not True:
            raise ValueError('health_unverified')
