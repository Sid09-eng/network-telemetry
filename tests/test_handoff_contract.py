"""Offline contracts for the Step 13 reproducibility handoff."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class HandoffContractTests(unittest.TestCase):
    def test_readme_documents_a_complete_linux_run_and_safe_teardown(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        for required in (
            "## Linux quick start",
            "make quickstart",
            "make topology-up",
            "make topology-check",
            "make monitoring-up",
            "## Teardown",
            "make monitoring-down",
            "make topology-down",
            "make teardown",
            "terraform -chdir=infra/terraform destroy",
            "## Observed demo flow",
            "## Limitations",
            "## Security boundary",
            "## Evidence and provenance",
            "102 automated tests",
        ):
            self.assertIn(required, readme)

    def test_readme_treats_gcp_as_a_required_deployment_path_not_an_optional_claim(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("required cloud deployment", readme)
        self.assertNotIn("optional deployment", readme)

    def test_committed_architecture_and_demo_assets_are_present(self) -> None:
        architecture = ROOT / "docs" / "architecture.svg"
        demo = ROOT / "docs" / "demo.gif"

        self.assertTrue(architecture.is_file())
        self.assertTrue(demo.is_file())
        self.assertGreater(demo.stat().st_size, 1_000)
        self.assertIn("NetPulse", architecture.read_text(encoding="utf-8"))
        self.assertIn("Containerlab", architecture.read_text(encoding="utf-8"))

    def test_every_copyable_quickstart_path_preserves_env_and_waits_for_prometheus(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        quickstart = (ROOT / "scripts" / "linux_quickstart.sh").read_text(encoding="utf-8")

        self.assertIn('if [[ ! -f .env ]]; then', readme)
        self.assertNotIn('cp .env.example .env  # only if .env does not already exist', readme)
        self.assertIn("wait_for_http", quickstart)
        self.assertIn("http://127.0.0.1:9090/-/ready", quickstart)
        self.assertIn("deadline=$((SECONDS + 60))", quickstart)
        self.assertIn("--connect-timeout 2", quickstart)
        self.assertIn('--max-time "$remaining"', quickstart)
        self.assertIn("if (( remaining <= 0 )); then", quickstart)
        self.assertIn("deadline=$((SECONDS + 60))", readme)
        self.assertIn("--connect-timeout 2", readme)
        self.assertIn("if (( remaining <= 0 )); then", readme)

    def test_quickstart_preflights_curl_and_supported_python_before_mutating(self) -> None:
        quickstart = (ROOT / "scripts" / "linux_quickstart.sh").read_text(encoding="utf-8")

        self.assertIn("python3 docker containerlab make curl", quickstart)
        self.assertIn('python3 -c \'import sys; raise SystemExit(', quickstart)
        self.assertLess(
            quickstart.index("python3 -c"),
            quickstart.index("python3 -m venv .venv"),
        )

    def test_quickstart_requires_a_nonempty_grafana_password_before_deployment(self) -> None:
        quickstart = (ROOT / "scripts" / "linux_quickstart.sh").read_text(encoding="utf-8")
        environment_example = (ROOT / ".env.example").read_text(encoding="utf-8")

        self.assertIn("GRAFANA_ADMIN_PASSWORD", quickstart)
        self.assertIn("Set a unique GRAFANA_ADMIN_PASSWORD", quickstart)
        self.assertIn("GRAFANA_ADMIN_PASSWORD=", environment_example)
        self.assertNotIn(
            "GRAFANA_ADMIN_PASSWORD=replace-with-a-local-password", environment_example
        )

    def test_capture_reports_a_validated_remediation_mode(self) -> None:
        specification = importlib.util.spec_from_file_location(
            "capture_demo_gif", ROOT / "scripts" / "capture_demo_gif.py"
        )
        self.assertIsNotNone(specification)
        self.assertIsNotNone(specification.loader)
        module = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(module)

        self.assertEqual(module.remediation_mode({"mode": "dry-run"}), "dry-run")
        self.assertEqual(module.remediation_mode({"mode": "live"}), "live")
        with self.assertRaises(ValueError):
            module.remediation_mode({"mode": "unknown"})

    def test_public_live_snapshot_is_sanitized_and_traceable(self) -> None:
        snapshot_json = ROOT / "results" / "live-demo-20261117.json"
        snapshot_markdown = ROOT / "results" / "live-demo-20261117.md"

        self.assertTrue(snapshot_json.is_file())
        self.assertTrue(snapshot_markdown.is_file())
        snapshot = json.loads(snapshot_json.read_text(encoding="utf-8"))

        self.assertEqual(snapshot["kind"], "NetPulse live acceptance snapshot")
        self.assertEqual(snapshot["topology"]["ospf_adjacencies"], "Full")
        self.assertEqual(snapshot["topology"]["r1_ecmp_paths_to_h2"], 2)
        self.assertGreaterEqual(snapshot["monitoring"]["healthy_scrape_targets"], 6)
        self.assertEqual(snapshot["monitoring"]["remediation_mode"], "dry-run")
        self.assertFalse(snapshot["controlled_traffic"]["fault_injected"])
        self.assertFalse(snapshot["controlled_traffic"]["remediation_request_submitted"])
        self.assertEqual(snapshot["source_run_id"], "live-demo-20261117-verified")
        self.assertRegex(snapshot["source_manifest_sha256"], r"^[0-9a-f]{64}$")
        self.assertNotIn("172.20.", snapshot_json.read_text(encoding="utf-8"))

    def test_forecast_metrics_reference_a_public_synthetic_source_run(self) -> None:
        source_run = ROOT / "runs" / "task7-variable-traffic-20261115"
        manifest = source_run / "manifest.json"
        telemetry = source_run / "telemetry.jsonl"
        report = (ROOT / "results" / "forecast_metrics.md").read_text(encoding="utf-8")

        self.assertTrue(manifest.is_file())
        self.assertTrue(telemetry.is_file())
        self.assertGreater(telemetry.stat().st_size, 1_000)
        self.assertNotIn("172.20.", telemetry.read_text(encoding="utf-8"))
        published_manifest = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(published_manifest["raw_telemetry"], None)
        self.assertEqual(published_manifest["fault_ground_truth"], None)
        digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
        self.assertIn(f"Source manifest SHA-256: `{digest}`", report)

    def test_anomaly_report_names_its_single_fault_evidence_and_limit(self) -> None:
        report = (ROOT / "results" / "anomaly_metrics.md").read_text(encoding="utf-8")

        self.assertIn("closed-loop-20261118-live-008", report)
        self.assertIn("36.14 s", report)
        self.assertIn("1.000 (1/1)", report)
        self.assertIn("Precision is not reported", report)

    def test_anomaly_evaluation_figure_is_committed_and_preserves_evidence_limits(self) -> None:
        figure = ROOT / "docs" / "anomaly-evaluation.svg"
        report = (ROOT / "results" / "anomaly_metrics.md").read_text(encoding="utf-8")

        self.assertTrue(figure.is_file())
        figure_text = figure.read_text(encoding="utf-8")
        self.assertIn("36.14 s", figure_text)
        self.assertIn("1 / 1", figure_text)
        self.assertIn("Precision not reported", figure_text)
        self.assertIn("../docs/anomaly-evaluation.svg", report)


if __name__ == "__main__":
    unittest.main()
