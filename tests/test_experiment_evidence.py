"""Task 10 immutable experiment-evidence tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluate.experiment import iperf_receiver_samples, write_trial_evidence


class ExperimentEvidenceTests(unittest.TestCase):
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
