"""Coordinate a verified deployment. Not exposed by the SSH guard.

The production adapter is not implemented yet; this module does not itself
connect to the server or decide which releases are authorized.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Outcome:
    status: str
    stage: str
    service_restored: bool
    backup: str | None = None


def deploy(adapter, sha):
    """Sequence a release with fixed operations supplied by a trusted adapter.

    The adapter must implement real authorization, current quota, exclusive
    deployment lock, service drain, verified backup and runtime checks. Never
    wire unreviewed adapters to production. Database restore is not attempted.
    """
    stage = 'authorization'
    was_running = False
    stop_attempted = False
    mutation_started = False
    backup = None
    try:
        with adapter.lock():
            try:
                adapter.authorize(sha)
                stage = 'preflight'
                adapter.preflight(sha)
                stage = 'quota'
                adapter.check_quota()
                stage = 'stage'
                release = adapter.stage(sha)
                stage = 'service_state'
                state = adapter.service_status()
                if state not in ('started', 'stopped'):
                    raise ValueError('service_status_unknown')
                was_running = state == 'started'
                if was_running:
                    stage = 'stop'
                    stop_attempted = True
                    adapter.stop_service()
                stage = 'drain'
                with adapter.quiescence():
                    stage = 'backup_and_apply'
                    # The existing updater checks its fresh backup before replacing
                    # files. It may fail after a partial replacement, so never
                    # assume the old code remains usable after entering this call.
                    mutation_started = True
                    backup = adapter.backup_and_apply(release)
                    stage = 'verify_backup'
                    adapter.verify_backup(backup)
                    stage = 'verify_install'
                    adapter.verify_installed(sha)
                if was_running:
                    stage = 'start'
                    adapter.start_service()
                    stage = 'health'
                    adapter.verify_health(sha)
                return Outcome('ok' if was_running else 'updated_stopped', 'complete', was_running, str(backup))
            except Exception:
                # Keep the deployment lock held until recovery finishes.
                restored = False
                if was_running and stop_attempted and not mutation_started:
                    try:
                        adapter.start_service()
                        restored = True
                    except Exception:
                        pass
                return Outcome('failed', stage, restored, str(backup) if backup else None)
    except Exception:
        # Includes failure to acquire the deployment lock.
        return Outcome('failed', stage, False, None)
