"""Allow-listed Docker/FRR OSPF-cost adapter for NetPulse remediation."""

from __future__ import annotations

import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass

from .policy import LINK_TARGETS, RemediationTarget

CommandRunner = Callable[[list[str], float], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ActionResult:
    """Audit-ready outcome of a safe remediation attempt."""

    status: str
    command: list[str]
    action_output: str
    rollback_status: str
    rollback_output: str
    latency_seconds: float


def run_command(command: list[str], timeout_seconds: float) -> subprocess.CompletedProcess[str]:
    """Run one already allow-listed Docker command and retain both output streams."""
    return subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _output(error: BaseException) -> str:
    """Normalize subprocess output without losing failure diagnostics for the audit log."""
    parts: list[str] = []
    values = (
        getattr(error, "output", None),
        getattr(error, "stdout", None),
        getattr(error, "stderr", None),
    )
    for value in values:
        if value:
            text = value.decode() if isinstance(value, bytes) else str(value)
            if text not in parts:
                parts.append(text)
    if not parts:
        parts.append(str(error))
    return "\n".join(parts).strip()


class OspfCostAdapter:
    """Apply one configured OSPF cost, attempting a safe rollback on command failure."""

    def __init__(
        self,
        *,
        dry_run: bool,
        cost: int = 100,
        timeout_seconds: float = 10.0,
        runner: CommandRunner = run_command,
    ) -> None:
        if not 1 <= cost <= 65_535:
            raise ValueError("cost must be between 1 and 65535")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.dry_run = dry_run
        self.cost = cost
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    def _command(self, target: RemediationTarget, directive: str) -> list[str]:
        if LINK_TARGETS.get(target.link) != (target.router, target.interface):
            raise ValueError("target is not allow-listed")
        return [
            "docker",
            "exec",
            f"clab-netpulse-{target.router}",
            "vtysh",
            "-c",
            "configure terminal",
            "-c",
            f"interface {target.interface}",
            "-c",
            directive,
            "-c",
            "end",
            "-c",
            "write memory",
        ]

    def apply(self, target: RemediationTarget) -> ActionResult:
        """Increase cost or record a dry-run; roll back only a failed live attempt."""
        command = self._command(target, f"ip ospf cost {self.cost}")
        if self.dry_run:
            return ActionResult(
                status="dry-run",
                command=command,
                action_output="not executed: NETPULSE_DRY_RUN is enabled",
                rollback_status="not-needed",
                rollback_output="",
                latency_seconds=0.0,
            )

        started = time.monotonic()
        try:
            completed = self.runner(command, self.timeout_seconds)
        except (OSError, subprocess.SubprocessError) as error:
            rollback = self._command(target, "no ip ospf cost")
            try:
                rollback_result = self.runner(rollback, self.timeout_seconds)
            except (OSError, subprocess.SubprocessError) as rollback_error:
                rollback_status = "failed"
                rollback_output = _output(rollback_error)
            else:
                rollback_status = "succeeded"
                rollback_output = (rollback_result.stdout + rollback_result.stderr).strip()
            return ActionResult(
                status="failed",
                command=command,
                action_output=_output(error),
                rollback_status=rollback_status,
                rollback_output=rollback_output,
                latency_seconds=time.monotonic() - started,
            )
        return ActionResult(
            status="applied",
            command=command,
            action_output=(completed.stdout + completed.stderr).strip(),
            rollback_status="not-needed",
            rollback_output="",
            latency_seconds=time.monotonic() - started,
        )
