"""Immutable evidence storage for bounded NetPulse recovery experiments."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .mttr import ThroughputSample

RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def run_paired_trial(
    *,
    run_id: str,
    remediated: bool,
    runs_root: Path,
    duration_seconds: int = 65,
    baseline_seconds: int = 15,
    impairment_seconds: int = 15,
    runner: Any = subprocess.run,
    clock: Any = time.time,
    sleeper: Any = time.sleep,
) -> dict[str, Any]:
    """Run one bounded netem trial and atomically preserve its evidence.

    The caller must start the explicit live remediation override for a remediated
    trial. Cleanup always removes netem and both temporary OSPF costs.
    """
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run_id must contain only letters, numbers, dots, underscores, or hyphens")
    if duration_seconds <= baseline_seconds + impairment_seconds:
        raise ValueError("duration must include a post-recovery observation window")
    if baseline_seconds < 0 or impairment_seconds <= 0:
        raise ValueError(
            "baseline_seconds must be non-negative and impairment_seconds must be positive"
        )
    if remediated and impairment_seconds < 5:
        raise ValueError("remediated trials require at least five impairment seconds")

    def command(args: list[str], *, output: bool = False) -> str:
        completed = runner(args, check=True, capture_output=output, text=output)
        return completed.stdout if output else ""
    cleanup = [
        ["docker", "exec", "clab-netpulse-r1", "tc", "qdisc", "del", "dev", "eth1", "root", "netem"],  # noqa: E501
        ["docker", "exec", "clab-netpulse-r1", "vtysh", "-c", "configure terminal", "-c", "interface eth1", "-c", "no ip ospf cost", "-c", "interface eth2", "-c", "no ip ospf cost", "-c", "end", "-c", "write memory"],  # noqa: E501
    ]
    events: dict[str, Any] = {"run_started": clock(), "mode": "remediated" if remediated else "control"}  # noqa: E501
    try:
        command(["docker", "exec", "clab-netpulse-h2", "sh", "-c", f"pkill -x iperf3 || true; iperf3 --server --one-off --json > /tmp/{run_id}-server.json 2>&1 &"])  # noqa: E501
        command(["docker", "exec", "clab-netpulse-h1", "sh", "-c", f"iperf3 --client 10.0.4.2 --udp --bitrate 10M --cport 51484 --time {duration_seconds} --interval 1 --json > /tmp/{run_id}-client.json 2>&1 &"])  # noqa: E501
        sleeper(baseline_seconds)
        events["fault_start"] = clock()
        command(["docker", "exec", "clab-netpulse-r1", "tc", "qdisc", "replace", "dev", "eth1", "root", "netem", "loss", "100%"])  # noqa: E501
        if remediated:
            sleeper(5)
            events["action_start"] = clock()
            response = command(
                [
                    "curl",
                    "--fail",
                    "--silent",
                    "-X",
                    "POST",
                    "http://127.0.0.1:8000/alerts",
                    "-H",
                    "Content-Type: application/json",
                    "--data",
                    '{"version":"4","status":"firing","alerts":[{"status":"firing","labels":{"alertname":"NetPulseLinkAnomaly","link":"r1-r2"}}]}',
                ],
                output=True,
            )
            try:
                decision = json.loads(response)
                decisions = decision["decisions"]
                applied = any(item.get("status") == "applied" for item in decisions)
            except (AttributeError, KeyError, TypeError, json.JSONDecodeError) as error:
                raise ValueError("remediation endpoint returned an invalid decision") from error
            if decision.get("mode") != "live" or not applied:
                raise ValueError("remediation endpoint did not confirm a live applied action")
            events["remediation"] = {"mode": "live", "status": "applied"}
            events["action_end"] = clock()
            sleeper(impairment_seconds - 5)
        else:
            sleeper(impairment_seconds)
        command(cleanup[0])
        events["impairment_removed"] = clock()
        sleeper(duration_seconds - baseline_seconds - impairment_seconds)
        raw = json.loads(command(["docker", "exec", "clab-netpulse-h2", "cat", f"/tmp/{run_id}-server.json"], output=True))  # noqa: E501
        events["run_finished"] = clock()
        return write_trial_evidence(runs_root=runs_root, run_id=run_id, raw_iperf=raw, events=events, config_paths=[Path("topology/netpulse.clab.yml"), Path("docker-compose.yml")])  # noqa: E501
    finally:
        for item in cleanup:
            try:
                command(item)
            except subprocess.SubprocessError:
                pass


def iperf_receiver_samples(raw_iperf: Mapping[str, Any]) -> list[ThroughputSample]:
    """Convert iperf server intervals into absolute receive-throughput samples."""
    try:
        started = float(raw_iperf["start"]["timestamp"]["timesecs"])
        intervals = raw_iperf["intervals"]
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError("invalid iperf receiver JSON") from error
    if not isinstance(intervals, list):
        raise ValueError("iperf intervals must be a list")
    samples: list[ThroughputSample] = []
    for interval in intervals:
        try:
            summary = interval["sum"]
            samples.append(
                ThroughputSample(
                    timestamp=started + float(summary["end"]),
                    bits_per_second=float(summary["bits_per_second"]),
                )
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid iperf interval") from error
    return samples


def write_trial_evidence(
    *,
    runs_root: Path,
    run_id: str,
    raw_iperf: Mapping[str, Any],
    events: Mapping[str, Any],
    config_paths: Sequence[Path],
    extra_artifacts: Mapping[str, str | bytes] | None = None,
) -> dict[str, Any]:
    """Atomically publish one evidence run after all inputs have been validated."""
    if not run_id or "/" in run_id or (runs_root / run_id).exists():
        raise ValueError("run_id must be new and path-safe")
    hashes: dict[str, str] = {}
    for path in config_paths:
        if not path.is_file() or path.name in hashes:
            raise ValueError(f"invalid configuration path: {path}")
        hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
    iperf_receiver_samples(raw_iperf)
    artifacts = extra_artifacts or {}
    if any(
        Path(name).is_absolute()
        or ".." in Path(name).parts
        or name in {"raw/iperf-receiver.json", "events.json", "manifest.json"}
        for name in artifacts
    ):
        raise ValueError("extra artifact path must be a new relative path")
    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "raw_iperf": "raw/iperf-receiver.json",
        "events": "events.json",
        "configuration_hashes": hashes,
        "artifact_hashes": {
            name: hashlib.sha256(
                value.encode("utf-8") if isinstance(value, str) else value
            ).hexdigest()
            for name, value in sorted(artifacts.items())
        },
    }
    runs_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=runs_root))
    try:
        (staging / "raw").mkdir()
        (staging / "raw" / "iperf-receiver.json").write_text(
            json.dumps(raw_iperf, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (staging / "events.json").write_text(
            json.dumps(dict(events), indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        for name, value in artifacts.items():
            artifact = staging / name
            artifact.parent.mkdir(parents=True, exist_ok=True)
            artifact.write_bytes(value.encode("utf-8") if isinstance(value, str) else value)
        (staging / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        staging.rename(runs_root / run_id)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return manifest
