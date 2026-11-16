"""Offline contracts for the Task 11 Terraform foundation."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TERRAFORM = ROOT / "infra" / "terraform"


class TerraformContractTests(unittest.TestCase):
    def test_configuration_has_no_committed_project_or_credentials(self) -> None:
        example = (TERRAFORM / "terraform.tfvars.example").read_text(encoding="utf-8")

        self.assertIn('replace-with-your-gcp-project-id', example)
        self.assertNotIn("service-account", example.lower())
        self.assertNotIn("credentials", example.lower())

    def test_network_access_is_scoped_to_the_named_admin_cidr(self) -> None:
        configuration = (TERRAFORM / "main.tf").read_text(encoding="utf-8")
        outputs = (TERRAFORM / "outputs.tf").read_text(encoding="utf-8")

        self.assertIn("auto_create_subnetworks = false", configuration)
        self.assertIn('image = "ubuntu-os-cloud/ubuntu-2404-lts-amd64"', configuration)
        self.assertNotIn('image = "ubuntu-os-cloud/ubuntu-2404-lts"', configuration)
        self.assertIn("source_ranges = [var.admin_cidr]", configuration)
        self.assertIn('target_tags   = ["netpulse"]', configuration)
        self.assertNotIn("0.0.0.0/0", configuration)
        self.assertNotIn('resource "google_compute_firewall" "ui"', configuration)
        self.assertNotIn("service_account {", configuration)
        self.assertIn('output "grafana_tunnel_command"', outputs)
        self.assertNotIn('output "grafana_url"', outputs)

    def test_startup_and_operator_docs_cover_safe_deployment_and_teardown(self) -> None:
        startup = (TERRAFORM / "startup.sh").read_text(encoding="utf-8")
        deployment = (ROOT / "docs" / "gcp-deployment.md").read_text(encoding="utf-8")

        self.assertIn("systemctl enable --now docker", startup)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", startup)
        self.assertIn("CONTAINERLAB_VERSION", startup)
        self.assertIn("containerlab_${CONTAINERLAB_VERSION}", startup)
        self.assertIn("terraform destroy", deployment)
        self.assertIn("budget", deployment.lower())

    def test_makefile_exposes_offline_format_and_validation_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("terraform-fmt:", makefile)
        self.assertIn("terraform-validate:", makefile)


if __name__ == "__main__":
    unittest.main()
