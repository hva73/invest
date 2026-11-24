"""Validate decoded app-deploy receipts without performing transport or recovery."""

import re


_LEGACY_FIELDS = {"operation", "status", "sha"}
_STATUSES = {"completed", "expired", "unavailable", "recovery", "failed"}
# Match the reason-bearing stages in tools/nordicway_deploy_client.py.
_REASONS_BY_STAGE = {
    "service_state": {
        "selector_failed",
        "application_state_unknown",
        "selector_exec_unavailable",
        "selector_exit_nonzero",
        "selector_response_too_large",
        "selector_invalid_json",
        "selector_result_failed",
        "service_status_unknown",
        "state_record_failed",
        "service_state_unavailable",
    },
    "drain": {
        "cron_unverified",
        "database_unavailable",
        "passenger_active",
        "database_in_use",
        "process_inspection_unavailable",
        "quiescence_unverified",
        "motor_stop_timeout",
        "drain_unavailable",
    },
}


def parse_release_failure_diagnostics(reply, expected_sha):
    """Return diagnostic status, stage, reason and recovery requirement.

    Pass None when transport failed or no decoded receipt is available.
    """
    unknown = {
        "status": "unknown",
        "stage": "unknown",
        "reason": "transport_or_reply_failed",
        "recovery_required": True,
    }
    if (
        type(expected_sha) is not str
        or not re.fullmatch(r"[0-9a-f]{40}", expected_sha)
        or type(reply) is not dict
    ):
        return unknown

    fields = set(reply)
    has_diagnostics = fields == _LEGACY_FIELDS | {"stage", "reason"}
    if (
        (fields != _LEGACY_FIELDS and not has_diagnostics)
        or any(type(value) is not str for value in reply.values())
        or reply["operation"] != "app-deploy"
        or reply["sha"] != expected_sha
        or reply["status"] not in _STATUSES
    ):
        return unknown

    status = reply["status"]
    if has_diagnostics:
        if (
            status not in {"failed", "recovery"}
            or reply["reason"] not in _REASONS_BY_STAGE.get(reply["stage"], ())
        ):
            return unknown

    return {
        "status": status,
        "stage": reply["stage"] if has_diagnostics else "unknown",
        "reason": reply["reason"] if has_diagnostics else None,
        "recovery_required": status == "recovery",
    }
