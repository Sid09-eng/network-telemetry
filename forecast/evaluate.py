"""Strict chronological and leave-one-link-out forecasting evaluation."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from forecast.features import FeatureRow
from forecast.models import MODEL_NAMES, predict


@dataclass(frozen=True)
class TimeFold:
    """One strictly chronological train/validation split expressed as timestamps."""

    train_timestamps: tuple[float, ...]
    validation_timestamps: tuple[float, ...]


def rolling_origin_folds(
    *,
    timestamps: Iterable[float],
    initial_train_timestamps: int,
    validation_timestamps: int,
    step_timestamps: int,
) -> tuple[list[TimeFold], list[str]]:
    """Create rolling-origin folds without allowing shared train/validation timestamps."""
    if min(initial_train_timestamps, validation_timestamps, step_timestamps) < 1:
        raise ValueError("fold sizes must be positive")
    unique = sorted(set(timestamps))
    if len(unique) < initial_train_timestamps + validation_timestamps:
        return [], ["insufficient timestamps for one validation fold"]
    folds: list[TimeFold] = []
    split = initial_train_timestamps
    while split + validation_timestamps <= len(unique):
        folds.append(
            TimeFold(
                train_timestamps=tuple(unique[:split]),
                validation_timestamps=tuple(unique[split : split + validation_timestamps]),
            )
        )
        split += step_timestamps
    return folds, []


def leave_one_link_out_splits(links: Iterable[str]) -> list[tuple[str, tuple[str, ...]]]:
    """Return held-out-link / train-link pairs, rejecting an invalid single-link dataset."""
    unique = tuple(sorted(set(links)))
    if len(unique) < 2:
        raise ValueError("leave-one-link-out evaluation requires at least two links")
    return [(held_out, tuple(link for link in unique if link != held_out)) for held_out in unique]


def _metrics(actual: Sequence[float], predicted: Sequence[float]) -> dict[str, float]:
    if not actual:
        raise ValueError("cannot score an empty prediction set")
    errors = [observed - forecast for observed, forecast in zip(actual, predicted, strict=True)]
    return {
        "mae": sum(abs(error) for error in errors) / len(errors),
        "rmse": math.sqrt(sum(error**2 for error in errors) / len(errors)),
    }


def _score_models(
    train_rows: Sequence[FeatureRow], test_rows: Sequence[FeatureRow]
) -> dict[str, dict[str, float]]:
    return {
        model: _metrics(
            [row.target for row in test_rows],
            predict(model, train_rows=train_rows, test_rows=test_rows),
        )
        for model in MODEL_NAMES
    }


def evaluate_rolling_origin(
    rows: Sequence[FeatureRow],
    *,
    initial_train_timestamps: int = 24,
    validation_timestamps: int = 12,
    step_timestamps: int = 12,
) -> dict[str, object]:
    """Score all models across strict rolling-origin folds."""
    folds, skipped = rolling_origin_folds(
        timestamps=[row.timestamp for row in rows],
        initial_train_timestamps=initial_train_timestamps,
        validation_timestamps=validation_timestamps,
        step_timestamps=step_timestamps,
    )
    scores: list[dict[str, object]] = []
    for fold in folds:
        train_times = set(fold.train_timestamps)
        validation_times = set(fold.validation_timestamps)
        train_rows = [row for row in rows if row.timestamp in train_times]
        validation_rows = [row for row in rows if row.timestamp in validation_times]
        scores.append(
            {
                "train_end": max(fold.train_timestamps),
                "validation_start": min(fold.validation_timestamps),
                "metrics": _score_models(train_rows, validation_rows),
            }
        )
    return {"folds": scores, "skipped": skipped}


def evaluate_leave_one_link_out(rows: Sequence[FeatureRow]) -> dict[str, object]:
    """Report transfer performance separately from chronological forecasting performance."""
    scores: dict[str, dict[str, dict[str, float]]] = {}
    for held_out, train_links in leave_one_link_out_splits(row.link for row in rows):
        train_rows = [row for row in rows if row.link in train_links]
        test_rows = [row for row in rows if row.link == held_out]
        scores[held_out] = _score_models(train_rows, test_rows)
    return {"held_out_links": scores}
