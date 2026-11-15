"""Evaluate comparable recovery experiments with a sustained-throughput definition."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ThroughputSample:
    """One measured end-to-end throughput observation in bits per second."""

    timestamp: float
    bits_per_second: float


@dataclass(frozen=True)
class RecoveryResult:
    """The reproducible outcome of one bounded recovery experiment."""

    pre_fault_median_bps: float
    restoration_threshold_bps: float
    restoration_time: float | None
    mttr_seconds: float | None
    required_consecutive_samples: int
    reason: str | None


def evaluate_recovery(
    samples: Sequence[ThroughputSample],
    *,
    fault_start: float,
    action_end: float,
    restoration_ratio: float = 0.9,
    required_consecutive_samples: int = 3,
) -> RecoveryResult:
    """Find recovery after an action using a predeclared sustained-throughput rule."""
    if not 0 < restoration_ratio <= 1:
        raise ValueError("restoration_ratio must be in (0, 1]")
    if required_consecutive_samples < 1:
        raise ValueError("required_consecutive_samples must be positive")
    if action_end < fault_start:
        raise ValueError("action_end must not be earlier than fault_start")
    ordered = sorted(samples, key=lambda sample: sample.timestamp)
    if any(sample.bits_per_second < 0 for sample in ordered):
        raise ValueError("throughput samples must be non-negative")
    baseline = [sample.bits_per_second for sample in ordered if sample.timestamp < fault_start]
    if not baseline:
        raise ValueError("at least one pre-fault throughput sample is required")
    median = statistics.median(baseline)
    threshold = median * restoration_ratio
    candidates = [sample for sample in ordered if sample.timestamp >= action_end]
    for index in range(len(candidates) - required_consecutive_samples + 1):
        window = candidates[index : index + required_consecutive_samples]
        if all(sample.bits_per_second >= threshold for sample in window):
            restoration = window[0].timestamp
            return RecoveryResult(
                pre_fault_median_bps=median,
                restoration_threshold_bps=threshold,
                restoration_time=restoration,
                mttr_seconds=restoration - fault_start,
                required_consecutive_samples=required_consecutive_samples,
                reason=None,
            )
    return RecoveryResult(
        pre_fault_median_bps=median,
        restoration_threshold_bps=threshold,
        restoration_time=None,
        mttr_seconds=None,
        required_consecutive_samples=required_consecutive_samples,
        reason="no sustained restoration before experiment end",
    )


def render_markdown(
    *,
    run_id: str,
    manifest_sha256: str,
    scenario: str,
    fault_start: float,
    alert_time: float | None,
    action_start: float | None,
    action_end: float | None,
    result: RecoveryResult,
) -> str:
    """Render one source-backed experiment without implying an unmeasured comparison."""
    def display(value: float | None) -> str:
        return "not observed" if value is None else f"{value:g}"

    mttr = "not restored" if result.mttr_seconds is None else f"{result.mttr_seconds:.3f} s"
    lines = [
        f"## {scenario}",
        "",
        f"Source run: `{run_id}`",
        f"Source manifest SHA-256: `{manifest_sha256}`",
        "",
        "| Event | Timestamp |",
        "| --- | ---: |",
        f"| Fault start | {display(fault_start)} |",
        f"| Alert time | {display(alert_time)} |",
        f"| Action start | {display(action_start)} |",
        f"| Action end | {display(action_end)} |",
        f"| Restoration time | {display(result.restoration_time)} |",
        f"| MTTR | {mttr} |",
        "",
        "| Restoration definition | Value |",
        "| --- | --- |",
        "| Pre-fault throughput median | " f"{result.pre_fault_median_bps:.3f} bps |",
        "| Threshold | " f"{result.restoration_threshold_bps:.3f} bps |",
        "| Required consecutive samples | " f"{result.required_consecutive_samples} |",
    ]
    if result.reason:
        lines.extend(["", f"Result: {result.reason}."])
    return "\n".join(lines) + "\n"
