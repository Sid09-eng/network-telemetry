#!/usr/bin/env python3
"""Collect validated Prometheus telemetry into immutable NetPulse run directories."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

if __package__:
    from .schema import TelemetrySample, validate_prometheus_matrix
else:  # Supports the documented `python forecast/collect.py` invocation.
    from schema import TelemetrySample, validate_prometheus_matrix

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
DEFAULT_QUERY = "router_interface:transmit_bits:rate1m"
DEFAULT_CONFIG_PATHS = (
    Path("monitoring/prometheus.yml"),
    Path("monitoring/recording_rules.yml"),
    Path("traffic/scenarios/diamond-failover.yaml"),
)
HttpOpener = Callable[[Request, float], Any]


def range_query_url(base_url: str, *, query: str, start: float, end: float, step: float) -> str:
    """Build a Prometheus range-query URL with safely encoded parameters."""
    parameters = urlencode({"query": query, "start": start, "end": end, "step": step})
    return f"{base_url.rstrip('/')}/api/v1/query_range?{parameters}"


def query_range(
    base_url: str,
    *,
    query: str,
    start: float,
    end: float,
    step: float,
    opener: HttpOpener = urlopen,
) -> dict[str, Any]:
    """Fetch one raw Prometheus range-query response over HTTP."""
    request = Request(range_query_url(base_url, query=query, start=start, end=end, step=step))
    with opener(request, 15) as response:
        decoded = response.read().decode("utf-8")
    data = json.loads(decoded)
    if not isinstance(data, dict):
        raise ValueError("Prometheus returned a non-object JSON response")
    return data


def query_range_from_container(
    container: str,
    *,
    query: str,
    start: float,
    end: float,
    step: float,
) -> dict[str, Any]:
    """Fetch a range query via the Prometheus container for DIND/DOOD terminals."""
    url = range_query_url("http://localhost:9090", query=query, start=start, end=end, step=step)
    completed = subprocess.run(
        ["docker", "exec", container, "wget", "-qO-", url],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(completed.stdout)
    if not isinstance(data, dict):
        raise ValueError("Prometheus returned a non-object JSON response")
    return data


def sha256_file(path: Path) -> str:
    """Return a configuration file's content hash."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, samples: Sequence[TelemetrySample]) -> None:
    with path.open("w", encoding="utf-8") as stream:
        for sample in samples:
            stream.write(json.dumps(asdict(sample), sort_keys=True) + "\n")


def write_run(
    *,
    runs_root: Path,
    run_id: str,
    raw_response: Mapping[str, Any],
    samples: Sequence[TelemetrySample],
    query: Mapping[str, Any],
    config_paths: Sequence[Path],
    fault_log: Path | None = None,
) -> dict[str, Any]:
    """Write raw, normalized, and provenance artifacts once; existing runs are immutable."""
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, numbers, dots, underscores, or hyphens")
    run_dir = runs_root / run_id
    if run_dir.exists():
        raise FileExistsError(run_dir)

    configuration_hashes: dict[str, str] = {}
    for config_path in config_paths:
        if not config_path.is_file():
            raise FileNotFoundError(f"configuration file not found: {config_path}")
        if config_path.name in configuration_hashes:
            raise ValueError(f"duplicate configuration filename: {config_path.name}")
        configuration_hashes[config_path.name] = sha256_file(config_path)

    fault_ground_truth: str | None = None
    if fault_log is not None:
        if not fault_log.is_file():
            raise FileNotFoundError(f"fault log not found: {fault_log}")
        fault_ground_truth = str(Path("faults") / fault_log.name)

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": datetime.now(UTC).isoformat(),
        "query": dict(query),
        "sample_count": len(samples),
        "raw_telemetry": "raw/prometheus-range.json",
        "normalized_telemetry": "telemetry.jsonl",
        "fault_ground_truth": fault_ground_truth,
        "configuration_hashes": configuration_hashes,
    }
    # Build complete runs in a sibling staging directory.  Publishing through an
    # atomic rename prevents failed writes from consuming an immutable run ID.
    runs_root.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=runs_root))
    try:
        raw_dir = staging_dir / "raw"
        raw_dir.mkdir()
        _write_json(raw_dir / "prometheus-range.json", raw_response)
        _write_jsonl(staging_dir / "telemetry.jsonl", samples)
        if fault_log is not None:
            faults_dir = staging_dir / "faults"
            faults_dir.mkdir()
            shutil.copyfile(fault_log, faults_dir / fault_log.name)
        _write_json(staging_dir / "manifest.json", manifest)
        staging_dir.rename(run_dir)
    except BaseException:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--start", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--end", type=float, required=True, help="Unix timestamp")
    parser.add_argument("--step", type=float, default=5)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--prometheus-url")
    source.add_argument("--prometheus-container", default="network-telemetry-prometheus-1")
    parser.add_argument("--fault-log", type=Path)
    parser.add_argument("--config-path", type=Path, action="append")
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.end <= args.start:
        raise SystemExit("--end must be later than --start")
    if args.step <= 0:
        raise SystemExit("--step must be positive")
    if args.prometheus_url:
        raw_response = query_range(
            args.prometheus_url,
            query=args.query,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    else:
        raw_response = query_range_from_container(
            args.prometheus_container,
            query=args.query,
            start=args.start,
            end=args.end,
            step=args.step,
        )
    samples = validate_prometheus_matrix(raw_response)
    manifest = write_run(
        runs_root=args.runs_root,
        run_id=args.run_id,
        raw_response=raw_response,
        samples=samples,
        query={"query": args.query, "start": args.start, "end": args.end, "step": args.step},
        config_paths=args.config_path or list(DEFAULT_CONFIG_PATHS),
        fault_log=args.fault_log,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
