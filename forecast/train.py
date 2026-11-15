#!/usr/bin/env python3
"""Train and evaluate Task 7 models from one immutable NetPulse run."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path

from forecast.detect import (
    Detection,
    configure_detector_threshold,
    publish_detections,
    score_residuals,
    select_threshold,
)
from forecast.evaluate import (
    evaluate_leave_one_link_out,
    evaluate_rolling_origin,
    rolling_origin_folds,
)
from forecast.features import FeatureRow, Observation, build_features
from forecast.models import MODEL_NAMES, predict


def load_observations(path: Path, *, capacity_bps: float) -> list[Observation]:
    """Load normalized telemetry and transform bits per second into utilization ratios."""
    if capacity_bps <= 0:
        raise ValueError("capacity_bps must be positive")
    observations: list[Observation] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        observations.append(
            Observation(
                timestamp=float(record["timestamp"]),
                router=str(record["router"]),
                interface=str(record["interface"]),
                link=str(record["link"]),
                value=float(record["value"]) / capacity_bps,
            )
        )
    return observations


def mean_fold_metrics(report: dict[str, object]) -> dict[str, dict[str, float]]:
    """Average chronological-fold metrics per model without mixing transfer results."""
    totals: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for fold in report["folds"]:  # type: ignore[index]
        for model, metrics in fold["metrics"].items():  # type: ignore[index]
            for name, value in metrics.items():  # type: ignore[index]
                totals[model][name].append(value)
    return {
        model: {name: sum(values) / len(values) for name, values in metrics.items()}
        for model, metrics in totals.items()
    }


def _rows_for_timestamps(
    rows: Sequence[FeatureRow], timestamps: Sequence[float]
) -> list[FeatureRow]:
    timestamps_set = set(timestamps)
    return [row for row in rows if row.timestamp in timestamps_set]


def calibrate_and_publish_detector(
    rows: Sequence[FeatureRow],
    *,
    detector_url: str,
    model: str,
    quantile: float,
    dry_run: bool = False,
) -> tuple[float, list[Detection]]:
    """Calibrate on earlier validation folds, then score and publish the final fold.

    The final validation fold emulates production: its targets are never used to
    select the threshold.  Its model only learns from timestamps before that fold.
    """
    folds, skipped = rolling_origin_folds(
        timestamps=[row.timestamp for row in rows],
        initial_train_timestamps=24,
        validation_timestamps=12,
        step_timestamps=12,
    )
    if len(folds) < 2:
        detail = "; ".join(skipped) if skipped else "need two rolling-origin folds"
        raise ValueError(f"insufficient folds for detector calibration: {detail}")

    calibration_residuals: list[float] = []
    for fold in folds[:-1]:
        train_rows = _rows_for_timestamps(rows, fold.train_timestamps)
        validation_rows = _rows_for_timestamps(rows, fold.validation_timestamps)
        predictions = predict(model, train_rows=train_rows, test_rows=validation_rows)
        calibration_residuals.extend(
            actual.target - forecast
            for actual, forecast in zip(validation_rows, predictions, strict=True)
        )

    threshold = select_threshold(calibration_residuals, quantile=quantile)
    final_fold = folds[-1]
    final_train_rows = _rows_for_timestamps(rows, final_fold.train_timestamps)
    final_validation_rows = _rows_for_timestamps(rows, final_fold.validation_timestamps)
    final_predictions = predict(model, train_rows=final_train_rows, test_rows=final_validation_rows)
    detections = score_residuals(
        timestamps=[row.timestamp for row in final_validation_rows],
        links=[row.link for row in final_validation_rows],
        actual=[row.target for row in final_validation_rows],
        predicted=final_predictions,
        threshold=threshold,
    )
    configure_detector_threshold(detector_url=detector_url, threshold=threshold, dry_run=dry_run)
    publish_detections(detector_url=detector_url, detections=detections, dry_run=dry_run)
    return threshold, detections


def render_markdown(
    *,
    run_id: str,
    manifest_sha256: str,
    chronological: dict[str, object],
    transfer: dict[str, object],
) -> str:
    """Render measured metrics with chronological and link-transfer sections separate."""
    averages = mean_fold_metrics(chronological)
    lines = [
        "# Forecast metrics",
        "",
        f"Source run: `{run_id}`. Metrics are utilization-ratio errors from completed collection.",
        f"Source manifest SHA-256: `{manifest_sha256}`.",
        "This is a short synthetic run, not an operator-network performance claim.",
        "",
        "## Rolling-origin future-time evaluation",
        "",
        "| Model | MAE | RMSE |",
        "| --- | ---: | ---: |",
    ]
    for model, metrics in averages.items():
        lines.append(f"| {model} | {metrics['mae']:.6f} | {metrics['rmse']:.6f} |")
    lines.extend(["", "## Leave-one-link-out transfer evaluation", ""])
    for link, models in transfer["held_out_links"].items():  # type: ignore[index]
        lines.extend(
            [f"### Held out: `{link}`", "", "| Model | MAE | RMSE |", "| --- | ---: | ---: |"]
        )
        for model, metrics in models.items():
            lines.append(f"| {model} | {metrics['mae']:.6f} | {metrics['rmse']:.6f} |")
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("results/forecast_metrics.md"))
    parser.add_argument("--capacity-bps", type=float, default=100_000_000)
    parser.add_argument(
        "--detector-url",
        help=(
            "Publish a validation-calibrated threshold and final-fold residuals "
            "to this detector URL"
        ),
    )
    parser.add_argument("--detector-model", choices=MODEL_NAMES, default="ridge")
    parser.add_argument("--detector-quantile", type=float, default=0.99)
    parser.add_argument(
        "--detector-dry-run",
        action="store_true",
        help="Calculate detector payloads without changing detector state",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_id = args.run_dir.name
    manifest_sha256 = hashlib.sha256((args.run_dir / "manifest.json").read_bytes()).hexdigest()
    observations = load_observations(
        args.run_dir / "telemetry.jsonl", capacity_bps=args.capacity_bps
    )
    rows = build_features(observations)
    chronological = evaluate_rolling_origin(rows)
    if not chronological["folds"]:
        raise SystemExit(f"no valid rolling-origin folds: {chronological['skipped']}")
    transfer = evaluate_leave_one_link_out(rows)
    if args.detector_url:
        threshold, detections = calibrate_and_publish_detector(
            rows,
            detector_url=args.detector_url,
            model=args.detector_model,
            quantile=args.detector_quantile,
            dry_run=args.detector_dry_run,
        )
        print(
            f"detector threshold={threshold:.6f}; published {len(detections)} final-fold residuals"
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        render_markdown(
            run_id=run_id,
            manifest_sha256=manifest_sha256,
            chronological=chronological,
            transfer=transfer,
        ),
        encoding="utf-8",
    )
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
