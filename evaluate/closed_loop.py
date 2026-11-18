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
    rollback_timeout_seconds: int = 360
    post_action_seconds: int = 15
    traffic_rate_mbps: int = 25
    impairment_rate: str = "1mbit"
    poll_seconds: float = 2.0
    command_timeout_seconds: float = 20.0
    detection_threshold_max: float = 0.01
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
        for name in ("command_timeout_seconds", "detection_threshold_max"):
            value = getattr(self, name)
            if not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite, positive, and numeric")

    @property
    def duration_seconds(self) -> int:
        """Keep the iperf flow alive through detection and post-action recovery evidence."""
        return (
            self.baseline_seconds
            + self.detection_timeout_seconds
            + self.post_action_seconds
            + 20
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
            "ip ospf cost 20",
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


def _audit_records(
    runner: CommandRunner, *, timeout_seconds: float
) -> tuple[str, list[dict[str, Any]]]:
    try:
        completed = runner(
            ["docker", "compose", "exec", "-T", "remediation", "cat", "/data/audit.jsonl"],
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except (OSError, subprocess.SubprocessError):
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


def _audit_snapshot(
    runner: CommandRunner,
    status: str,
    *,
    boundary: int,
    timeout_seconds: float,
) -> tuple[str, list[dict[str, Any]]] | None:
    snapshot = _audit_records(runner, timeout_seconds=timeout_seconds)
    return snapshot if _matching_audit(snapshot[1][boundary:], status) else None


def _detector_threshold(metrics: str) -> float | None:
    # The detector holds the configured threshold under ``unknown`` until the
    # first per-link residual is published.  During baseline warm-up that
    # global value is the only truthful preflight source for r1-r2.
    for link in (LINK, "unknown"):
        match = re.search(
            rf'netpulse_anomaly_threshold\{{link="{link}"\}} ([0-9.eE+-]+)$', metrics, re.M
        )
        if match:
            return float(match.group(1))
    return None


def require_trial_detection_profile(metrics: str, config: ClosedLoopConfig) -> None:
    """Require a threshold sensitive enough for the rate-limited trial profile."""
    threshold = _detector_threshold(metrics)
    if threshold is None or threshold > config.detection_threshold_max:
        raise ValueError(
            "closed-loop trial requires a detector threshold at or below "
            f"{config.detection_threshold_max:g}; restart monitoring with the reviewed "
            "trial profile"
        )


def _route_uses_alternate_path(payload: object) -> bool:
    """Accept FRR JSON only when the r1-r3 interface appears in a selected route."""
    if isinstance(payload, Mapping):
        if payload.get("interfaceName") == ALTERNATE_INTERFACE:
            return True
        return any(_route_uses_alternate_path(value) for value in payload.values())
    if isinstance(payload, list):
        return any(_route_uses_alternate_path(value) for value in payload)
    return False


def _route_uses_primary_path(payload: object) -> bool:
    """Accept a route only when the initial traffic path is r1-r2, not ECMP."""
    interfaces: set[str] = set()

    def collect(value: object) -> None:
        if isinstance(value, Mapping):
            interface = value.get("interfaceName")
            if isinstance(interface, str):
                interfaces.add(interface)
            for child in value.values():
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(payload)
    return PRIMARY_INTERFACE in interfaces and ALTERNATE_INTERFACE not in interfaces


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
    if (runs_root / config.run_id).exists():
        raise ValueError("run_id must be new and path-safe")
    require_live_mode(_get_json(f"{config.remediation_url}/healthz"))
    require_trial_detection_profile(_get_text(f"{config.detector_url}/metrics"), config)
    commands = trial_commands(config)
    events: dict[str, Any] = {"run_started": clock(), "link": LINK, "mode": "live"}
    raw: dict[str, str] = {}
    _, initial_audit_records = _audit_records(
        runner, timeout_seconds=config.command_timeout_seconds
    )
    audit_boundary = len(initial_audit_records)

    def command(args: list[str], *, output: bool = False) -> str:
        completed = runner(
            args,
            check=True,
            capture_output=output,
            text=output,
            timeout=config.command_timeout_seconds,
        )
        return completed.stdout if output else ""

    def cleanup_temporary_state() -> list[str]:
        errors: list[str] = []
        for cleanup in commands["cleanup"]:  # type: ignore[union-attr]
            try:
                completed = runner(
                    cleanup,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=config.command_timeout_seconds,
                )
                output = (completed.stdout + completed.stderr).strip()
                already_removed = cleanup == commands["cleanup"][0] and any(
                    marker in output for marker in ("No such file", "Cannot find")
                )
                if completed.returncode and not already_removed:
                    errors.append(output or f"cleanup returned {completed.returncode}")
            except (OSError, subprocess.SubprocessError) as error:
                errors.append(str(error))
        return errors

    try:
        command(commands["route_bias"])  # type: ignore[arg-type]

        def primary_route() -> str | None:
            route = command(
                [
                    "docker",
                    "exec",
                    "clab-netpulse-r1",
                    "vtysh",
                    "-c",
                    "show ip route 10.0.4.0/24 json",
                ],
                output=True,
            )
            return route if _route_uses_primary_path(json.loads(route)) else None

        raw["raw/r1-route-before-fault.json"] = _wait_for(
            primary_route,
            timeout_seconds=config.post_action_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        events["primary_path_observed"] = clock()
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
        pre_fault_audit_text, pre_fault_audits = _audit_records(
            runner, timeout_seconds=config.command_timeout_seconds
        )
        if _matching_audit(pre_fault_audits[audit_boundary:], "applied"):
            raise ValueError(
                "remediation acted before fault injection; wait for alert state to settle"
            )
        raw["raw/remediation-audit-before-fault.jsonl"] = pre_fault_audit_text
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
            lambda: _audit_snapshot(
                runner,
                "applied",
                boundary=audit_boundary,
                timeout_seconds=config.command_timeout_seconds,
            ),
            timeout_seconds=config.detection_timeout_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        raw["raw/remediation-audit-after-action.jsonl"] = audit_text
        events["action_applied"] = _matching_audit(applied[audit_boundary:], "applied")[
            "timestamp"
        ]
        events["action_observed_at"] = clock()

        def alternate_route() -> str | None:
            route = command(
                [
                    "docker",
                    "exec",
                    "clab-netpulse-r1",
                    "vtysh",
                    "-c",
                    "show ip route 10.0.4.0/24 json",
                ],
                output=True,
            )
            return route if _route_uses_alternate_path(json.loads(route)) else None

        raw["raw/r1-route-after-action.json"] = _wait_for(
            alternate_route,
            timeout_seconds=config.post_action_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        events["alternate_path_observed"] = clock()

        def complete_receiver() -> dict[str, Any] | None:
            try:
                receiver = json.loads(
                    command(
                        [
                            "docker",
                            "exec",
                            "clab-netpulse-h2",
                            "cat",
                            f"/tmp/{config.run_id}-server.json",
                        ],
                        output=True,
                    )
                )
                samples = iperf_receiver_samples(receiver)
            except (ValueError, json.JSONDecodeError, subprocess.SubprocessError):
                return None
            required_end = float(events["run_started"]) + config.duration_seconds - 2
            return receiver if samples and samples[-1].timestamp >= required_end else None

        raw_iperf = _wait_for(
            complete_receiver,
            timeout_seconds=max(
                config.command_timeout_seconds,
                float(events["run_started"]) + config.duration_seconds - clock()
                + config.command_timeout_seconds,
            ),
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
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
        if recovery.mttr_seconds is None:
            raise ValueError("receiver throughput did not meet the sustained restoration criterion")

        events["impairment_removed"] = clock()
        command(commands["clear_impairment"])  # type: ignore[arg-type]
        audit_text, rolled_back = _wait_for(
            lambda: _audit_snapshot(
                runner,
                "rolled-back",
                boundary=audit_boundary,
                timeout_seconds=config.command_timeout_seconds,
            ),
            timeout_seconds=config.rollback_timeout_seconds,
            interval_seconds=config.poll_seconds,
            clock=clock,
            sleeper=sleeper,
        )
        raw["raw/remediation-audit-after-rollback.jsonl"] = audit_text
        events["action_rolled_back"] = _matching_audit(
            rolled_back[audit_boundary:], "rolled-back"
        )["timestamp"]
        cleanup_errors = cleanup_temporary_state()
        if cleanup_errors:
            raise RuntimeError("closed-loop cleanup incomplete: " + "; ".join(cleanup_errors))
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
        return manifest
    finally:
        cleanup_errors = cleanup_temporary_state()
        if cleanup_errors:
            raise RuntimeError("closed-loop cleanup incomplete: " + "; ".join(cleanup_errors))


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
