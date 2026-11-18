"""Contracts for the continuous Prometheus-to-detector inference worker."""

from __future__ import annotations

import unittest

from forecast.features import Observation
from forecast.worker import (
    InferenceConfig,
    InferenceWorker,
    observations_from_prometheus_responses,
    observations_from_prometheus_vector,
)


def observation(timestamp: float, value: float) -> Observation:
    return Observation(
        timestamp=timestamp,
        router="r1",
        interface="eth1",
        link="r1-r2",
        value=value,
    )


def second_endpoint_observation(timestamp: float, value: float) -> Observation:
    return Observation(
        timestamp=timestamp,
        router="r2",
        interface="eth1",
        link="r1-r2",
        value=value,
    )


class InferenceWorkerTests(unittest.TestCase):
    def test_uses_source_timestamps_and_rejects_stale_prometheus_samples(self) -> None:
        utilisation = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "__name__": "router_interface:transmit_utilisation_ratio:rate1m",
                            "router": "r1",
                            "interface": "eth1",
                            "link": "r1-r2",
                        },
                        "value": ["100", "0.4"],
                    }
                ],
            },
        }
        source_timestamp = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {"router": "r1", "interface": "eth1", "link": "r1-r2"},
                        "value": ["100", "95"],
                    }
                ],
            },
        }

        self.assertEqual(
            observations_from_prometheus_responses(
                utilisation, source_timestamp, max_sample_age_seconds=10
            ),
            [observation(95.0, 0.4)],
        )
        source_timestamp["data"]["result"][0]["value"][1] = "80"
        self.assertEqual(
            observations_from_prometheus_responses(
                utilisation, source_timestamp, max_sample_age_seconds=10
            ),
            [],
        )

    def test_publishes_residuals_after_warmup_and_clears_detector_state(self) -> None:
        cycles = iter([[observation(index * 5.0, 0.4)] for index in range(15)])
        published: list[object] = []
        configured: list[float] = []
        worker = InferenceWorker(
            InferenceConfig(
                prometheus_url="http://prometheus:9090",
                detector_url="http://detector:8001",
                poll_seconds=5.0,
                threshold=0.1,
            ),
            collector=lambda: next(cycles),
            configure_threshold=lambda threshold: configured.append(threshold),
            publisher=lambda detections: published.append(detections),
        )

        for _ in range(13):
            self.assertEqual(worker.poll_once(), [])
        self.assertEqual(configured, [0.1])

        anomaly = worker.poll_once()
        self.assertEqual(len(anomaly), 1)
        self.assertAlmostEqual(anomaly[0].score, 0.0)
        self.assertFalse(anomaly[0].active)

        # A sharp utilization reduction in the following interval must be scored and published.
        cycles = iter([[observation(70.0, 0.05)]])
        detected = worker.poll_once()
        self.assertEqual(len(detected), 1)
        self.assertAlmostEqual(detected[0].score, 0.35)
        self.assertTrue(detected[0].active)
        self.assertEqual(len(published), 2)

    def test_gap_drops_a_stale_prediction_instead_of_scoring_it(self) -> None:
        cycles = iter(
            [[observation(index * 5.0, 0.4)] for index in range(13)]
            + [[observation(70.0, 0.1)]]
        )
        worker = InferenceWorker(
            InferenceConfig(
                prometheus_url="http://prometheus:9090",
                detector_url="http://detector:8001",
                poll_seconds=5.0,
                threshold=0.1,
            ),
            collector=lambda: next(cycles),
            configure_threshold=lambda _threshold: None,
            publisher=lambda _detections: None,
        )

        for _ in range(13):
            worker.poll_once()
        self.assertEqual(worker.poll_once(), [])

    def test_prediction_timestamp_rejects_epoch_sized_relative_tolerance(self) -> None:
        epoch = 1_700_000_000.0
        cycles = iter(
            [[observation(epoch + index * 5.0, 0.4)] for index in range(13)]
            + [[observation(epoch + 66.5, 0.1)]]
        )
        worker = InferenceWorker(
            InferenceConfig(
                prometheus_url="http://prometheus:9090",
                detector_url="http://detector:8001",
                poll_seconds=5.0,
                threshold=0.1,
            ),
            collector=lambda: next(cycles),
            configure_threshold=lambda _threshold: None,
            publisher=lambda _detections: None,
        )

        for _ in range(13):
            worker.poll_once()
        self.assertEqual(worker.poll_once(), [])

    def test_tolerates_normal_polling_jitter_without_breaking_feature_history(self) -> None:
        cycles = iter([[observation(index * 5.1, 0.4)] for index in range(14)])
        worker = InferenceWorker(
            InferenceConfig(
                prometheus_url="http://prometheus:9090",
                detector_url="http://detector:8001",
                poll_seconds=5.0,
                threshold=0.1,
            ),
            collector=lambda: next(cycles),
            configure_threshold=lambda _threshold: None,
            publisher=lambda _detections: None,
        )

        for _ in range(13):
            worker.poll_once()
        self.assertEqual(len(worker.poll_once()), 1)

    def test_collapses_directional_residuals_to_the_highest_link_score(self) -> None:
        cycles = iter(
            [
                [observation(index * 5.0, 0.4), second_endpoint_observation(index * 5.0, 0.4)]
                for index in range(13)
            ]
            + [[observation(65.0, 0.05), second_endpoint_observation(65.0, 0.35)]]
        )
        worker = InferenceWorker(
            InferenceConfig(
                prometheus_url="http://prometheus:9090",
                detector_url="http://detector:8001",
                poll_seconds=5.0,
                threshold=0.1,
            ),
            collector=lambda: next(cycles),
            configure_threshold=lambda _threshold: None,
            publisher=lambda _detections: None,
        )

        for _ in range(13):
            worker.poll_once()
        detections = worker.poll_once()

        self.assertEqual(len(detections), 1)
        self.assertEqual(detections[0].link, "r1-r2")
        self.assertAlmostEqual(detections[0].score, 0.35)
        self.assertTrue(detections[0].active)

    def test_validates_prometheus_vector_labels_and_values(self) -> None:
        response = {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [
                    {
                        "metric": {
                            "__name__": "router_interface:transmit_utilisation_ratio:rate1m",
                            "router": "r1",
                            "interface": "eth1",
                            "link": "r1-r2",
                        },
                        "value": ["10", "0.4"],
                    }
                ],
            },
        }

        samples = observations_from_prometheus_vector(response)

        self.assertEqual(samples, [observation(10.0, 0.4)])
        response["data"]["result"][0]["metric"].pop("link")
        with self.assertRaisesRegex(ValueError, "link"):
            observations_from_prometheus_vector(response)
