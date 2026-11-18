"""Step 4 monitoring-stack configuration contracts."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class MonitoringStackContractTests(unittest.TestCase):
    def test_compose_keeps_monitoring_separate_and_adds_router_namespace_exporters(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

        for service in (
            "prometheus:",
            "grafana:",
            "alertmanager:",
            "detector:",
            "forecaster:",
            "remediation:",
            "exporter-r1:",
            "exporter-r2:",
            "exporter-r3:",
            "exporter-r4:",
        ):
            self.assertIn(service, compose)
        self.assertIn('network_mode: "container:clab-netpulse-r1"', compose)
        self.assertIn("external: true", compose)
        self.assertIn("name: netpulse-mgmt", compose)
        self.assertIn("monitoring-up:", makefile)
        self.assertIn("docker compose up", makefile)
        self.assertNotIn("containerlab", makefile.split("monitoring-up:", 1)[1].split("\n\n", 1)[0])

    def test_monitoring_is_provisioned_with_alertmanager_and_grafana_assets(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        live_compose = (ROOT / "docker-compose.live.yml").read_text(encoding="utf-8")
        prometheus = (ROOT / "monitoring" / "prometheus.yml").read_text(encoding="utf-8")
        alertmanager = (ROOT / "monitoring" / "alertmanager.yml").read_text(encoding="utf-8")
        datasource = (
            ROOT / "monitoring" / "grafana" / "provisioning" / "datasources" / "prometheus.yml"
        ).read_text(encoding="utf-8")
        dashboard_provider = (
            ROOT / "monitoring" / "grafana" / "provisioning" / "dashboards" / "dashboards.yml"
        ).read_text(encoding="utf-8")
        dashboard = json.loads(
            (ROOT / "monitoring" / "grafana" / "dashboards" / "link-overview.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertIn("alertmanagers:", prometheus)
        self.assertIn("alertmanager:9093", prometheus)
        self.assertIn("job_name: netpulse-remediation", prometheus)
        self.assertIn("remediation:8000", prometheus)
        self.assertIn("http://remediation:8000/alerts", alertmanager)
        self.assertIn("receiver: discard", alertmanager)
        self.assertIn('link="r1-r2"', alertmanager)
        alert_rules = (ROOT / "monitoring" / "alert_rules.yml").read_text(encoding="utf-8")
        self.assertIn("netpulse_anomaly_residual < 0", alert_rules)
        self.assertIn("NETPULSE_ENABLE_LIVE_ACTIONS", compose)
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock", compose)
        self.assertIn("/var/run/docker.sock:/var/run/docker.sock", live_compose)
        self.assertIn("http://prometheus:9090", datasource)
        self.assertIn("/var/lib/grafana/dashboards", dashboard_provider)
        self.assertEqual(dashboard["uid"], "netpulse-link-overview")
        self.assertEqual(dashboard["title"], "NetPulse Link Overview")


if __name__ == "__main__":
    unittest.main()
