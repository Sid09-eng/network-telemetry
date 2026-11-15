"""Task 10 immutable experiment-evidence tests."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate.experiment import iperf_receiver_samples, run_paired_trial, write_trial_evidence


class ExperimentEvidenceTests(unittest.TestCase):
    def test_paired_trial_rejects_an_unsafe_run_id_before_running_commands(self) -> None:
        def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
            self.fail("unsafe run IDs must be rejected before any command is executed")

        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "run_id"):
                run_paired_trial(
                    run_id="trial; unexpected-command",
                    remediated=False,
                    runs_root=Path(directory),
                    runner=runner,
                )

    def test_paired_trial_rejects_a_dry_run_webhook_as_remediation(self) -> None:
        receiver = {"start": {"timestamp": {"timesecs": 1}}, "intervals": []}

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            stdout = ""
            if command[0] == "curl":
                stdout = '{"mode":"dry-run","decisions":[{"status":"dry-run"}]}'
            elif "cat" in command:
                stdout = json.dumps(receiver)
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "live applied"):
                run_paired_trial(
                    run_id="task10-dry-run",
                    remediated=True,
                    runs_root=Path(directory),
                    duration_seconds=8,
                    baseline_seconds=1,
                    impairment_seconds=6,
                    runner=runner,
                    sleeper=lambda _seconds: None,
                )

    def test_paired_trial_records_a_confirmed_live_action(self) -> None:
        receiver = {"start": {"timestamp": {"timesecs": 1}}, "intervals": []}

        def runner(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            stdout = ""
            if command[0] == "curl":
                stdout = '{"mode":"live","decisions":[{"status":"applied"}]}'
            elif "cat" in command:
                stdout = json.dumps(receiver)
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")

        with TemporaryDirectory() as directory:
            root = Path(directory)
            run_paired_trial(
                run_id="task10-live",
                remediated=True,
                runs_root=root,
                duration_seconds=8,
                baseline_seconds=1,
                impairment_seconds=6,
                runner=runner,
                sleeper=lambda _seconds: None,
            )
            events = json.loads((root / "task10-live" / "events.json").read_text())

        self.assertEqual(events["remediation"], {"mode": "live", "status": "applied"})

    def test_receiver_intervals_become_timestamped_throughput_samples(self) -> None:
        raw = {
            "start": {"timestamp": {"timesecs": 100}},
            "intervals": [
                {"sum": {"end": 1.5, "bits_per_second": 10.0}},
                {"sum": {"end": 2.5, "bits_per_second": 20.0}},
            ],
        }
        samples = iperf_receiver_samples(raw)
        values = [(sample.timestamp, sample.bits_per_second) for sample in samples]
        self.assertEqual(values, [(101.5, 10.0), (102.5, 20.0)])

    def test_evidence_is_published_atomically_with_manifest_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "topology.yml"
            config.write_text("topology", encoding="utf-8")
            manifest = write_trial_evidence(
                runs_root=root / "runs",
                run_id="task10-control",
                raw_iperf={"start": {"timestamp": {"timesecs": 1}}, "intervals": []},
                events={"fault_start": 2.0},
                config_paths=[config],
            )
            run_dir = root / "runs" / "task10-control"
            self.assertTrue((run_dir / "raw" / "iperf-receiver.json").is_file())
            events = json.loads((run_dir / "events.json").read_text())
            self.assertEqual(events, {"fault_start": 2.0})
            self.assertEqual(manifest["configuration_hashes"].keys(), {"topology.yml"})


if __name__ == "__main__":
    unittest.main()
