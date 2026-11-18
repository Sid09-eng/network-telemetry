"""Offline contracts for the Step 11 Terraform foundation."""

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
        self.assertIn("service_account {", configuration)
        self.assertIn("email  = null", configuration)
        self.assertIn("scopes = []", configuration)
        self.assertIn("ignore_changes = [metadata_startup_script]", configuration)
        self.assertIn('output "grafana_tunnel_command"', outputs)
        self.assertNotIn('output "grafana_url"', outputs)

    def test_vm_alerts_are_scoped_to_the_terraform_managed_instance(self) -> None:
        configuration = (TERRAFORM / "main.tf").read_text(encoding="utf-8")
        variables = (TERRAFORM / "variables.tf").read_text(encoding="utf-8")
        example = (TERRAFORM / "terraform.tfvars.example").read_text(encoding="utf-8")
        deployment = (ROOT / "docs" / "gcp-deployment.md").read_text(encoding="utf-8")

        self.assertIn('resource "google_monitoring_alert_policy" "vm_unavailable"', configuration)
        self.assertIn('resource "google_monitoring_alert_policy" "cpu_saturation"', configuration)
        self.assertIn("condition_absent", configuration)
        self.assertIn("condition_threshold", configuration)
        self.assertIn("compute.googleapis.com/instance/cpu/utilization", configuration)
        self.assertIn("google_compute_instance.netpulse.instance_id", configuration)
        self.assertIn("google_monitoring_notification_channel", configuration)
        self.assertIn("alert_notification_email", variables)
        self.assertIn("alert_notification_email", example)
        self.assertIn("Cloud Monitoring", deployment)

    def test_startup_and_operator_docs_cover_safe_deployment_and_teardown(self) -> None:
        startup = (TERRAFORM / "startup.sh").read_text(encoding="utf-8")
        deployment = (ROOT / "docs" / "gcp-deployment.md").read_text(encoding="utf-8")

        self.assertIn("systemctl enable --now docker", startup)
        self.assertIn("apt-get install -y ca-certificates curl git make python3", startup)
        self.assertNotIn("GOOGLE_APPLICATION_CREDENTIALS", startup)
        self.assertIn("CONTAINERLAB_VERSION", startup)
        self.assertIn("containerlab_${CONTAINERLAB_VERSION}", startup)
        self.assertIn("/opt/netpulse/app", startup)
        self.assertIn("terraform destroy", deployment)
        self.assertIn("budget", deployment.lower())
        self.assertIn("gcloud auth application-default login", deployment)
        self.assertIn("gcloud auth login", deployment)
        self.assertIn("sudo make topology-up", deployment)
        self.assertIn("sudo make topology-check", deployment)
        self.assertIn("sudo make monitoring-up", deployment)

    def test_makefile_exposes_offline_format_and_validation_targets(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        self.assertIn("terraform-fmt:", makefile)
        self.assertIn("terraform-validate:", makefile)


if __name__ == "__main__":
    unittest.main()
