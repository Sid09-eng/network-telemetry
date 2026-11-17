"""Run one explicit, bounded detection-to-restoration demonstration."""

from __future__ import annotations

import json
import math
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from .experiment import RUN_ID_PATTERN, iperf_receiver_samples, write_trial_evidence
from .mttr import evaluate_recovery

NETEM_RATE_PATTERN = re.compile(r"^[1-9][0-9]*(?:bit|kbit|mbit|gbit)$")
LINK = "r1-r2"
PRIMARY_INTERFACE = "eth1"
ALTERNATE_INTERFACE = "eth2"

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
Clock = Callable[[], float]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class ClosedLoopConfig:
    """Fixed bounds for the single allow-listed closed-loop demonstration."""

    run_id: str
    baseline_seconds: int = 75
    detection_timeout_seconds: int = 120
    rollback_timeout_seconds: int = 120
    post_action_seconds: int = 15
    traffic_rate_mbps: int = 25
    impairment_rate: str = "1mbit"
    poll_seconds: float = 2.0
    prometheus_url: str = "http://127.0.0.1:9090"
    detector_url: str = "http://127.0.0.1:8001"
    remediation_url: str = "http://127.0.0.1:8000"

    def __post_init__(self) -> None:
        if not RUN_ID_PATTERN.fullmatch(self.run_id):
            raise ValueError(
                "run_id must contain only letters, numbers, dots, underscores, or hyphens"
            )
        for name in (
            "baseline_seconds",
            "detection_timeout_seconds",
            "rollback_timeout_seconds",
            "post_action_seconds",
            "traffic_rate_mbps",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if (
            not isinstance(self.poll_seconds, (int, float))
            or not math.isfinite(self.poll_seconds)
            or self.poll_seconds <= 0
        ):
            raise ValueError("poll_seconds must be finite, positive, and numeric")
        if not NETEM_RATE_PATTERN.fullmatch(self.impairment_rate):
            raise ValueError("impairment_rate must be a positive tc rate")

    @property
    def duration_seconds(self) -> int:
        """Keep the iperf flow alive through bounded detection and rollback windows."""
        return (
            self.baseline_seconds
            + self.detection_timeout_seconds
            + self.rollback_timeout_seconds
            + self.post_action_seconds
            + 10
        )


def require_live_mode(response: Mapping[str, object]) -> None:
    """Reject a trial unless the running remediation API confirms live mode."""
    if response.get("status") != "ok" or response.get("mode") != "live":
        raise ValueError("closed-loop trial requires live remediation mode")


def trial_commands(config: ClosedLoopConfig) -> dict[str, list[list[str]] | list[str]]:
    """Return the fixed, reviewable command set used by the trial."""
    r1 = "clab-netpulse-r1"
    return {
        "route_bias": [
            "docker",
            "exec",
            r1,
            "vtysh",
            "-c",
            "configure terminal",
            "-c",
            f"interface {ALTERNATE_INTERFACE}",
            "-c",
            "ip ospf cost 10",
            "-c",
            "end",
            "-c",
            "write memory",
        ],
        "impair": [
            [
                "docker",
                "exec",
                r1,
                "tc",
                "qdisc",
                "replace",
                "dev",
                PRIMARY_INTERFACE,
                "root",
                "netem",
                "rate",
                config.impairment_rate,
            ]
        ],
        "clear_impairment": [
            "docker",
            "exec",
            r1,
            "tc",
            "qdisc",
            "del",
            "dev",
            PRIMARY_INTERFACE,
            "root",
            "netem",
        ],
        "cleanup": [
            [
                "docker",
                "exec",
                r1,
                "tc",
                "qdisc",
                "del",
                "dev",
                PRIMARY_INTERFACE,
                "root",
                "netem",
            ],
            [
                "docker",
                "exec",
                r1,
                "vtysh",
                "-c",
                "configure terminal",
                "-c",
                f"interface {PRIMARY_INTERFACE}",
                "-c",
                "no ip ospf cost",
                "-c",
                f"interface {ALTERNATE_INTERFACE}",
                "-c",
                "no ip ospf cost",
                "-c",
                "end",
                "-c",
                "write memory",
            ],
        ],
    }


def _get_json(url: str) -> dict[str, Any]:
    with urlopen(url, timeout=5.0) as response:  # noqa: S310
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object from {url}")
    return payload


def _get_text(url: str) -> str:
    with urlopen(url, timeout=5.0) as response:  # noqa: S310
        return response.read().decode("utf-8")


def _wait_for(
    predicate: Callable[[], Any | None],
    *,
    timeout_seconds: float,
    interval_seconds: float,
    clock: Clock,
    sleeper: Sleeper,
) -> Any:
    deadline = clock() + timeout_seconds
    while clock() < deadline:
        value = predicate()
        if value is not None:
            return value
        sleeper(min(interval_seconds, max(0.0, deadline - clock())))
    raise TimeoutError(f"condition was not observed within {timeout_seconds:g} seconds")


def _detector_drop(metrics: str) -> bool:
    return bool(
        re.search(rf'netpulse_anomaly_active\{{link="{LINK}"\}} 1(?:\.0+)?$', metrics, re.M)
        and re.search(rf'netpulse_anomaly_residual\{{link="{LINK}"\}} -', metrics, re.M)
    )


def _alert_firing(payload: Mapping[str, Any]) -> bool:
    data = payload.get("data")
    alerts = data.get("alerts") if isinstance(data, Mapping) else None
    return isinstance(alerts, list) and any(
        isinstance(alert, Mapping)
        and alert.get("state") == "firing"
        and isinstance(alert.get("labels"), Mapping)
        and alert["labels"].get("alertname") == "NetPulseLinkAnomaly"
        and alert["labels"].get("link") == LINK
        for alert in alerts
    )


def _audit_records(runner: CommandRunner) -> tuple[str, list[dict[str, Any]]]:
    try:
        completed = runner(
            ["docker", "compose", "exec", "-T", "remediation", "cat", "/data/audit.jsonl"],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError:
        return "", []
    text = completed.stdout
    return text, [json.loads(line) for line in text.splitlines() if line.strip()]


def _matching_audit(records: list[dict[str, Any]], status: str) -> dict[str, Any] | None:
    for record in reversed(records):
        target = record.get("target")
        if (
            record.get("status") == status
            and isinstance(target, Mapping)
            and target.get("link") == LINK
        ):
            return record
    return None


def _detector_snapshot(config: ClosedLoopConfig) -> str | None:
    metrics = _get_text(f"{config.detector_url}/metrics")
    return metrics if _detector_drop(metrics) else None


def _alert_snapshot(config: ClosedLoopConfig) -> dict[str, Any] | None:
    alerts = _get_json(f"{config.prometheus_url}/api/v1/alerts")
    return alerts if _alert_firing(alerts) else None


def _audit_snapshot(runner: CommandRunner, status: str) -> tuple[str, list[dict[str, Any]]] | None:
    snapshot = _audit_records(runner)
    return snapshot if _matching_audit(snapshot[1], status) else None


def run_closed_loop_trial(
    *,
    config: ClosedLoopConfig,
    runs_root: Path,
    runner: CommandRunner = subprocess.run,
    clock: Clock = time.time,
    sleeper: Sleeper = time.sleep,
) -> dict[str, Any]:
    """Inject one rate fault and preserve detection, action, and restoration evidence.

    The caller is responsible for starting ``make monitoring-live-up`` with both explicit live
    environment flags.  This function refuses dry-run mode before it changes routing or qdisc
    state and removes both temporary states even if evidence collection fails.
    """
    require_live_mode(_get_json(f"{config.remediation_url}/healthz"))
    commands = trial_commands(config)
    events: dict[str, Any] = {"run_started": clock(), "link": LINK, "mode": "live"}
    raw: dict[str, str] = {}

    def command(args: list[str], *, output: bool = False) -> str:
        completed = runner(args, check=True, capture_output=output, text=output)
        return completed.stdout if output else ""

    try:
        command(commands["route_bias"])  # type: ignore[arg-type]
        server_command = (
            f"pkill -x iperf3 || true; iperf3 --server --one-off --json "
            f"> /tmp/{config.run_id}-server.json 2>&1 &"
        )
        command(
            [
                "docker",
                "exec",
                "clab-netpulse-h2",
                "sh",
                "-c",
                server_command,
            ]
        )
        client_command = (
            f"iperf3 --client 10.0.4.2 --udp --bitrate {config.traffic_rate_mbps}M "
            f"--cport 51484 --time {config.duration_seconds} --interval 1 --json "
            f"> /tmp/{config.run_id}-client.json 2>&1 &"
        )
        command(
            [
                "docker",
                "exec",
                "clab-netpulse-h1",
                "sh",
                "-c",
                client_command,
            ]
        )
        sleeper(config.baseline_seconds)
        events["fault_start"] = clock()
        command(commands["impair"][0])  # type: ignore[index]

        raw["raw/detector-after-fault.txt"] = _wait_for(
            lambda: _detector_snapshot(config),
            timeout_seconds=config.detection_timeout_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        events["detector_active"] = clock()
        raw["raw/prometheus-alerts.json"] = json.dumps(
            _wait_for(
                lambda: _alert_snapshot(config),
                timeout_seconds=config.detection_timeout_seconds,
                interval_seconds=config.poll_seconds,
                clock=clock,
                sleeper=sleeper,
            ),
            indent=2,
            sort_keys=True,
        )
        events["alert_firing"] = clock()

        audit_text, applied = _wait_for(
            lambda: _audit_snapshot(runner, "applied"),
            timeout_seconds=config.detection_timeout_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        raw["raw/remediation-audit-after-action.jsonl"] = audit_text
        events["action_applied"] = _matching_audit(applied, "applied")["timestamp"]
        events["action_observed_at"] = clock()
        events["impairment_removed"] = clock()
        command(commands["clear_impairment"])  # type: ignore[arg-type]
        sleeper(config.post_action_seconds)

        audit_text, rolled_back = _wait_for(
            lambda: _audit_snapshot(runner, "rolled-back"),
            timeout_seconds=config.rollback_timeout_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        raw["raw/remediation-audit-after-rollback.jsonl"] = audit_text
        events["action_rolled_back"] = _matching_audit(rolled_back, "rolled-back")["timestamp"]

        remaining = max(0.0, events["run_started"] + config.duration_seconds - clock())
        sleeper(remaining)
        raw_iperf = json.loads(
            command(
                ["docker", "exec", "clab-netpulse-h2", "cat", f"/tmp/{config.run_id}-server.json"],
                output=True,
            )
        )
        events["run_finished"] = clock()
        recovery = evaluate_recovery(
            iperf_receiver_samples(raw_iperf),
            fault_start=float(events["fault_start"]),
            action_end=float(events["action_observed_at"]),
        )
        events["restoration_time"] = recovery.restoration_time
        events["mttr_seconds"] = recovery.mttr_seconds
        events["restoration_reason"] = recovery.reason
        raw["raw/recovery.json"] = json.dumps(asdict(recovery), indent=2, sort_keys=True)
        raw["raw/r1-route.json"] = command(
            ["docker", "exec", "clab-netpulse-r1", "vtysh", "-c", "show ip route 10.0.4.0/24 json"],
            output=True,
        )
        manifest = write_trial_evidence(
            runs_root=runs_root,
            run_id=config.run_id,
            raw_iperf=raw_iperf,
            events=events,
            config_paths=[
                Path("docker-compose.yml"),
                Path("docker-compose.live.yml"),
                Path("monitoring/alert_rules.yml"),
                Path("forecast/worker.py"),
                Path("remediation/actions.py"),
            ],
            extra_artifacts=raw,
        )
        if recovery.mttr_seconds is None:
            raise ValueError("receiver throughput did not meet the sustained restoration criterion")
        return manifest
    finally:
        for cleanup in commands["cleanup"]:  # type: ignore[union-attr]
            try:
                command(cleanup)
            except subprocess.SubprocessError:
                pass


def main() -> int:
    """Run the explicit live trial only when the operator passes --apply."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--runs-root", type=Path, default=Path("runs"))
    parser.add_argument("--apply", action="store_true", help="run the live controlled trial")
    args = parser.parse_args()
    if not args.apply:
        parser.error("--apply is required; this trial changes temporary qdisc and OSPF state")
    manifest = run_closed_loop_trial(
        config=ClosedLoopConfig(run_id=args.run_id), runs_root=args.runs_root
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
