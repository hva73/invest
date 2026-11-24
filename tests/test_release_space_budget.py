import unittest
from dataclasses import replace

from release_space_budget import SpaceEvidence, calculate_space_budget


class ReleaseSpaceBudgetTest(unittest.TestCase):
    def setUp(self):
        self.evidence = SpaceEvidence(
            account_free_bytes=241,
            filesystem_free_bytes=241,
            raw_locked_db_snapshot_bytes=100,
            archive_overhead_bytes=7,
            old_code_and_keys_bytes=3,
            candidate_staging_sets_bytes=(5, 5),
            wal_journal_sidecars_bytes=4,
            allocation_overhead_bytes=8,
            safety_margin_bytes=9,
            raw_archive_overlap=True,
        )

    def test_exact_boundary_and_independent_limits(self):
        result = calculate_space_budget(self.evidence)
        self.assertEqual([p.peak_bytes for p in result.phases], [134, 141, 241])
        self.assertEqual(result.peak_bytes, 241)
        self.assertEqual(result.blockers, ())
        self.assertEqual(result.outcome, "diagnostic_fits")
        self.assertEqual(result.phases[-1].account_headroom_bytes, 0)
        self.assertEqual(result.phases[-1].filesystem_headroom_bytes, 0)

        for limit in ("account", "filesystem"):
            with self.subTest(limit=limit):
                result = calculate_space_budget(
                    replace(self.evidence, **{f"{limit}_free_bytes": 240})
                )
                self.assertEqual(
                    result.blockers, (f"insufficient_{limit}_space:raw_snapshot_and_archive",)
                )
                self.assertEqual(getattr(result.phases[-1], f"{limit}_headroom_bytes"), -1)
                self.assertEqual(result.outcome, "diagnostic_blocked")

    def test_non_overlap_requires_evidence(self):
        evidence = replace(self.evidence, raw_archive_overlap=False, account_free_bytes=141)
        result = calculate_space_budget(evidence)
        self.assertIn("missing:non_overlap_evidence", result.blockers)
        self.assertEqual(result.peak_bytes, 241)

        result = calculate_space_budget(
            replace(evidence, non_overlap_evidence="Verified disjoint allocation lifetimes")
        )
        self.assertEqual([p.name for p in result.phases], ["raw_snapshot", "archive"])
        self.assertEqual(result.peak_bytes, 141)
        self.assertEqual(result.blockers, ())

    def test_separately_proven_archive_bound(self):
        evidence = replace(
            self.evidence, archive_overhead_bytes=None, proven_archive_upper_bound_bytes=80,
        )
        result = calculate_space_budget(evidence)
        self.assertEqual(result.blockers, ("missing:archive_bound_evidence",))
        self.assertIsNone(result.peak_bytes)

        result = calculate_space_budget(replace(
            evidence, archive_bound_evidence="Verified upper bound for this snapshot",
        ))
        self.assertEqual(result.peak_bytes, 214)
        self.assertEqual(result.blockers, ())

    def test_each_required_input_fails_closed_when_missing(self):
        cases = (
            ("account_free_bytes", "account_free_bytes"),
            ("filesystem_free_bytes", "filesystem_free_bytes"),
            ("raw_locked_db_snapshot_bytes", "raw_locked_db_snapshot_bytes"),
            ("archive_overhead_bytes", "archive_bound_evidence"),
            ("old_code_and_keys_bytes", "old_code_and_keys_bytes"),
            ("candidate_staging_sets_bytes", "candidate_staging_sets_bytes"),
            ("wal_journal_sidecars_bytes", "wal_journal_sidecars_bytes"),
            ("allocation_overhead_bytes", "allocation_overhead_bytes"),
            ("safety_margin_bytes", "safety_margin_bytes"),
            ("raw_archive_overlap", "raw_archive_overlap"),
        )
        for field, blocker in cases:
            with self.subTest(field=field):
                result = calculate_space_budget(replace(self.evidence, **{field: None}))
                self.assertEqual(result.blockers, (f"missing:{blocker}",))
                self.assertEqual(result.outcome, "diagnostic_blocked")
                if field == "account_free_bytes":
                    self.assertIsNone(result.phases[-1].account_headroom_bytes)
                    self.assertEqual(result.phases[-1].filesystem_headroom_bytes, 0)
                if field == "raw_archive_overlap":
                    self.assertEqual(result.peak_bytes, 241)

    def test_invalid_values_fail_closed(self):
        cases = (
            ("account_free_bytes", True),
            ("filesystem_free_bytes", 241.0),
            ("raw_locked_db_snapshot_bytes", -1),
            ("archive_overhead_bytes", -1),
            ("proven_archive_upper_bound_bytes", "80"),
            ("candidate_staging_sets_bytes", (5, -5)),
            ("candidate_staging_sets_bytes", ()),
            ("safety_margin_bytes", -1),
            ("raw_archive_overlap", 0),
        )
        for field, value in cases:
            with self.subTest(field=field, value=value):
                result = calculate_space_budget(replace(self.evidence, **{field: value}))
                self.assertIn(f"invalid:{field}", result.blockers)
                self.assertEqual(result.outcome, "diagnostic_blocked")

    def test_frozen_release_measured_regression(self):
        db = 6_712_553_472
        account_free = 12_775_112_128
        source = 2_215_894
        self.assertEqual(2 * db - account_free, 649_994_816)
        measured = SpaceEvidence(
            account_free_bytes=account_free,
            raw_locked_db_snapshot_bytes=db,
            candidate_staging_sets_bytes=(source, source),
        )
        result = calculate_space_budget(measured)
        self.assertEqual(result.outcome, "diagnostic_blocked")
        self.assertIn("missing:archive_bound_evidence", result.blockers)
        self.assertEqual(result.phases[0].known_budgeted_bytes, db + 2 * source)
        self.assertIsNone(result.phases[0].account_headroom_bytes)
        self.assertIsNone(result.peak_bytes)

        # Even pricing archive overhead at zero exceeds the measured quota floor.
        result = calculate_space_budget(replace(
            measured, archive_overhead_bytes=0, raw_archive_overlap=True,
        ))
        self.assertEqual(result.phases[-1].known_budgeted_bytes, 2 * db + 2 * source)
        self.assertIn("insufficient_account_space:raw_snapshot_and_archive", result.blockers)
        self.assertIsNone(result.peak_bytes)


if __name__ == "__main__":
    unittest.main()
