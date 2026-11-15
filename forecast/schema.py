"""Validate Prometheus range-query data before it becomes a NetPulse run artifact."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

REQUIRED_LABELS = ("__name__", "router", "interface", "link")


class SchemaError(ValueError):
    """Raised when raw Prometheus data does not meet the NetPulse telemetry contract."""


@dataclass(frozen=True)
class TelemetrySample:
    """One finite, labeled point from a Prometheus matrix result."""

    metric: str
    router: str
    interface: str
    link: str
    timestamp: float
    value: float


def _finite_number(value: object, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise SchemaError(f"{field} must be numeric") from error
    if not math.isfinite(number):
        raise SchemaError(f"{field} must be finite")
    return number


def validate_prometheus_matrix(response: Any) -> list[TelemetrySample]:
    """Validate a successful Prometheus matrix response into typed samples."""
    if not isinstance(response, dict) or response.get("status") != "success":
        raise SchemaError("Prometheus response status must be success")
    data = response.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "matrix":
        raise SchemaError("Prometheus response must contain a matrix result")
    result = data.get("result")
    if not isinstance(result, list):
        raise SchemaError("Prometheus matrix result must be a list")

    samples: list[TelemetrySample] = []
    for series_index, series in enumerate(result):
        if not isinstance(series, dict):
            raise SchemaError(f"series {series_index} must be an object")
        labels = series.get("metric")
        if not isinstance(labels, dict):
            raise SchemaError(f"series {series_index} has no metric labels")
        for label in REQUIRED_LABELS:
            if not isinstance(labels.get(label), str) or not labels[label]:
                raise SchemaError(f"series {series_index} is missing required label {label}")
        values = series.get("values")
        if not isinstance(values, list):
            raise SchemaError(f"series {series_index} values must be a list")
        for value_index, point in enumerate(values):
            if not isinstance(point, list) or len(point) != 2:
                raise SchemaError(
                    f"series {series_index} point {value_index} must be [timestamp, value]"
                )
            samples.append(
                TelemetrySample(
                    metric=labels["__name__"],
                    router=labels["router"],
                    interface=labels["interface"],
                    link=labels["link"],
                    timestamp=_finite_number(point[0], "timestamp"),
                    value=_finite_number(point[1], "value"),
                )
            )
    return samples
