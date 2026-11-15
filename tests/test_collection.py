"""Task 6 telemetry collection and immutable-run tests."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from forecast.collect import query_range, write_run
from forecast.schema import SchemaError, validate_prometheus_matrix
from forecast.train import render_markdown

RANGE_RESPONSE = {
    "status": "success",
    "data": {
        "resultType": "matrix",
        "result": [
            {
                "metric": {
                    "__name__": "router_interface:transmit_bits:rate1m",
                    "router": "r1",
                    "interface": "eth1",
                    "link": "r1-r2",
                },
                "values": [["1794728000.0", "12500000"], ["1794728005.0", "13000000"]],
            }
        ],
    },
}


class TelemetrySchemaTests(unittest.TestCase):
    def test_validates_prometheus_matrix_into_finite_labeled_observations(self) -> None:
        samples = validate_prometheus_matrix(RANGE_RESPONSE)

        self.assertEqual(len(samples), 2)
        self.assertEqual(samples[0].router, "r1")
        self.assertEqual(samples[1].value, 13_000_000.0)

    def test_rejects_missing_required_link_label(self) -> None:
        invalid = json.loads(json.dumps(RANGE_RESPONSE))
        del invalid["data"]["result"][0]["metric"]["link"]

        with self.assertRaisesRegex(SchemaError, "link"):
            validate_prometheus_matrix(invalid)


class CollectionTests(unittest.TestCase):
    def test_collector_help_runs_as_documented_script(self) -> None:
        root = Path(__file__).resolve().parents[1]

        completed = subprocess.run(
            [sys.executable, str(root / "forecast" / "collect.py"), "--help"],
            check=False,
            capture_output=True,
            text=True,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("immutable NetPulse run", completed.stdout)

    def test_range_query_encodes_parameters(self) -> None:
        requested: list[str] = []

        class Response:
            def read(self) -> bytes:
                return json.dumps(RANGE_RESPONSE).encode("utf-8")

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        def opener(request: object, timeout: float) -> Response:
            requested.append(request.full_url)  # type: ignore[attr-defined]
            self.assertEqual(timeout, 15)
            return Response()

        response = query_range(
            "http://prometheus:9090",
            query='router_interface:transmit_bits:rate1m{router="r1"}',
            start=100,
            end=200,
            step=5,
            opener=opener,
        )

        self.assertEqual(response, RANGE_RESPONSE)
        self.assertIn("query=router_interface%3Atransmit_bits%3Arate1m", requested[0])
        self.assertIn("start=100", requested[0])
        self.assertIn("end=200", requested[0])
        self.assertIn("step=5", requested[0])

    def test_writes_immutable_run_with_raw_response_faults_and_config_hashes(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "prometheus.yml"
            config.write_text("scrape_interval: 5s\n", encoding="utf-8")
            faults = root / "faults.jsonl"
            faults.write_text('{"outcome":"dry-run"}\n', encoding="utf-8")
            samples = validate_prometheus_matrix(RANGE_RESPONSE)

            manifest = write_run(
                runs_root=root / "runs",
                run_id="demo-001",
                raw_response=RANGE_RESPONSE,
                samples=samples,
                query={"query": "example", "start": 100, "end": 200, "step": 5},
                config_paths=[config],
                fault_log=faults,
            )

            run_dir = root / "runs" / "demo-001"
            self.assertEqual(manifest["sample_count"], 2)
            self.assertEqual(manifest["fault_ground_truth"], "faults/faults.jsonl")
            self.assertIn("prometheus.yml", manifest["configuration_hashes"])
            self.assertTrue((run_dir / "raw" / "prometheus-range.json").is_file())
            self.assertTrue((run_dir / "telemetry.jsonl").is_file())
            self.assertTrue((run_dir / "faults" / "faults.jsonl").is_file())
            with self.assertRaises(FileExistsError):
                write_run(
                    runs_root=root / "runs",
                    run_id="demo-001",
                    raw_response=RANGE_RESPONSE,
                    samples=samples,
                    query={},
                    config_paths=[],
                )

    def test_validation_failure_does_not_reserve_the_run_id(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            samples = validate_prometheus_matrix(RANGE_RESPONSE)

            with self.assertRaisesRegex(FileNotFoundError, "configuration file not found"):
                write_run(
                    runs_root=root / "runs",
                    run_id="retryable-run",
                    raw_response=RANGE_RESPONSE,
                    samples=samples,
                    query={},
                    config_paths=[root / "missing-prometheus.yml"],
                )

            self.assertFalse((root / "runs" / "retryable-run").exists())

    def test_missing_fault_log_does_not_reserve_the_run_id(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            samples = validate_prometheus_matrix(RANGE_RESPONSE)

            with self.assertRaisesRegex(FileNotFoundError, "fault log not found"):
                write_run(
                    runs_root=root / "runs",
                    run_id="retryable-fault-run",
                    raw_response=RANGE_RESPONSE,
                    samples=samples,
                    query={},
                    config_paths=[],
                    fault_log=root / "missing-faults.jsonl",
                )

            self.assertFalse((root / "runs" / "retryable-fault-run").exists())

    def test_forecast_report_records_source_manifest_hash(self) -> None:
        manifest_hash = "a" * 64
        chronological = {
            "folds": [
                {"metrics": {"persistence": {"mae": 0.1, "rmse": 0.2}}},
            ]
        }
        transfer = {
            "held_out_links": {
                "r1-r2": {"persistence": {"mae": 0.3, "rmse": 0.4}},
            }
        }

        report = render_markdown(
            run_id="demo-001",
            manifest_sha256=manifest_hash,
            chronological=chronological,
            transfer=transfer,
        )

        self.assertIn(f"Source manifest SHA-256: `{manifest_hash}`.", report)


if __name__ == "__main__":
    unittest.main()
