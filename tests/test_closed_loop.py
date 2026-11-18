"""Contracts for the explicit end-to-end closed-loop trial."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from evaluate.closed_loop import (
    ClosedLoopConfig,
    require_live_mode,
    require_trial_detection_profile,
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
        self.assertIn("ip ospf cost 20", commands["route_bias"])

    def test_rejects_unsafe_run_ids_and_short_observation_windows(self) -> None:
        with self.assertRaisesRegex(ValueError, "run_id"):
            ClosedLoopConfig(run_id="unsafe/run")
        with self.assertRaisesRegex(ValueError, "post_action"):
            ClosedLoopConfig(run_id="closed-loop-001", post_action_seconds=0)

    def test_requires_the_reviewed_detector_threshold_before_fault_injection(self) -> None:
        config = ClosedLoopConfig(run_id="closed-loop-profile")
        with self.assertRaisesRegex(ValueError, "threshold"):
            require_trial_detection_profile(
                'netpulse_anomaly_threshold{link="r1-r2"} 0.1\n', config
            )
        require_trial_detection_profile(
            'netpulse_anomaly_threshold{link="r1-r2"} 0.01\n', config
        )
        require_trial_detection_profile(
            'netpulse_anomaly_threshold{link="unknown"} 0.01\n', config
        )

    def test_rejects_existing_run_before_contacting_live_services(self) -> None:
        with TemporaryDirectory() as directory:
            runs_root = Path(directory)
            (runs_root / "already-used").mkdir()
            with self.assertRaisesRegex(ValueError, "run_id"):
                run_closed_loop_trial(
                    config=ClosedLoopConfig(run_id="already-used"),
                    runs_root=runs_root,
                    runner=lambda *_args, **_kwargs: self.fail("no command should run"),
                )

    def test_rejects_an_action_that_arrives_before_the_fault(self) -> None:
        now = [0.0]
        audit_calls = [0]
        commands: list[list[str]] = []

        def runner(command: list[str], **_kwargs: object) -> object:
            import json
            import subprocess

            commands.append(command)
            stdout = ""
            if command[:4] == ["docker", "compose", "exec", "-T"]:
                audit_calls[0] += 1
                records = []
                if audit_calls[0] == 2:
                    records = [
                        {
                            "status": "applied",
                            "timestamp": "2026-11-18T00:00:00+00:00",
                            "target": {"link": "r1-r2"},
                        }
                    ]
                stdout = "".join(json.dumps(record) + "\n" for record in records)
            elif command[-1:] == ["show ip route 10.0.4.0/24 json"]:
                stdout = '{"10.0.4.0/24":[{"nexthops":[{"interfaceName":"eth1"}]}]}'
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        config = ClosedLoopConfig(
            run_id="closed-loop-pre-fault-action",
            baseline_seconds=1,
            detection_timeout_seconds=1,
            rollback_timeout_seconds=1,
            post_action_seconds=1,
        )
        metrics = 'netpulse_anomaly_threshold{link="unknown"} 0.01\n'
        with (
            TemporaryDirectory() as directory,
            patch("evaluate.closed_loop._get_json", return_value={"status": "ok", "mode": "live"}),
            patch("evaluate.closed_loop._get_text", return_value=metrics),
            self.assertRaisesRegex(ValueError, "before fault injection"),
        ):
            run_closed_loop_trial(
                config=config,
                runs_root=Path(directory),
                runner=runner,
                clock=lambda: now[0],
                sleeper=lambda seconds: now.__setitem__(0, now[0] + seconds),
            )

        self.assertFalse(any("netem" in command and "replace" in command for command in commands))

    def test_publishes_evidence_only_after_detection_action_rollback_and_restoration(self) -> None:
        now = [0.0]
        audit_calls = [0]
        route_calls = [0]
        qdisc_deletes = [0]
        commands: list[list[str]] = []
        receiver = {
            "start": {"timestamp": {"timesecs": 0}},
            "intervals": [
                {"sum": {"end": end, "bits_per_second": 25_000_000.0}}
                for end in range(1, 31)
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
            if command[:6] == [
                "docker",
                "exec",
                "clab-netpulse-r1",
                "tc",
                "qdisc",
                "del",
            ]:
                qdisc_deletes[0] += 1
                if qdisc_deletes[0] > 1:
                    return subprocess.CompletedProcess(
                        command,
                        2,
                        stdout="",
                        stderr="Error: Invalid qdisc name: must match existing qdisc.",
                    )
            stdout = ""
            if command[:4] == ["docker", "compose", "exec", "-T"]:
                audit_calls[0] += 1
                records = []
                if audit_calls[0] > 2:
                    records.append(
                        {
                            "status": "applied",
                            "timestamp": "2026-11-18T00:00:00+00:00",
                            "target": {"link": "r1-r2"},
                        }
                    )
                if audit_calls[0] > 3:
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
                route_calls[0] += 1
                interface = "eth1" if route_calls[0] == 1 else "eth2"
                stdout = json.dumps(
                    {"10.0.4.0/24": [{"nexthops": [{"interfaceName": interface}]}]}
                )
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
            'netpulse_anomaly_threshold{link="r1-r2"} 0.01\n'
        )
        config = ClosedLoopConfig(
            run_id="closed-loop-contract",
            baseline_seconds=2,
            detection_timeout_seconds=1,
            rollback_timeout_seconds=1,
            post_action_seconds=1,
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
