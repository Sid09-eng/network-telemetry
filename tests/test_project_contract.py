"""Step 1 repository contract tests."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectContractTests(unittest.TestCase):
    def test_starter_files_exist_for_a_safe_python_project(self) -> None:
        expected_files = (
            "pyproject.toml",
            ".gitignore",
            ".env.example",
            "README.md",
            "Makefile",
        )

        missing = [name for name in expected_files if not (ROOT / name).is_file()]

        self.assertEqual(missing, [])

    def test_starter_files_define_safe_local_defaults(self) -> None:
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn('name = "netpulse"', pyproject)
        self.assertIn('requires-python = ">=3.11,<3.13"', pyproject)
        self.assertIn("[tool.hatch.build.targets.wheel]", pyproject)
        self.assertIn('packages = ["forecast", "monitoring", "remediation", "traffic"]', pyproject)
        self.assertIn(".env", gitignore)
        self.assertIn("*.tfstate", gitignore)
        self.assertIn("NETPULSE_DRY_RUN=true", env_example)
        self.assertIn("GCP", readme)
        self.assertIn("test:", makefile)


if __name__ == "__main__":
    unittest.main()
