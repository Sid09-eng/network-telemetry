"""Residual anomaly scoring and link-fault evaluation for NetPulse."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class Detection:
    """One residual score and its thresholded anomaly state."""

    timestamp: float
    link: str
    score: float
    active: bool


@dataclass(frozen=True)
class FaultInterval:
    """Ground-truth fault interval for one physical link."""

    fault_id: str
    link: str
    start: float
    end: float


DetectorOpener = Callable[..., Any]


def _validate_detector_url(detector_url: str) -> str:
    """Return a usable detector base URL without accepting an empty value."""
    normalized = detector_url.rstrip("/")
    if not normalized.startswith(("http://", "https://")):
        raise ValueError("detector_url must start with http:// or https://")
    return normalized


def _post_json(
    *,
    detector_url: str,
    path: str,
    payload: dict[str, float | str],
    timeout_seconds: float,
    opener: DetectorOpener,
) -> None:
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive and finite")
    request = Request(
        f"{_validate_detector_url(detector_url)}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with opener(request, timeout=timeout_seconds) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError(f"detector returned HTTP {response.status}")


def configure_detector_threshold(
    *,
    detector_url: str,
    threshold: float,
    dry_run: bool = False,
    timeout_seconds: float = 2.0,
    opener: DetectorOpener = urlopen,
) -> None:
    """Publish a validation-only residual threshold to the detector.

    Call this only after selecting ``threshold`` from validation residuals.  ``dry_run``
    intentionally performs no HTTP request so experiment/reporting runs cannot mutate
    live detector state.
    """
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be non-negative and finite")
    if dry_run:
        return
    _post_json(
        detector_url=detector_url,
        path="/threshold",
        payload={"threshold": threshold},
        timeout_seconds=timeout_seconds,
        opener=opener,
    )


def publish_detections(
    *,
    detector_url: str,
    detections: Sequence[Detection],
    dry_run: bool = False,
    timeout_seconds: float = 2.0,
    opener: DetectorOpener = urlopen,
) -> None:
    """Publish residual scores produced by :func:`score_residuals` to the detector.

    Every detection is sent, including normal scores, so the detector can clear an
    earlier active anomaly.  Publishing is deliberately opt-in at the caller and
    dry-run safe.
    """
    if dry_run:
        return
    for detection in detections:
        _post_json(
            detector_url=detector_url,
            path="/score",
            payload={"link": detection.link, "score": detection.score},
            timeout_seconds=timeout_seconds,
            opener=opener,
        )


def select_threshold(validation_residuals: Sequence[float], *, quantile: float) -> float:
    """Select a nearest-rank threshold using validation residuals only."""
    if not validation_residuals:
        raise ValueError("validation_residuals must not be empty")
    if not 0 < quantile <= 1:
        raise ValueError("quantile must be in (0, 1]")
    residuals = [abs(value) for value in validation_residuals]
    if not all(math.isfinite(value) for value in residuals):
        raise ValueError("validation_residuals must be finite")
    residuals.sort()
    index = math.ceil(quantile * len(residuals)) - 1
    return residuals[index]


def score_residuals(
    *,
    timestamps: Sequence[float],
    links: Sequence[str],
    actual: Sequence[float],
    predicted: Sequence[float],
    threshold: float,
) -> list[Detection]:
    """Score absolute residuals and flag values at or above the fixed threshold."""
    if not math.isfinite(threshold) or threshold < 0:
        raise ValueError("threshold must be non-negative and finite")
    if not (len(timestamps) == len(links) == len(actual) == len(predicted)):
        raise ValueError("timestamps, links, actual, and predicted must have equal length")
    detections: list[Detection] = []
    for timestamp, link, observed, forecast in zip(
        timestamps, links, actual, predicted, strict=True
    ):
        score = abs(observed - forecast)
        if not math.isfinite(score):
            raise ValueError("residual scores must be finite")
        detections.append(
            Detection(timestamp=timestamp, link=link, score=score, active=score >= threshold)
        )
    return detections


def evaluate_detections(
    *,
    detections: Sequence[Detection],
    faults: Sequence[FaultInterval],
    matching_window_seconds: float,
) -> dict[str, object]:
    """Match each active detection to at most one same-link fault interval."""
    if matching_window_seconds < 0:
        raise ValueError("matching_window_seconds must be non-negative")
    unmatched_faults = {fault.fault_id: fault for fault in faults}
    matched_detections = 0
    delays: list[float] = []
    active = sorted((item for item in detections if item.active), key=lambda item: item.timestamp)
    for detection in active:
        candidates = [
            fault
            for fault in unmatched_faults.values()
            if fault.link == detection.link
            and fault.start <= detection.timestamp <= fault.end + matching_window_seconds
        ]
        if not candidates:
            continue
        matched = min(candidates, key=lambda fault: fault.start)
        del unmatched_faults[matched.fault_id]
        matched_detections += 1
        delays.append(detection.timestamp - matched.start)
    precision = matched_detections / len(active) if active else 0.0
    recall = matched_detections / len(faults) if faults else 0.0
    return {
        "precision": precision,
        "recall": recall,
        "false_positive_count": len(active) - matched_detections,
        "detection_delays_seconds": delays,
        "matching_window_seconds": matching_window_seconds,
    }
