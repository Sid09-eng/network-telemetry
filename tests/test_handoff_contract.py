"""Offline contracts for the Step 13 reproducibility handoff."""

from __future__ import annotations

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
            "78 automated tests",
        ):
            self.assertIn(required, readme)

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
        self.assertNotIn("172.20.", snapshot_json.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
