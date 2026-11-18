"""Serialized remediation orchestration, audit records, and Prometheus metrics."""

from __future__ import annotations

import json
import math
import threading
import time
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .actions import OspfCostAdapter
from .audit import append_audit
from .policy import CooldownPolicy, PolicyError, RemediationTarget, parse_alertmanager_payload

MonotonicClock = Callable[[], float]


class RemediationMetrics:
    """Small dependency-free Prometheus registry for remediation outcomes."""

    def __init__(self) -> None:
        self._counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        self._latencies: dict[tuple[str, str], float] = {}

    def record(self, *, mode: str, status: str, latency_seconds: float) -> None:
        if not math.isfinite(latency_seconds) or latency_seconds < 0:
            raise ValueError("latency_seconds must be finite and non-negative")
        key = (mode, status)
        self._counts[key] += 1
        self._latencies[key] = latency_seconds

    def render(self) -> str:
        """Render counters and last observed latency as Prometheus text exposition."""
        lines = [
            "# TYPE netpulse_remediation_actions_total counter",
            "# TYPE netpulse_remediation_last_latency_seconds gauge",
        ]
        for mode, status in sorted(self._counts):
            labels = f'mode="{mode}",status="{status}"'
            count = self._counts[mode, status]
            lines.append(f"netpulse_remediation_actions_total{{{labels}}} {count}")
            lines.append(
                "netpulse_remediation_last_latency_seconds"
                f"{{{labels}}} {self._latencies[mode, status]}"
            )
        return "\n".join(lines) + "\n"


class RemediationService:
    """Perform one safe, auditable remediation decision at a time."""

    def __init__(
        self,
        *,
        adapter: OspfCostAdapter,
        cooldown_seconds: float,
        audit_path: Path,
        global_cooldown_seconds: float = 0.0,
        monotonic_clock: MonotonicClock = time.monotonic,
    ) -> None:
        self.adapter = adapter
        self.policy = CooldownPolicy(cooldown_seconds=cooldown_seconds)
        if not math.isfinite(global_cooldown_seconds) or global_cooldown_seconds < 0:
            raise ValueError("global_cooldown_seconds must be finite and non-negative")
        self.global_cooldown_seconds = global_cooldown_seconds
        self._last_action_at: float | None = None
        self._applied_targets: dict[tuple[str, str], RemediationTarget] = {}
        self.audit_path = audit_path
        self.monotonic_clock = monotonic_clock
        self._lock = threading.Lock()
        self._metrics = RemediationMetrics()
        self._restore_applied_targets()

    def _restore_applied_targets(self) -> None:
        """Recover live costs that were durably applied before a service restart."""
        if self.adapter.dry_run or not self.audit_path.is_file():
            return
        for line in self.audit_path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
                target_data = record["target"]
                target = RemediationTarget(
                    link=str(target_data["link"]),
                    router=str(target_data["router"]),
                    interface=str(target_data["interface"]),
                    fingerprint=str(target_data["fingerprint"]),
                )
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            key = (target.router, target.interface)
            if record.get("mode") != "live":
                continue
            if record.get("status") == "applied":
                self._applied_targets[key] = target
            elif record.get("status") == "rolled-back":
                self._applied_targets.pop(key, None)

    @property
    def mode(self) -> str:
        """Return the operational mode which is attached to every metric and audit row."""
        return "dry-run" if self.adapter.dry_run else "live"

    def metrics(self) -> str:
        """Return a thread-safe snapshot of remediation metrics."""
        with self._lock:
            return self._metrics.render()

    def _append_rejected(self, error: PolicyError) -> None:
        with self._lock:
            record = {
                "timestamp": datetime.now(UTC).isoformat(),
                "mode": self.mode,
                "status": "rejected",
                "reason": str(error),
            }
            append_audit(self.audit_path, record)
            self._metrics.record(mode=self.mode, status="rejected", latency_seconds=0.0)

    def handle(self, payload: object) -> list[dict[str, Any]]:
        """Validate an Alertmanager payload and serialize all policy/action decisions."""
        try:
            is_resolved = isinstance(payload, dict) and payload.get("status") == "resolved"
            targets = parse_alertmanager_payload(payload, include_resolved=is_resolved)
        except PolicyError as error:
            self._append_rejected(error)
            raise
        with self._lock:
            if is_resolved:
                return [self._resolve_target(target) for target in targets]
            if not targets:
                record = {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "mode": self.mode,
                    "status": "resolved",
                }
                append_audit(self.audit_path, record)
                self._metrics.record(mode=self.mode, status="resolved", latency_seconds=0.0)
                return [record]
            return [self._handle_target(target) for target in targets]

    def _handle_target(self, target: RemediationTarget) -> dict[str, Any]:
        now = self.monotonic_clock()
        if not self.policy.allow(target, now=now):
            decision = self._decision(target, status="cooldown", latency_seconds=0.0)
            append_audit(self.audit_path, decision)
            self._metrics.record(mode=self.mode, status="cooldown", latency_seconds=0.0)
            return decision

        if (
            self._last_action_at is not None
            and now - self._last_action_at < self.global_cooldown_seconds
        ):
            decision = self._decision(target, status="global-cooldown", latency_seconds=0.0)
            append_audit(self.audit_path, decision)
            self._metrics.record(mode=self.mode, status="global-cooldown", latency_seconds=0.0)
            return decision
        self._last_action_at = now

        result = self.adapter.apply(target)
        decision = self._decision(
            target,
            status=result.status,
            latency_seconds=result.latency_seconds,
            command=result.command,
            action_output=result.action_output,
            rollback_status=result.rollback_status,
            rollback_output=result.rollback_output,
        )
        append_audit(self.audit_path, decision)
        self._metrics.record(
            mode=self.mode,
            status=result.status,
            latency_seconds=result.latency_seconds,
        )
        if result.status == "applied":
            self._applied_targets[target.router, target.interface] = target
        return decision

    def _resolve_target(self, target: RemediationTarget) -> dict[str, Any]:
        """Rollback only the cost previously applied for this resolved alert."""
        key = (target.router, target.interface)
        applied = self._applied_targets.get(key)
        if applied is None:
            decision = self._decision(target, status="resolved", latency_seconds=0.0)
            append_audit(self.audit_path, decision)
            self._metrics.record(mode=self.mode, status="resolved", latency_seconds=0.0)
            return decision

        result = self.adapter.rollback(applied)
        decision = self._decision(
            applied,
            status=result.status,
            latency_seconds=result.latency_seconds,
            command=result.command,
            action_output=result.action_output,
            rollback_status=result.rollback_status,
            rollback_output=result.rollback_output,
        )
        append_audit(self.audit_path, decision)
        self._metrics.record(
            mode=self.mode,
            status=result.status,
            latency_seconds=result.latency_seconds,
        )
        if result.status == "rolled-back":
            self._applied_targets.pop(key, None)
        return decision

    def _decision(
        self,
        target: RemediationTarget,
        *,
        status: str,
        latency_seconds: float,
        command: Sequence[str] | None = None,
        action_output: str = "",
        rollback_status: str = "not-needed",
        rollback_output: str = "",
    ) -> dict[str, Any]:
        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "mode": self.mode,
            "status": status,
            "latency_seconds": latency_seconds,
            "target": {
                "link": target.link,
                "router": target.router,
                "interface": target.interface,
                "fingerprint": target.fingerprint,
            },
            "command": list(command) if command else None,
            "action_output": action_output,
            "rollback_status": rollback_status,
            "rollback_output": rollback_output,
        }
