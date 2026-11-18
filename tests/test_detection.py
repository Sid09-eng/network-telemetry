"""Step 8 residual anomaly scoring and fault-matching tests."""

from __future__ import annotations

import unittest
from http.server import ThreadingHTTPServer
from threading import Thread
from urllib.request import Request, urlopen

from detector.app import DetectorState, Handler
from forecast.detect import (
    Detection,
    FaultInterval,
    configure_detector_threshold,
    evaluate_detections,
    publish_detections,
    score_residuals,
    select_threshold,
)


class AnomalyScoringTests(unittest.TestCase):
    def test_threshold_is_selected_only_from_validation_residuals(self) -> None:
        threshold = select_threshold([0.1, 0.2, 0.3, 0.4], quantile=0.75)

        self.assertEqual(threshold, 0.3)
        detections = score_residuals(
            timestamps=[10.0, 15.0],
            links=["r1-r2", "r1-r2"],
            actual=[0.2, 10.0],
            predicted=[0.0, 0.0],
            threshold=threshold,
        )
        self.assertEqual([detection.active for detection in detections], [False, True])

    def test_detector_publishing_configures_validation_threshold_then_scores(self) -> None:
        requests: list[object] = []

        class Response:
            status = 200

            def __enter__(self) -> Response:
                return self

            def __exit__(self, *_args: object) -> None:
                return None

        def opener(request: object, *, timeout: float) -> Response:
            self.assertEqual(timeout, 2.0)
            requests.append(request)
            return Response()

        threshold = select_threshold([0.1, 0.2, 0.3], quantile=0.95)
        detections = score_residuals(
            timestamps=[10.0, 15.0],
            links=["r1-r2", "r1-r3"],
            actual=[0.2, 0.8],
            predicted=[0.0, 0.0],
            threshold=threshold,
        )

        configure_detector_threshold(
            detector_url="http://detector:8001", threshold=threshold, opener=opener
        )
        publish_detections(
            detector_url="http://detector:8001", detections=detections, opener=opener
        )

        urls = [request.full_url for request in requests]  # type: ignore[attr-defined]
        payloads = [request.data for request in requests]  # type: ignore[attr-defined]
        self.assertEqual(
            urls,
            [
                "http://detector:8001/threshold",
                "http://detector:8001/score",
                "http://detector:8001/score",
            ],
        )
        self.assertEqual(
            payloads,
            [
                b'{"threshold": 0.3}',
                b'{"link": "r1-r2", "score": 0.2, "residual": 0.2}',
                b'{"link": "r1-r3", "score": 0.8, "residual": 0.8}',
            ],
        )

    def test_dry_run_never_posts_detector_state(self) -> None:
        def fail_opener(*_args: object, **_kwargs: object) -> object:
            self.fail("dry-run must not issue an HTTP request")

        configure_detector_threshold(
            detector_url="http://detector:8001", threshold=0.2, dry_run=True, opener=fail_opener
        )
        publish_detections(
            detector_url="http://detector:8001",
            detections=[Detection(timestamp=0.0, link="r1-r2", score=0.1, active=False)],
            dry_run=True,
            opener=fail_opener,
        )


class DetectionEvaluationTests(unittest.TestCase):
    def test_duplicate_and_unmatched_detections_are_false_positives(self) -> None:
        metrics = evaluate_detections(
            detections=[
                Detection(timestamp=102.0, link="r1-r2", score=0.8, active=True),
                Detection(timestamp=104.0, link="r1-r2", score=0.9, active=True),
                Detection(timestamp=130.0, link="r1-r3", score=0.9, active=True),
            ],
            faults=[FaultInterval(fault_id="fault-1", link="r1-r2", start=100.0, end=110.0)],
            matching_window_seconds=10,
        )

        self.assertEqual(metrics["precision"], 1 / 3)
        self.assertEqual(metrics["recall"], 1.0)
        self.assertEqual(metrics["false_positive_count"], 2)
        self.assertEqual(metrics["detection_delays_seconds"], [2.0])

    def test_fault_without_detection_has_zero_recall(self) -> None:
        metrics = evaluate_detections(
            detections=[],
            faults=[FaultInterval(fault_id="fault-1", link="r1-r2", start=100.0, end=110.0)],
            matching_window_seconds=10,
        )

        self.assertEqual(metrics["precision"], 0.0)
        self.assertEqual(metrics["recall"], 0.0)
        self.assertEqual(metrics["false_positive_count"], 0)
        self.assertEqual(metrics["detection_delays_seconds"], [])


