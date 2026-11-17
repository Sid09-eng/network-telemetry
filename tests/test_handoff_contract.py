"""Offline contracts for the Task 13 reproducibility handoff."""

from __future__ import annotations

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
            "70 automated tests",
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


if __name__ == "__main__":
    unittest.main()
