import unittest

from release_failure_diagnostics import parse_release_failure_diagnostics


class ReleaseFailureDiagnosticsTests(unittest.TestCase):
    sha = "a" * 40

    def receipt(self, **fields):
        return {"operation": "app-deploy", "status": "failed", "sha": self.sha} | fields

    def test_legacy_statuses(self):
        for status in ("completed", "expired", "unavailable", "recovery", "failed"):
            with self.subTest(status=status):
                self.assertEqual(
                    parse_release_failure_diagnostics(self.receipt(status=status), self.sha),
                    {
                        "status": status,
                        "stage": "unknown",
                        "reason": None,
                        "recovery_required": status == "recovery",
                    },
                )

    def test_supported_pairs(self):
        for status, stage, reason in (
            ("failed", "service_state", "selector_failed"),
            ("recovery", "drain", "database_in_use"),
        ):
            with self.subTest(stage=stage):
                self.assertEqual(
                    parse_release_failure_diagnostics(
                        self.receipt(status=status, stage=stage, reason=reason), self.sha
                    ),
                    {
                        "status": status,
                        "stage": stage,
                        "reason": reason,
                        "recovery_required": status == "recovery",
                    },
                )

    def test_invalid_or_transport_unknown_requires_recovery(self):
        invalid = (
            None,
            [],
            {},
            self.receipt(operation="app-resume"),
            self.receipt(status="ok"),
            self.receipt(status=[]),
            self.receipt(sha="b" * 40),
            self.receipt(sha=self.sha.upper()),
            self.receipt(status="completed", recovery_required=True),
            self.receipt(status="completed", stage="drain", reason="database_in_use"),
            self.receipt(stage="drain"),
            self.receipt(reason="database_in_use"),
            self.receipt(stage="drain", reason="selector_failed"),
            self.receipt(stage="quota", reason="quota_exceeded"),
            self.receipt(stage="service_state", reason="arbitrary text"),
            self.receipt(stage="drain", reason="database_in_use", detail="extra"),
        )
        for reply in invalid:
            with self.subTest(reply=reply):
                self.assertEqual(
                    parse_release_failure_diagnostics(reply, self.sha),
                    {
                        "status": "unknown",
                        "stage": "unknown",
                        "reason": "transport_or_reply_failed",
                        "recovery_required": True,
                    },
                )

    def test_invalid_expected_sha(self):
        self.assertTrue(
            parse_release_failure_diagnostics(self.receipt(sha="short"), "short")[
                "recovery_required"
            ]
        )
