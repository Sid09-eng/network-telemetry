"""Step 5 repeatable-traffic and fault-ground-truth tests."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from traffic.faults import FaultEvent, apply_fault, load_scenario
from traffic.generate import build_schedule, iperf_command


class TrafficScheduleTests(unittest.TestCase):
    def test_traffic_hosts_are_built_with_iperf3_before_topology_deploy(self) -> None:
        root = Path(__file__).resolve().parents[1]
        host_dockerfile = (root / "traffic" / "host.Dockerfile").read_text(encoding="utf-8")
        topology = (root / "topology" / "netpulse.clab.yml").read_text(encoding="utf-8")
        makefile = (root / "Makefile").read_text(encoding="utf-8")

        self.assertIn("apk add --no-cache iperf3=3.19.1-r0", host_dockerfile)
        self.assertIn("image: netpulse-traffic-host:0.1.0", topology)
        self.assertIn("topology-up: traffic-host-image", makefile)

    def test_same_seed_and_scenario_produce_the_same_compressed_day_schedule(self) -> None:
        first = build_schedule(
            seed=17,
            compressed_day_seconds=120,
            target_rate_mbps=25,
            scenario_id="diamond-failover",
        )
        second = build_schedule(
            seed=17,
            compressed_day_seconds=120,
            target_rate_mbps=25,
            scenario_id="diamond-failover",
        )

        self.assertEqual(first, second)
        self.assertTrue(first)
        self.assertTrue(all(event.rate_bps <= 25_000_000 for event in first))
        self.assertEqual(first[0].scenario_id, "diamond-failover")

    def test_schedule_preserves_requested_whole_second_duration(self) -> None:
        schedule = build_schedule(
            seed=17,
            compressed_day_seconds=60,
            target_rate_mbps=25,
            scenario_id="diamond-failover",
        )

        self.assertEqual(sum(event.duration_seconds for event in schedule), 60)
        self.assertEqual(schedule[-1].start_offset_seconds + schedule[-1].duration_seconds, 60)
        self.assertEqual(
            sum(int(iperf_command(event)[-1]) for event in schedule),
            60,
        )

    def test_client_command_uses_only_client_compatible_iperf_options(self) -> None:
        event = build_schedule(
            seed=17,
            compressed_day_seconds=120,
            target_rate_mbps=25,
            scenario_id="diamond-failover",
        )[0]

        command = iperf_command(event)

        self.assertIn("--client", command)
        self.assertIn("--udp", command)
        self.assertNotIn("--one-off", command)


class FaultGroundTruthTests(unittest.TestCase):
    def test_scenario_expands_a_declared_link_recovery(self) -> None:
        scenario = Path(__file__).resolve().parents[1] / "traffic/scenarios/diamond-failover.yaml"

        events = load_scenario(scenario)

        self.assertEqual([event.action for event in events], ["link_down", "link_up"])
        self.assertEqual([event.planned_offset_seconds for event in events], [60.0, 80.0])
        self.assertEqual(events[1].parameters, {"recovery_for": "r1-r2-down"})

    def test_second_endpoint_failure_is_rolled_back_and_logged(self) -> None:
        event = FaultEvent(
            event_id="r1-r2-down",
            planned_offset_seconds=30,
            link="r1-r2",
            action="link_down",
            parameters={"restore_after_seconds": 20},
        )
        planned_at = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

        def runner(command: list[str]) -> None:
            if "clab-netpulse-r2" in command:
                raise RuntimeError("simulated Docker failure")

        with TemporaryDirectory() as directory:
            log_path = Path(directory) / "faults.jsonl"
            result = apply_fault(
                event,
                runner=runner,
                log_path=log_path,
                planned_at=planned_at,
                clock=lambda: planned_at,
            )
            logged = json.loads(log_path.read_text(encoding="utf-8"))

        self.assertEqual(result["outcome"], "unapplied")
        self.assertIsNone(result["applied_at"])
        self.assertEqual(logged["planned_at"], "2026-11-15T12:00:00+00:00")
        self.assertEqual(logged["target_link"], "r1-r2")
        self.assertEqual(logged["action"], "link_down")
        self.assertEqual(logged["parameters"], {"restore_after_seconds": 20})
        self.assertEqual(logged["outcome"], "unapplied")
        self.assertEqual(logged["rollback"], "succeeded")
        self.assertEqual(logged["applied_endpoints"], ["clab-netpulse-r1"])
        self.assertEqual(logged["rollback_endpoints"], ["clab-netpulse-r1"])

    def test_rollback_failure_is_logged_as_a_partial_failure(self) -> None:
        event = FaultEvent(
            event_id="r1-r2-down",
            planned_offset_seconds=30,
            link="r1-r2",
            action="link_down",
            parameters={},
        )
        planned_at = datetime(2026, 11, 15, 12, 0, tzinfo=UTC)

        def runner(command: list[str]) -> None:
            if "clab-netpulse-r2" in command or command[-1] == "up":
                raise RuntimeError("simulated Docker failure")

        with TemporaryDirectory() as directory:
            result = apply_fault(
                event,
                runner=runner,
                log_path=Path(directory) / "faults.jsonl",
                planned_at=planned_at,
            )

        self.assertEqual(result["outcome"], "partial-failure")
        self.assertEqual(result["rollback"], "failed")
        self.assertEqual(result["applied_endpoints"], ["clab-netpulse-r1"])
        self.assertEqual(result["rollback_endpoints"], [])


if __name__ == "__main__":
    unittest.main()
