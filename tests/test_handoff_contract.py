"""Offline contracts for the Task 13 reproducibility handoff."""

from __future__ import annotations

import importlib.util
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
            "72 automated tests",
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


if __name__ == "__main__":
    unittest.main()
