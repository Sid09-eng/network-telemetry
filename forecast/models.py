"""Forecast baselines and regressors fitted only on the current training split."""

from __future__ import annotations

import math
from collections.abc import Sequence

from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from forecast.features import FeatureRow

MODEL_NAMES = ("persistence", "seasonal_naive", "ridge", "hist_gradient_boosting")


def _bounded_utilization(value: float) -> float:
    """Keep forecasts in the physical range of a utilization ratio."""
    if not math.isfinite(value):
        raise ValueError("model predictions must be finite")
    return min(1.0, max(0.0, value))


def _feature_names(rows: Sequence[FeatureRow]) -> list[str]:
    if not rows:
        raise ValueError("at least one training row is required")
    names = sorted(rows[0].features)
    if not names or any(sorted(row.features) != names for row in rows):
        raise ValueError("all feature rows must share the same feature names")
    return names


def _matrix(rows: Sequence[FeatureRow], names: Sequence[str]) -> list[list[float]]:
    return [[row.features[name] for name in names] for row in rows]


def predict(
    model: str,
    *,
    train_rows: Sequence[FeatureRow],
    test_rows: Sequence[FeatureRow],
) -> list[float]:
    """Fit a selected model on train rows and predict target utilization for test rows."""
    if model not in MODEL_NAMES:
        raise ValueError(f"unknown model: {model}")
    if not test_rows:
        return []
    if model == "persistence":
        return [_bounded_utilization(row.features["current"]) for row in test_rows]
    seasonal_name = next(name for name in test_rows[0].features if name.startswith("seasonal_lag_"))
    if model == "seasonal_naive":
        return [_bounded_utilization(row.features[seasonal_name]) for row in test_rows]

    names = _feature_names(train_rows)
    estimator = (
        make_pipeline(StandardScaler(), Ridge(alpha=1.0))
        if model == "ridge"
        else HistGradientBoostingRegressor(max_iter=100, random_state=0)
    )
    estimator.fit(_matrix(train_rows, names), [row.target for row in train_rows])
    predictions = estimator.predict(_matrix(test_rows, names))
    return [_bounded_utilization(float(value)) for value in predictions]
