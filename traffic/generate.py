#!/usr/bin/env python3
"""Generate and optionally run deterministic compressed-day iperf3 traffic."""

from __future__ import annotations

import argparse
import json
import math
import random
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass

BUCKETS_PER_DAY = 24
SOURCE_CONTAINER = "clab-netpulse-h1"
DESTINATION_CONTAINER = "clab-netpulse-h2"
DESTINATION = "10.0.4.2"

CommandRunner = Callable[[Sequence[str]], None]
Sleeper = Callable[[float], None]


@dataclass(frozen=True)
class TrafficEvent:
    """One UDP stream placed in a compressed 24-hour schedule."""

    scenario_id: str
    stream_id: int
    start_offset_seconds: float
    duration_seconds: float
    rate_bps: int
    is_burst: bool


def build_schedule(
    *,
    seed: int,
    compressed_day_seconds: float,
    target_rate_mbps: float,
    scenario_id: str,
) -> list[TrafficEvent]:
    """Return a deterministic 24-bucket traffic schedule without running it."""
    if compressed_day_seconds <= 0 or not float(compressed_day_seconds).is_integer():
        raise ValueError("compressed_day_seconds must be a positive whole number")
    if target_rate_mbps <= 0:
        raise ValueError("target_rate_mbps must be positive")
    if not scenario_id.strip():
        raise ValueError("scenario_id must be non-empty")

    target_rate_bps = int(target_rate_mbps * 1_000_000)
    total_seconds = int(compressed_day_seconds)
    bucket_count = min(BUCKETS_PER_DAY, total_seconds)
    base_duration, extra_seconds = divmod(total_seconds, bucket_count)
    random_source = random.Random(f"{scenario_id}:{seed}")
    burst_count = max(1, round(bucket_count / 12))
    burst_buckets = set(random_source.sample(range(bucket_count), burst_count))
    schedule: list[TrafficEvent] = []
    offset_seconds = 0
    for stream_id in range(bucket_count):
        # A compressed day has a repeatable low-to-high-to-low load shape. The small seeded
        # noise component and sparse bursts make the signal less regular without exceeding cap.
        daily_fraction = 0.55 - 0.25 * math.cos(math.tau * stream_id / bucket_count)
        noise_fraction = random_source.uniform(-0.04, 0.04)
        is_burst = stream_id in burst_buckets
        burst_fraction = 0.12 if is_burst else 0.0
        rate_fraction = min(0.95, max(0.15, daily_fraction + noise_fraction + burst_fraction))
        rate_bps = int(target_rate_bps * rate_fraction)
        schedule.append(
            TrafficEvent(
                scenario_id=scenario_id,
                stream_id=stream_id,
                start_offset_seconds=float(offset_seconds),
                duration_seconds=float(base_duration + (stream_id < extra_seconds)),
                rate_bps=rate_bps,
                is_burst=is_burst,
            )
        )
        offset_seconds += base_duration + (stream_id < extra_seconds)
    return schedule


def iperf_command(event: TrafficEvent) -> list[str]:
    """Return the allow-listed Containerlab iperf3 command for one event."""
    return [
        "docker",
        "exec",
        SOURCE_CONTAINER,
        "iperf3",
        "--client",
        DESTINATION,
        "--udp",
        "--bitrate",
        str(event.rate_bps),
        "--time",
        str(max(1, round(event.duration_seconds))),
    ]


def receiver_command() -> list[str]:
    """Return the idempotent command that starts the h2 iperf3 receiver."""
    return [
        "docker",
        "exec",
        DESTINATION_CONTAINER,
        "sh",
        "-c",
        "pgrep -x iperf3 >/dev/null || iperf3 --server --daemon",
    ]


def run_schedule(
    schedule: Sequence[TrafficEvent],
    *,
    runner: CommandRunner,
    sleeper: Sleeper = time.sleep,
    apply: bool = False,
) -> list[list[str]]:
    """Run a schedule only when explicitly enabled; otherwise return its commands."""
    commands: list[list[str]] = []
    previous_end_offset = 0.0
    if apply:
        runner(receiver_command())
    for event in schedule:
        commands.append(iperf_command(event))
        if apply:
            sleeper(max(0.0, event.start_offset_seconds - previous_end_offset))
            runner(commands[-1])
        previous_end_offset = max(
            previous_end_offset, event.start_offset_seconds + event.duration_seconds
        )
    return commands


def run_command(command: Sequence[str]) -> None:
    """Execute one traffic command and raise when iperf3 does not complete."""
    subprocess.run(command, check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--duration-seconds", type=int, required=True)
    parser.add_argument("--target-rate-mbps", type=float, required=True)
    parser.add_argument("--scenario-id", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="run generated iperf3 commands; omit to print the deterministic plan",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    schedule = build_schedule(
        seed=args.seed,
        compressed_day_seconds=args.duration_seconds,
        target_rate_mbps=args.target_rate_mbps,
        scenario_id=args.scenario_id,
    )
    commands = run_schedule(schedule, runner=run_command, apply=args.apply)
    print(json.dumps([asdict(event) for event in schedule], indent=2))
    if not args.apply:
        print(f"Dry run: {len(commands)} iperf3 commands planned; pass --apply to send traffic.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
