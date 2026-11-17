"""Contracts for the explicit end-to-end closed-loop trial."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from evaluate.closed_loop import (
    ClosedLoopConfig,
    require_live_mode,
    run_closed_loop_trial,
    trial_commands,
)


class ClosedLoopTrialTests(unittest.TestCase):
    def test_requires_explicit_live_remediation_before_any_fault_command(self) -> None:
        with self.assertRaisesRegex(ValueError, "live"):
            require_live_mode({"status": "ok", "mode": "dry-run"})

    def test_uses_an_egress_rate_fault_and_always_has_cleanup_commands(self) -> None:
        commands = trial_commands(ClosedLoopConfig(run_id="closed-loop-001"))

        self.assertIn(
            [
                "docker",
                "exec",
                "clab-netpulse-r1",
                "tc",
                "qdisc",
                "replace",
                "dev",
                "eth1",
                "root",
                "netem",
                "rate",
                "1mbit",
            ],
            commands["impair"],
        )
        self.assertIn("no ip ospf cost", commands["cleanup"][1])
        self.assertIn("interface eth2", commands["route_bias"])

    def test_rejects_unsafe_run_ids_and_short_observation_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id"):
            ClosedLoopConfig(run_id="unsafe/run")
        with self.assertRaisesRegex(ValueError, "post_action"):
            ClosedLoopConfig(run_id="closed-loop-001", post_action_seconds=0)

    def test_publishes_evidence_only_after_detection_action_rollback_and_restoration(self) -> None:
        now = [0.0]
        audit_calls = [0]
        commands: list[list[str]] = []
        receiver = {
            "start": {"timestamp": {"timesecs": 0}},
            "intervals": [
                {"sum": {"end": end, "bits_per_second": 25_000_000.0}}
                for end in (0.5, 1.5, 2.5, 3.5, 4.5)
            ],
        }

        def clock() -> float:
            return now[0]

        def sleeper(seconds: float) -> None:
            now[0] += seconds

        def runner(command: list[str], **_kwargs: object) -> object:
            import json
            import subprocess

            commands.append(command)
            stdout = ""
            if command[:4] == ["docker", "compose", "exec", "-T"]:
                audit_calls[0] += 1
                records = [
                    {
                        "status": "applied",
                        "timestamp": "2026-11-18T00:00:00+00:00",
                        "target": {"link": "r1-r2"},
                    }
                ]
                if audit_calls[0] > 1:
                    records.append(
                        {
                            "status": "rolled-back",
                            "timestamp": "2026-11-18T00:00:01+00:00",
                            "target": {"link": "r1-r2"},
                        }
                    )
                stdout = "".join(json.dumps(record) + "\n" for record in records)
            elif command[:5] == ["docker", "exec", "clab-netpulse-h2", "cat", "/tmp"]:
                stdout = json.dumps(receiver)
            elif command[:4] == ["docker", "exec", "clab-netpulse-h2", "cat"]:
                stdout = json.dumps(receiver)
            elif command[-1:] == ["show ip route 10.0.4.0/24 json"]:
                stdout = "{}"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        health = {"status": "ok", "mode": "live"}
        alerts = {
            "data": {
                "alerts": [
                    {
                        "state": "firing",
                        "labels": {"alertname": "NetPulseLinkAnomaly", "link": "r1-r2"},
                    }
                ]
            }
        }
        detector_metrics = (
            'netpulse_anomaly_active{link="r1-r2"} 1\n'
            'netpulse_anomaly_residual{link="r1-r2"} -0.2\n'
        )
        config = ClosedLoopConfig(
            run_id="closed-loop-contract", baseline_seconds=2, post_action_seconds=1
        )

        with (
            TemporaryDirectory() as directory,
            patch("evaluate.closed_loop._get_json", side_effect=[health, alerts]),
            patch("evaluate.closed_loop._get_text", return_value=detector_metrics),
        ):
            manifest = run_closed_loop_trial(
                config=config,
                runs_root=Path(directory),
                runner=runner,
                clock=clock,
                sleeper=sleeper,
            )
            run_dir = Path(directory) / config.run_id
            alert_snapshot_written = (run_dir / "raw" / "prometheus-alerts.json").is_file()

        self.assertIn("raw/recovery.json", manifest["artifact_hashes"])
        self.assertTrue(alert_snapshot_written)
        self.assertTrue(any("netem" in command for command in commands))
        self.assertTrue(any("no ip ospf cost" in command for command in commands))


if __name__ == "__main__":
    unittest.main()
