"""Step 10 sustained-throughput MTTR evaluation tests."""

from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from evaluate.mttr import ThroughputSample, evaluate_recovery, render_markdown

ROOT = Path(__file__).resolve().parents[1]


class MttrEvaluationTests(unittest.TestCase):
    def test_published_mttr_source_artifacts_match_the_reported_manifest_hashes(self) -> None:
        report = (ROOT / "results" / "mttr_metrics.md").read_text(encoding="utf-8")
        expected_hashes = {
            "task10-control-short-20261115": (
                "d7c0f26326e6e3a51c790b654a645e9353f4962064c61c77a4be5a6cb59fb73b"
            ),
            "task10-remediated-short-20261115": (
                "0e795af1ee6eb358ffa98ab1fe9a692763f263474f21c2a2342ecd8c4936555e"
            ),
        }

        for run_id, expected_hash in expected_hashes.items():
            manifest = ROOT / "runs" / run_id / "manifest.json"
            self.assertTrue(manifest.is_file())
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), expected_hash)
            self.assertIn(run_id, report)
            self.assertIn(expected_hash, report)

    def test_reports_first_of_three_sustained_samples_after_action(self) -> None:
        result = evaluate_recovery(
            samples=[
                ThroughputSample(0, 100),
                ThroughputSample(5, 90),
                ThroughputSample(10, 20),
                ThroughputSample(15, 95),
                ThroughputSample(20, 91),
                ThroughputSample(25, 92),
            ],
            fault_start=10,
            action_end=14,
            required_consecutive_samples=3,
        )

        self.assertEqual(result.pre_fault_median_bps, 95)
        self.assertEqual(result.restoration_threshold_bps, 85.5)
        self.assertEqual(result.restoration_time, 15)
        self.assertEqual(result.mttr_seconds, 5)

    def test_does_not_claim_recovery_when_the_sustained_window_is_not_met(self) -> None:
        result = evaluate_recovery(
            samples=[
                ThroughputSample(0, 100),
                ThroughputSample(5, 100),
                ThroughputSample(10, 10),
                ThroughputSample(15, 95),
                ThroughputSample(20, 10),
                ThroughputSample(25, 95),
            ],
            fault_start=10,
            action_end=10,
            required_consecutive_samples=3,
        )

        self.assertIsNone(result.restoration_time)
        self.assertIsNone(result.mttr_seconds)
        self.assertEqual(result.reason, "no sustained restoration before experiment end")

    def test_report_names_source_and_all_required_event_times(self) -> None:
        result = evaluate_recovery(
            samples=[
                ThroughputSample(0, 100),
                ThroughputSample(5, 100),
                ThroughputSample(10, 10),
                ThroughputSample(15, 100),
                ThroughputSample(20, 100),
                ThroughputSample(25, 100),
            ],
            fault_start=10,
            action_end=14,
        )

        report = render_markdown(
            run_id="task10-remediated",
            manifest_sha256="abc123",
            scenario="r1-r2-cost-reroute",
            fault_start=10,
            alert_time=11,
            action_start=12,
            action_end=14,
            result=result,
        )

        self.assertIn("`task10-remediated`", report)
        self.assertIn("`abc123`", report)
        self.assertIn("| Fault start | 10 |", report)
        self.assertIn("| Action end | 14 |", report)
        self.assertIn("| MTTR | 5.000 s |", report)


if __name__ == "__main__":
    unittest.main()
