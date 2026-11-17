"""Step 9 safety tests for Alertmanager-triggered OSPF remediation."""

from __future__ import annotations

import asyncio
import json
import math
import os
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import httpx

from remediation.actions import OspfCostAdapter
from remediation.app import RemediationConfig, create_app
from remediation.audit import append_audit
from remediation.policy import CooldownPolicy, PolicyError, parse_alertmanager_payload
from remediation.service import RemediationService


class AlertmanagerPolicyTests(unittest.TestCase):
    def test_valid_firing_alert_maps_only_to_an_allowlisted_ospf_target(self) -> None:
        targets = parse_alertmanager_payload(
            {
                "version": "4",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "fingerprint": "alert-1",
                        "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r2"},
                    }
                ],
            }
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].router, "r1")
        self.assertEqual(targets[0].interface, "eth1")
        self.assertEqual(targets[0].link, "r1-r2")

    def test_rejects_malformed_or_unrecognised_alert_targets(self) -> None:
        with self.assertRaises(PolicyError):
            parse_alertmanager_payload({"status": "firing", "alerts": []})
        with self.assertRaises(PolicyError):
            parse_alertmanager_payload(
                {
                    "version": "4",
                    "status": "firing",
                    "alerts": [
                        {
                            "status": "firing",
                            "labels": {"alertname": "NetPulseLinkAnomaly", "link": "h1-r1"},
                        }
                    ],
                }
            )

    def test_cooldown_rejects_duplicate_target_with_monotonic_time(self) -> None:
        policy = CooldownPolicy(cooldown_seconds=30)
        target = parse_alertmanager_payload(
            {
                "version": "4",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r3"},
                    }
                ],
            }
        )[0]

        self.assertTrue(policy.allow(target, now=100.0))
        self.assertFalse(policy.allow(target, now=129.9))
        self.assertTrue(policy.allow(target, now=130.0))

    def test_cooldown_rejects_non_finite_values(self) -> None:
        for value in (math.inf, -math.inf, math.nan):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "finite"):
                CooldownPolicy(cooldown_seconds=value)


class RemediationConfigurationTests(unittest.TestCase):
    def test_environment_rejects_non_finite_cooldown_and_timeout(self) -> None:
        for name in (
            "NETPULSE_REMEDIATION_COOLDOWN_SECONDS",
            "NETPULSE_REMEDIATION_GLOBAL_COOLDOWN_SECONDS",
            "NETPULSE_REMEDIATION_COMMAND_TIMEOUT_SECONDS",
        ):
            with self.subTest(name=name), patch.dict(os.environ, {name: "nan"}, clear=False):
                with self.assertRaisesRegex(ValueError, "finite"):
                    RemediationConfig.from_env()


class OspfCostAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.target = parse_alertmanager_payload(
            {
                "version": "4",
                "status": "firing",
                "alerts": [
                    {
                        "status": "firing",
                        "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r2"},
                    }
                ],
            }
        )[0]

    def test_dry_run_never_invokes_docker(self) -> None:
        def runner(_command: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            self.fail("dry-run must not invoke Docker")

        result = OspfCostAdapter(dry_run=True, runner=runner).apply(self.target)

        self.assertEqual(result.status, "dry-run")
        self.assertEqual(result.rollback_status, "not-needed")
        self.assertIn("ip ospf cost 100", " ".join(result.command))

    def test_live_failure_attempts_allowlisted_rollback_and_preserves_output(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            if "ip ospf cost 100" in command:
                raise subprocess.CalledProcessError(
                    1, command, output="action stdout", stderr="action stderr"
                )
            return subprocess.CompletedProcess(command, 0, stdout="rollback stdout", stderr="")

        result = OspfCostAdapter(dry_run=False, runner=runner).apply(self.target)

        self.assertEqual(result.status, "failed")
        self.assertEqual(result.action_output, "action stdout\naction stderr")
        self.assertEqual(result.rollback_status, "succeeded")
        self.assertEqual(result.rollback_output, "rollback stdout")
        self.assertEqual(len(commands), 2)
        self.assertIn("no ip ospf cost", commands[1])


class AuditTests(unittest.TestCase):
    def test_audit_appends_one_json_record_without_rewriting_prior_records(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "audit.jsonl"
            append_audit(path, {"event": "first"})
            append_audit(path, {"event": "second"})
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

        self.assertEqual(records, [{"event": "first"}, {"event": "second"}])


class RemediationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = {
            "version": "4",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "fingerprint": "alert-1",
                    "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r2"},
                }
            ],
        }

    def test_valid_alert_creates_dry_run_audit_and_status_metrics(self) -> None:
        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=True),
                cooldown_seconds=30,
                audit_path=audit_path,
                monotonic_clock=lambda: 100.0,
            )

            decisions = service.handle(self.payload)
            audit = json.loads(audit_path.read_text(encoding="utf-8"))
            metrics = service.metrics()

        self.assertEqual(decisions[0]["status"], "dry-run")
        self.assertEqual(audit["target"]["router"], "r1")
        self.assertEqual(audit["rollback_status"], "not-needed")
        self.assertIn(
            'netpulse_remediation_actions_total{mode="dry-run",status="dry-run"} 1', metrics
        )
        self.assertIn("netpulse_remediation_last_latency_seconds", metrics)

    def test_duplicate_alert_is_audited_as_cooldown_without_running_again(self) -> None:
        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=True),
                cooldown_seconds=30,
                audit_path=audit_path,
                monotonic_clock=lambda: 100.0,
            )
            service.handle(self.payload)
            decisions = service.handle(self.payload)
            audits = [
                json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(decisions[0]["status"], "cooldown")
        self.assertEqual(audits[-1]["status"], "cooldown")

    def test_global_cooldown_blocks_a_second_link_in_the_same_incident_window(self) -> None:
        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=True),
                cooldown_seconds=30,
                global_cooldown_seconds=30,
                audit_path=audit_path,
                monotonic_clock=lambda: 100.0,
            )
            service.handle(self.payload)
            second_payload = {
                **self.payload,
                "alerts": [
                    {
                        **self.payload["alerts"][0],
                        "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r3"},
                    }
                ],
            }
            decisions = service.handle(second_payload)

        self.assertEqual(decisions[0]["status"], "global-cooldown")

    def test_rejected_payload_is_audited_without_attempting_an_action(self) -> None:
        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=True),
                cooldown_seconds=30,
                audit_path=audit_path,
            )
            with self.assertRaises(PolicyError):
                service.handle({"version": "4", "status": "invalid", "alerts": []})
            audit = json.loads(audit_path.read_text(encoding="utf-8"))

        self.assertEqual(audit["status"], "rejected")

    def test_resolved_alert_rolls_back_a_live_applied_cost(self) -> None:
        commands: list[list[str]] = []

        def runner(command: list[str], _timeout: float) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ok", stderr="")

        with TemporaryDirectory() as directory:
            audit_path = Path(directory) / "audit.jsonl"
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=False, runner=runner),
                cooldown_seconds=30,
                audit_path=audit_path,
                monotonic_clock=lambda: 100.0,
            )
            service.handle(self.payload)
            resolved = {
                **self.payload,
                "status": "resolved",
                "alerts": [{**self.payload["alerts"][0], "status": "resolved"}],
            }
            decisions = service.handle(resolved)
            audits = [
                json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(decisions[0]["status"], "rolled-back")
        self.assertEqual(audits[-1]["status"], "rolled-back")
        self.assertEqual(len(commands), 2)
        self.assertIn("ip ospf cost 100", commands[0])
        self.assertIn("no ip ospf cost", commands[1])


class RemediationHttpTests(unittest.TestCase):
    def test_alert_webhook_exposes_dry_run_decision_and_metrics(self) -> None:
        payload = {
            "version": "4",
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r2"},
                }
            ],
        }
        with TemporaryDirectory() as directory:
            service = RemediationService(
                adapter=OspfCostAdapter(dry_run=True),
                cooldown_seconds=30,
                audit_path=Path(directory) / "audit.jsonl",
            )
            async def exercise_webhook() -> tuple[httpx.Response, httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=create_app(service))
                async with httpx.AsyncClient(
                    transport=transport, base_url="http://netpulse-test"
                ) as client:
                    response = await client.post("/alerts", json=payload)
                    metrics = await client.get("/metrics")
                    rejected = await client.post("/alerts", json={"status": "invalid"})
                return response, metrics, rejected

            response, metrics, rejected = asyncio.run(exercise_webhook())

        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json()["decisions"][0]["status"], "dry-run")
        self.assertIn("netpulse_remediation_actions_total", metrics.text)
        self.assertEqual(rejected.status_code, 400)


if __name__ == "__main__":
    unittest.main()
