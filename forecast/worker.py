#!/usr/bin/env python3
"""Continuously score Prometheus link utilisation and publish residuals to the detector."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from forecast.detect import Detection, configure_detector_threshold, publish_detections
from forecast.features import Observation, build_live_features

DEFAULT_QUERY = "router_interface:transmit_utilisation_ratio:rate1m"
REQUIRED_LABELS = ("__name__", "router", "interface", "link")
Collector = Callable[[], list[Observation]]
ThresholdConfigurer = Callable[[float], None]
Publisher = Callable[[Sequence[Detection]], None]


def _finite(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{field} must be numeric") from error
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def observations_from_prometheus_vector(response: Any) -> list[Observation]:
    """Validate a Prometheus instant-vector response as utilisation observations."""
    if not isinstance(response, Mapping) or response.get("status") != "success":
        raise ValueError("Prometheus response status must be success")
    data = response.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "vector":
        raise ValueError("Prometheus response must contain a vector result")
    result = data.get("result")
    if not isinstance(result, list):
        raise ValueError("Prometheus vector result must be a list")

    observations: list[Observation] = []
    for index, series in enumerate(result):
        if not isinstance(series, Mapping):
            raise ValueError(f"series {index} must be an object")
        labels = series.get("metric")
        if not isinstance(labels, Mapping):
            raise ValueError(f"series {index} has no metric labels")
        for label in REQUIRED_LABELS:
            if not isinstance(labels.get(label), str) or not labels[label]:
                raise ValueError(f"series {index} is missing required label {label}")
        value = series.get("value")
        if not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"series {index} must contain [timestamp, value]")
        utilisation = _finite(value[1], "utilisation")
        if utilisation < 0:
            raise ValueError("utilisation must be non-negative")
        observations.append(
            Observation(
                timestamp=_finite(value[0], "timestamp"),
                router=labels["router"],
                interface=labels["interface"],
                link=labels["link"],
                value=utilisation,
            )
        )
    return observations


def observations_from_prometheus_responses(
    utilisation_response: Any,
    source_timestamp_response: Any,
    *,
    max_sample_age_seconds: float,
) -> list[Observation]:
    """Join utilisation with Prometheus source timestamps and discard stale samples."""
    if not math.isfinite(max_sample_age_seconds) or max_sample_age_seconds <= 0:
        raise ValueError("max_sample_age_seconds must be finite and positive")
    utilisation = observations_from_prometheus_vector(utilisation_response)
    if (
        not isinstance(source_timestamp_response, Mapping)
        or source_timestamp_response.get("status") != "success"
    ):
        raise ValueError("Prometheus source timestamp response status must be success")
    data = source_timestamp_response.get("data")
    if not isinstance(data, Mapping) or data.get("resultType") != "vector":
        raise ValueError("Prometheus source timestamp response must contain a vector result")
    result = data.get("result")
    if not isinstance(result, list):
        raise ValueError("Prometheus source timestamp vector result must be a list")

    source_timestamps: dict[tuple[str, str, str], float] = {}
    for index, series in enumerate(result):
        if not isinstance(series, Mapping):
            raise ValueError(f"source timestamp series {index} must be an object")
        labels = series.get("metric")
        value = series.get("value")
        if not isinstance(labels, Mapping) or not isinstance(value, list) or len(value) != 2:
            raise ValueError(f"source timestamp series {index} is malformed")
        key = tuple(labels.get(label) for label in ("router", "interface", "link"))
        if not all(isinstance(label, str) and label for label in key):
            raise ValueError(f"source timestamp series {index} is missing required labels")
        if key in source_timestamps:
            raise ValueError("source timestamp response contains duplicate link samples")
        source_timestamps[key] = _finite(value[1], "source timestamp")

    observations: list[Observation] = []
    for sample in utilisation:
        key = (sample.router, sample.interface, sample.link)
        source_timestamp = source_timestamps.get(key)
        if source_timestamp is None:
            raise ValueError("utilisation sample has no corresponding source timestamp")
        # The instant-vector timestamp is query evaluation time; timestamp(query) supplies the
        # stored sample time.  Never warm history from a paused recording rule's lookback value.
        if sample.timestamp - source_timestamp > max_sample_age_seconds:
            continue
        if source_timestamp > sample.timestamp:
            raise ValueError("source timestamp cannot be later than query evaluation time")
        observations.append(
            Observation(
                timestamp=source_timestamp,
                router=sample.router,
                interface=sample.interface,
                link=sample.link,
                value=sample.value,
            )
        )
    return observations


def collect_prometheus_vector(
    prometheus_url: str,
    query: str = DEFAULT_QUERY,
    *,
    timeout_seconds: float = 5.0,
    max_sample_age_seconds: float = 15.0,
) -> list[Observation]:
    """Fetch current utilisation with its stored source sample timestamps."""
    if not prometheus_url.startswith(("http://", "https://")):
        raise ValueError("prometheus_url must start with http:// or https://")
    if not query.strip():
        raise ValueError("query must be non-empty")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be finite and positive")
    def fetch(query_expression: str) -> Any:
        parameters = urlencode({"query": query_expression})
        request = Request(f"{prometheus_url.rstrip('/')}/api/v1/query?{parameters}")
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))

    return observations_from_prometheus_responses(
        fetch(query),
        fetch(f"timestamp({query})"),
        max_sample_age_seconds=max_sample_age_seconds,
    )


@dataclass(frozen=True)
class InferenceConfig:
    """Runtime settings for a bounded in-memory persistence forecaster."""

    prometheus_url: str
    detector_url: str
    poll_seconds: float
    threshold: float
    query: str = DEFAULT_QUERY
    max_sample_age_seconds: float = 15.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.poll_seconds) or self.poll_seconds <= 0:
            raise ValueError("poll_seconds must be finite and positive")
        if not math.isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("threshold must be finite and non-negative")
        if not math.isfinite(self.max_sample_age_seconds) or self.max_sample_age_seconds <= 0:
            raise ValueError("max_sample_age_seconds must be finite and positive")

    @classmethod
    def from_env(cls) -> InferenceConfig:
        return cls(
            prometheus_url=os.environ.get("NETPULSE_PROMETHEUS_URL", "http://prometheus:9090"),
            detector_url=os.environ.get("NETPULSE_DETECTOR_URL", "http://detector:8001"),
            poll_seconds=float(os.environ.get("NETPULSE_INFERENCE_POLL_SECONDS", "5")),
            threshold=float(os.environ.get("NETPULSE_ANOMALY_THRESHOLD", "0.1")),
            query=os.environ.get("NETPULSE_INFERENCE_QUERY", DEFAULT_QUERY),
            max_sample_age_seconds=float(
                os.environ.get("NETPULSE_INFERENCE_MAX_SAMPLE_AGE_SECONDS", "15")
            ),
        )


@dataclass(frozen=True)
class _Prediction:
    expected_timestamp: float
    value: float


def _highest_score_per_link(detections: Sequence[Detection]) -> list[Detection]:
    """Collapse directional interface residuals to one conservative physical-link score."""
    by_link: dict[str, Detection] = {}
    for detection in detections:
        existing = by_link.get(detection.link)
        if existing is None or detection.score > existing.score:
            by_link[detection.link] = detection
    return [by_link[link] for link in sorted(by_link)]


class InferenceWorker:
    """Poll utilisation, retain bounded feature history, and publish residual scores."""

    def __init__(
        self,
        config: InferenceConfig,
        *,
        collector: Collector | None = None,
        configure_threshold: ThresholdConfigurer | None = None,
        publisher: Publisher | None = None,
    ) -> None:
        self.config = config
        self.collector = collector or (
            lambda: collect_prometheus_vector(
                config.prometheus_url,
                config.query,
                max_sample_age_seconds=config.max_sample_age_seconds,
            )
        )
        self.configure_threshold = configure_threshold or (
            lambda threshold: configure_detector_threshold(
                detector_url=config.detector_url, threshold=threshold
            )
        )
        self.publisher = publisher or (
            lambda detections: publish_detections(
                detector_url=config.detector_url, detections=detections
            )
        )
        self._configured = False
        self._history: dict[str, list[Observation]] = {}
        self._predictions: dict[str, _Prediction] = {}
        self._last_received_at: dict[str, float] = {}

    def _normalise_cadence(self, sample: Observation) -> Observation | None:
        """Map ordinary polling jitter to an exact in-memory feature cadence."""
        previous_received_at = self._last_received_at.get(sample.series_id)
        history = self._history.setdefault(sample.series_id, [])
        if previous_received_at is not None and sample.timestamp <= previous_received_at:
            return None
        self._last_received_at[sample.series_id] = sample.timestamp
        if previous_received_at is None or not history:
            return sample
        elapsed = sample.timestamp - previous_received_at
        if math.isclose(elapsed, self.config.poll_seconds, rel_tol=0.2):
            return Observation(
                timestamp=history[-1].timestamp + self.config.poll_seconds,
                router=sample.router,
                interface=sample.interface,
                link=sample.link,
                value=sample.value,
            )
        return sample

    def poll_once(self) -> list[Detection]:
        """Execute one collection, scoring, and publication cycle."""
        if not self._configured:
            self.configure_threshold(self.config.threshold)
            self._configured = True

        detections: list[Detection] = []
        for received_sample in self.collector():
            sample = self._normalise_cadence(received_sample)
            if sample is None:
                continue
            history = self._history.setdefault(sample.series_id, [])

            prediction = self._predictions.get(sample.series_id)
            if prediction is not None:
                if math.isclose(
                    sample.timestamp,
                    prediction.expected_timestamp,
                    abs_tol=self.config.poll_seconds * 0.01,
                    rel_tol=0.0,
                ):
                    residual = sample.value - prediction.value
                    score = abs(residual)
                    detections.append(
                        Detection(
                            timestamp=received_sample.timestamp,
                            link=sample.link,
                            score=score,
                            active=score >= self.config.threshold,
                            residual=residual,
                        )
                    )
                elif sample.timestamp > prediction.expected_timestamp:
                    del self._predictions[sample.series_id]

            history.append(sample)
            history[:] = history[-13:]
            features = build_live_features(
                history, expected_step_seconds=self.config.poll_seconds
            )
            if features:
                self._predictions[sample.series_id] = _Prediction(
                    expected_timestamp=sample.timestamp + self.config.poll_seconds,
                    value=features[0].features["current"],
                )
            else:
                self._predictions.pop(sample.series_id, None)

        link_detections = _highest_score_per_link(detections)
        if link_detections:
            self.publisher(link_detections)
        return link_detections


def run_forever(worker: InferenceWorker, *, sleeper: Callable[[float], None] = time.sleep) -> None:
    """Keep the worker available through transient upstream failures."""
    while True:
        started = time.monotonic()
        try:
            detections = worker.poll_once()
            print(f"inference cycle complete; published={len(detections)}", flush=True)
        except (OSError, ValueError, json.JSONDecodeError) as error:
            print(f"inference cycle failed: {error}", flush=True)
        sleeper(max(0.0, worker.config.poll_seconds - (time.monotonic() - started)))


def main() -> int:
    """Run the Compose inference worker until the service is stopped."""
    run_forever(InferenceWorker(InferenceConfig.from_env()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
