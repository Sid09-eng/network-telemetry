#!/usr/bin/env python3
"""Apply allow-listed synthetic link faults and write JSONL ground truth."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

LINK_ENDPOINTS = {
    "r1-r2": (("r1", "eth1"), ("r2", "eth1")),
    "r1-r3": (("r1", "eth2"), ("r3", "eth1")),
    "r2-r4": (("r2", "eth2"), ("r4", "eth1")),
    "r3-r4": (("r3", "eth2"), ("r4", "eth2")),
}
SUPPORTED_ACTIONS = {"link_down", "link_up"}

CommandRunner = Callable[[list[str]], None]
Clock = Callable[[], datetime]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class FaultEvent:
    """A scheduled, allow-listed topology fault."""

    event_id: str
    planned_offset_seconds: float
    link: str
    action: str
    parameters: Mapping[str, Any]


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def commands_for(event: FaultEvent) -> list[list[str]]:
    """Resolve a fault event to safe Docker commands for both link endpoints."""
    if event.link not in LINK_ENDPOINTS:
        raise ValueError(f"unrecognised NetPulse link: {event.link}")
    if event.action not in SUPPORTED_ACTIONS:
        raise ValueError(f"unsupported fault action: {event.action}")
    state = "down" if event.action == "link_down" else "up"
    return [
        ["docker", "exec", f"clab-netpulse-{router}", "ip", "link", "set", "dev", interface, state]
        for router, interface in LINK_ENDPOINTS[event.link]
    ]


def write_jsonl(log_path: Path, record: Mapping[str, Any]) -> None:
    """Append one immutable ground-truth record."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, sort_keys=True) + "\n")


def apply_fault(
    event: FaultEvent,
    *,
    runner: CommandRunner,
    log_path: Path,
    planned_at: datetime,
    clock: Clock = lambda: datetime.now(UTC),
) -> dict[str, Any]:
    """Apply both endpoints or compensate already-applied endpoints on failure."""
    record: dict[str, Any] = {
        "event_id": event.event_id,
        "planned_at": _timestamp(planned_at),
        "applied_at": None,
        "target_link": event.link,
        "action": event.action,
        "parameters": dict(event.parameters),
        "outcome": "unapplied",
        "rollback": "not-needed",
        "applied_endpoints": [],
        "rollback_endpoints": [],
    }
    applied_commands: list[list[str]] = []
    try:
        for command in commands_for(event):
            runner(command)
            applied_commands.append(command)
            record["applied_endpoints"].append(command[2])
    except (OSError, RuntimeError, subprocess.SubprocessError, ValueError) as error:
        record["error"] = str(error)
        if applied_commands:
            rollback_action = "link_up" if event.action == "link_down" else "link_down"
            rollback_event = FaultEvent(
                event_id=f"{event.event_id}-rollback",
                planned_offset_seconds=event.planned_offset_seconds,
                link=event.link,
                action=rollback_action,
                parameters={},
            )
            try:
                rollback_commands = commands_for(rollback_event)[: len(applied_commands)]
                for command in reversed(rollback_commands):
                    runner(command)
                    record["rollback_endpoints"].append(command[2])
            except (
                OSError,
                RuntimeError,
                subprocess.SubprocessError,
                ValueError,
            ) as rollback_error:
                record["outcome"] = "partial-failure"
                record["rollback"] = "failed"
                record["rollback_error"] = str(rollback_error)
            else:
                record["rollback"] = "succeeded"
    else:
        record["outcome"] = "applied"
        record["applied_at"] = _timestamp(clock())
    write_jsonl(log_path, record)
    return record


def _fault_event(item: Mapping[str, Any]) -> FaultEvent:
    return FaultEvent(
        event_id=str(item["id"]),
        planned_offset_seconds=float(item["at_seconds"]),
        link=str(item["link"]),
        action=str(item["action"]),
        parameters=dict(item.get("parameters", {})),
    )


def load_scenario(path: Path) -> list[FaultEvent]:
    """Load fault events from a YAML scenario, validating its top-level shape."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("faults"), list):
        raise ValueError("scenario must define a faults list")
    events = [_fault_event(item) for item in data["faults"]]
    recovery_events: list[FaultEvent] = []
    for event in events:
        restore_after = event.parameters.get("restore_after_seconds")
        if event.action == "link_down" and restore_after is not None:
            restore_delay = float(restore_after)
            if restore_delay <= 0:
                raise ValueError("restore_after_seconds must be positive")
            recovery_events.append(
                FaultEvent(
                    event_id=f"{event.event_id}-restore",
                    planned_offset_seconds=event.planned_offset_seconds + restore_delay,
                    link=event.link,
                    action="link_up",
                    parameters={"recovery_for": event.event_id},
                )
            )
    return sorted(events + recovery_events, key=lambda event: event.planned_offset_seconds)


def run_command(command: list[str]) -> None:
    """Execute an allow-listed link command."""
    subprocess.run(command, check=True)


def execute_scenario(
    events: Sequence[FaultEvent],
    *,
    log_path: Path,
    apply: bool,
    runner: CommandRunner = run_command,
    clock: Clock = lambda: datetime.now(UTC),
    sleeper: Sleeper = time.sleep,
) -> list[dict[str, Any]]:
    """Run scheduled events, or write non-applied dry-run ground truth records."""
    started_at = clock()
    previous_offset = 0.0
    records: list[dict[str, Any]] = []
    for event in sorted(events, key=lambda candidate: candidate.planned_offset_seconds):
        planned_at = started_at + timedelta(seconds=event.planned_offset_seconds)
        if not apply:
            record = {
                "event_id": event.event_id,
                "planned_at": _timestamp(planned_at),
                "applied_at": None,
                "target_link": event.link,
                "action": event.action,
                "parameters": dict(event.parameters),
                "outcome": "dry-run",
            }
            write_jsonl(log_path, record)
        else:
            sleeper(max(0.0, event.planned_offset_seconds - previous_offset))
            record = apply_fault(
                event,
                runner=runner,
                log_path=log_path,
                planned_at=planned_at,
                clock=clock,
            )
        records.append(record)
        previous_offset = event.planned_offset_seconds
    return records


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--log-path", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="execute link changes; omit to write dry-run ground truth only",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    events = load_scenario(args.scenario)
    records = execute_scenario(events, log_path=args.log_path, apply=args.apply)
    print(json.dumps(records, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
