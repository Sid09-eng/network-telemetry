"""Leakage-safe features for next-interval interface utilisation forecasting."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class Observation:
    """One utilization observation for a directional router interface."""

    timestamp: float
    router: str
    interface: str
    link: str
    value: float

    @property
    def series_id(self) -> str:
        return f"{self.router}:{self.interface}:{self.link}"


@dataclass(frozen=True)
class FeatureRow:
    """Features known at time t and the target utilization at t plus horizon."""

    timestamp: float
    router: str
    interface: str
    link: str
    features: dict[str, float]
    target: float


@dataclass(frozen=True)
class LiveFeatureRow:
    """Features available at the newest observation, before its target exists."""

    timestamp: float
    router: str
    interface: str
    link: str
    features: dict[str, float]


def _is_contiguous(observations: Sequence[Observation], start: int, end: int, step: float) -> bool:
    """Require every observation used by features or target to be evenly spaced."""
    return all(
        observations[index].timestamp - observations[index - 1].timestamp == step
        for index in range(start + 1, end + 1)
    )


def _feature_values(
    observations: Sequence[Observation],
    *,
    current_index: int,
    lag_steps: Sequence[int],
    rolling_window: int,
    seasonal_period: int,
) -> dict[str, float]:
    """Build feature values known at one observation index."""
    current = observations[current_index]
    values = {"current": current.value}
    values.update({f"lag_{lag}": observations[current_index - lag].value for lag in lag_steps})
    values[f"rolling_mean_{rolling_window}"] = (
        sum(
            point.value
            for point in observations[current_index - rolling_window + 1 : current_index + 1]
        )
        / rolling_window
    )
    values[f"seasonal_lag_{seasonal_period}"] = observations[current_index - seasonal_period].value
    return values


def build_live_features(
    observations: Iterable[Observation],
    *,
    lag_steps: Sequence[int] = (1, 2, 3),
    rolling_window: int = 3,
    seasonal_period: int = 12,
    expected_step_seconds: float = 5,
) -> list[LiveFeatureRow]:
    """Build latest-point features without reading an unknown future target."""
    if expected_step_seconds <= 0:
        raise ValueError("expected_step_seconds must be positive")
    if not lag_steps or any(lag < 1 for lag in lag_steps):
        raise ValueError("lag_steps must contain positive values")
    if rolling_window < 1 or seasonal_period < 1:
        raise ValueError("rolling_window and seasonal_period must be positive")

    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.series_id].append(observation)

    history = max(max(lag_steps), rolling_window - 1, seasonal_period)
    rows: list[LiveFeatureRow] = []
    for series in grouped.values():
        ordered = sorted(series, key=lambda observation: observation.timestamp)
        if len({observation.timestamp for observation in ordered}) != len(ordered):
            raise ValueError(f"duplicate timestamp in series {ordered[0].series_id}")
        current_index = len(ordered) - 1
        if current_index < history or not _is_contiguous(
            ordered, current_index - history, current_index, expected_step_seconds
        ):
            continue
        current = ordered[current_index]
        rows.append(
            LiveFeatureRow(
                timestamp=current.timestamp,
                router=current.router,
                interface=current.interface,
                link=current.link,
                features=_feature_values(
                    ordered,
                    current_index=current_index,
                    lag_steps=lag_steps,
                    rolling_window=rolling_window,
                    seasonal_period=seasonal_period,
                ),
            )
        )
    return sorted(rows, key=lambda row: (row.timestamp, row.router, row.interface, row.link))


def build_features(
    observations: Iterable[Observation],
    *,
    horizon_steps: int = 1,
    lag_steps: Sequence[int] = (1, 2, 3),
    rolling_window: int = 3,
    seasonal_period: int = 12,
    expected_step_seconds: float = 5,
) -> list[FeatureRow]:
    """Build rows whose features use observations through t only and target is after t."""
    if horizon_steps < 1 or rolling_window < 1 or seasonal_period < 1:
        raise ValueError("horizon_steps, rolling_window, and seasonal_period must be positive")
    if expected_step_seconds <= 0:
        raise ValueError("expected_step_seconds must be positive")
    if not lag_steps or any(lag < 1 for lag in lag_steps):
        raise ValueError("lag_steps must contain positive values")

    grouped: dict[str, list[Observation]] = defaultdict(list)
    for observation in observations:
        grouped[observation.series_id].append(observation)

    rows: list[FeatureRow] = []
    history = max(max(lag_steps), rolling_window - 1, seasonal_period)
    for series in grouped.values():
        ordered = sorted(series, key=lambda observation: observation.timestamp)
        if len({observation.timestamp for observation in ordered}) != len(ordered):
            raise ValueError(f"duplicate timestamp in series {ordered[0].series_id}")
        for current_index in range(history, len(ordered) - horizon_steps):
            target_index = current_index + horizon_steps
            if not _is_contiguous(
                ordered, current_index - history, target_index, expected_step_seconds
            ):
                continue
            current = ordered[current_index]
            rows.append(
                FeatureRow(
                    timestamp=current.timestamp,
                    router=current.router,
                    interface=current.interface,
                    link=current.link,
                    features=_feature_values(
                        ordered,
                        current_index=current_index,
                        lag_steps=lag_steps,
                        rolling_window=rolling_window,
                        seasonal_period=seasonal_period,
                    ),
                    target=ordered[target_index].value,
                )
            )
    return sorted(rows, key=lambda row: (row.timestamp, row.router, row.interface, row.link))
