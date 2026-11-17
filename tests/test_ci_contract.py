"""Offline contracts for the Step 12 GitHub Actions quality gates."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
DEPENDABOT = ROOT / ".github" / "dependabot.yml"


class ContinuousIntegrationContractTests(unittest.TestCase):
    def test_workflow_covers_quality_build_iac_and_secret_scanning(self) -> None:
        workflow = WORKFLOW.read_text(encoding="utf-8")

        for required in (
            "pull_request:",
            "push:",
            "actions/checkout@v7",
            "actions/setup-python@v7",
            'python-version: "3.11"',
            'python -m pip install -e ".[dev]"',
            "make lint",
            "make test",
            "docker compose config --quiet",
            "docker compose build",
            "make traffic-host-image",
            "terraform -chdir=infra/terraform init -backend=false",
            "terraform -chdir=infra/terraform fmt -check",
            "terraform -chdir=infra/terraform validate",
            "gitleaks/gitleaks-action@v3",
        ):
            self.assertIn(required, workflow)

        self.assertNotIn("terraform apply", workflow)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", workflow)
        self.assertNotIn("actions/checkout@v4", workflow)

    def test_dependabot_tracks_action_and_python_dependencies_without_unreviewed_image_jumps(
        self,
    ) -> None:
        dependabot = DEPENDABOT.read_text(encoding="utf-8")

        self.assertIn('package-ecosystem: "github-actions"', dependabot)
        self.assertIn('package-ecosystem: "pip"', dependabot)
        self.assertNotIn('package-ecosystem: "docker"', dependabot)
        self.assertIn("interval: weekly", dependabot)


if __name__ == "__main__":
    unittest.main()