class DetectorStateTests(unittest.TestCase):
    def test_detector_expires_an_active_score_without_fresh_telemetry(self) -> None:
        now = [100.0]
        state = DetectorState(
            threshold=0.1, freshness_seconds=15.0, monotonic_clock=lambda: now[0]
        )
        state.update(link="r1-r2", score=0.25)
        now[0] += 16.0

        metrics = state.metrics().decode("utf-8")

        self.assertIn('netpulse_anomaly_score_fresh{link="r1-r2"} 0', metrics)
        self.assertIn('netpulse_anomaly_active{link="r1-r2"} 0', metrics)

    def test_detector_exposes_labeled_score_threshold_and_state_metrics(self) -> None:
        state = DetectorState(threshold=0.1)
        state.update(link="r1-r2", score=0.25, residual=-0.25)

        metrics = state.metrics().decode("utf-8")

        self.assertIn('netpulse_anomaly_score{link="r1-r2"} 0.25', metrics)
        self.assertIn('netpulse_anomaly_residual{link="r1-r2"} -0.25', metrics)
        self.assertIn('netpulse_anomaly_threshold{link="r1-r2"} 0.1', metrics)
        self.assertIn('netpulse_anomaly_active{link="r1-r2"} 1', metrics)
        with self.assertRaises(ValueError):
            state.update(link="r1-r2", score=-0.1)

    def test_detector_tracks_each_link_and_recomputes_activity_after_threshold_change(self) -> None:
        state = DetectorState(threshold=0.5)
        state.update(link="r1-r2", score=0.6)
        state.update(link="r1-r3", score=0.4)
        state.set_threshold(0.7)

        metrics = state.metrics().decode("utf-8")

        self.assertIn('netpulse_anomaly_active{link="r1-r2"} 0', metrics)
        self.assertIn('netpulse_anomaly_active{link="r1-r3"} 0', metrics)
        self.assertIn('netpulse_anomaly_threshold{link="r1-r2"} 0.7', metrics)
        with self.assertRaises(ValueError):
            state.set_threshold(float("nan"))


class DetectorHandlerTests(unittest.TestCase):
    def test_threshold_endpoint_and_multilink_metrics(self) -> None:
        previous_state = Handler.state
        Handler.state = DetectorState(threshold=0.1)
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{server.server_port}"

        def post(path: str, payload: bytes) -> bytes:
            request = Request(
                f"{base_url}{path}",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urlopen(request, timeout=2.0) as response:
                return response.read()

        try:
            self.assertEqual(post("/threshold", b'{"threshold": 0.5}'), b'{"threshold": 0.5}')
            post("/score", b'{"link": "r1-r2", "score": 0.6, "residual": -0.6}')
            post("/score", b'{"link": "r1-r3", "score": 0.4, "residual": 0.4}')
            with urlopen(f"{base_url}/metrics", timeout=2.0) as response:
                metrics = response.read().decode("utf-8")
        finally:
            server.shutdown()
            thread.join()
            server.server_close()
            Handler.state = previous_state

        self.assertIn('netpulse_anomaly_active{link="r1-r2"} 1', metrics)
        self.assertIn('netpulse_anomaly_active{link="r1-r3"} 0', metrics)
        self.assertIn('netpulse_anomaly_residual{link="r1-r2"} -0.6', metrics)
        self.assertIn('netpulse_anomaly_threshold{link="r1-r2"} 0.5', metrics)


if __name__ == "__main__":
    unittest.main()
