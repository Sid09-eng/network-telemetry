#!/usr/bin/env python3
"""Check OSPF adjacency and primary ECMP route health for NetPulse."""

from __future__ import annotations

import argparse
import re
import subprocess
import time
from collections.abc import Callable, Sequence

LAB_NAME = "netpulse"
EXPECTED_FULL_NEIGHBOURS = {"r1": 2, "r2": 2, "r3": 2, "r4": 2}
ECMP_ROUTE = {"r1": ("10.0.4.0/24", 2)}
FULL_STATE_PATTERN = re.compile(r"\bfull(?:/[a-z-]+)?\b", re.IGNORECASE)
NEXT_HOP_PATTERN = re.compile(r"(?:\bvia\s+|^\s*\*\s+)(\d{1,3}(?:\.\d{1,3}){3})", re.MULTILINE)

CommandRunner = Callable[[list[str]], str]
FailureChecker = Callable[[], list[str]]
Sleeper = Callable[[float], None]


def container_name(router: str, lab_name: str = LAB_NAME) -> str:
    """Return Containerlab's Docker container name for a router."""
    return f"clab-{lab_name}-{router}"


def full_neighbour_count(output: str) -> int:
    """Count OSPF neighbours whose state has reached Full."""
    return len(FULL_STATE_PATTERN.findall(output))


def next_hop_count(output: str) -> int:
    """Count unique IPv4 next hops in an FRR route display."""
    return len(set(NEXT_HOP_PATTERN.findall(output)))


def assess_router(router: str, runner: CommandRunner, lab_name: str = LAB_NAME) -> list[str]:
    """Return readiness failures for one router; empty means healthy."""
    if router not in EXPECTED_FULL_NEIGHBOURS:
        raise ValueError(f"unknown NetPulse router: {router}")

    router_container = container_name(router, lab_name)
    neighbours = runner(
        ["docker", "exec", router_container, "vtysh", "-c", "show ip ospf neighbor"]
    )
    expected_neighbours = EXPECTED_FULL_NEIGHBOURS[router]
    observed_neighbours = full_neighbour_count(neighbours)
    failures: list[str] = []

    if observed_neighbours != expected_neighbours:
        failures.append(
            f"{router}: expected {expected_neighbours} Full OSPF neighbours; "
            f"found {observed_neighbours}"
        )

    if router in ECMP_ROUTE:
        destination, expected_next_hops = ECMP_ROUTE[router]
        route = runner(
            [
                "docker",
                "exec",
                router_container,
                "vtysh",
                "-c",
                f"show ip route {destination}",
            ]
        )
        observed_next_hops = next_hop_count(route)
        if observed_next_hops < expected_next_hops:
            failures.append(
                f"{router}: expected at least {expected_next_hops} next hops to {destination}; "
                f"found {observed_next_hops}"
            )

    return failures


def run_command(command: Sequence[str], timeout: int) -> str:
    """Run a Docker/FRR query and return stdout, raising on command failure."""
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout


def topology_failures(runner: CommandRunner, lab_name: str) -> list[str]:
    """Return all current router readiness failures for one probe attempt."""
    failures: list[str] = []
    for router in EXPECTED_FULL_NEIGHBOURS:
        try:
            failures.extend(assess_router(router, runner, lab_name))
        except (subprocess.SubprocessError, OSError) as error:
            failures.append(f"{router}: health query failed: {error}")
    return failures


def wait_for_topology(
    checker: FailureChecker,
    *,
    attempts: int,
    retry_interval: float,
    sleeper: Sleeper = time.sleep,
) -> list[str]:
    """Probe boundedly while FRR elects OSPF roles and installs ECMP routes."""
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if retry_interval < 0:
        raise ValueError("retry_interval must be non-negative")
    failures: list[str] = []
    for attempt in range(attempts):
        failures = checker()
        if not failures:
            return []
        if attempt < attempts - 1:
            sleeper(retry_interval)
    return failures


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-name", default=LAB_NAME, help="Containerlab lab name")
    parser.add_argument("--timeout", type=int, default=15, help="per-command timeout in seconds")
    parser.add_argument(
        "--wait-seconds",
        type=float,
        default=50,
        help="maximum OSPF convergence wait after deployment",
    )
    parser.add_argument(
        "--retry-interval",
        type=float,
        default=5,
        help="seconds between readiness probes",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    def runner(command: list[str]) -> str:
        return run_command(command, args.timeout)

    if args.wait_seconds < 0 or args.retry_interval <= 0:
        raise SystemExit(
            "--wait-seconds must be non-negative and --retry-interval must be positive"
        )
    attempts = int(args.wait_seconds // args.retry_interval) + 1
    failures = wait_for_topology(
        lambda: topology_failures(runner, args.lab_name),
        attempts=attempts,
        retry_interval=args.retry_interval,
    )

    if failures:
        print("Topology health check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("Topology healthy: all OSPF adjacencies Full; r1 has two ECMP paths to h2.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
