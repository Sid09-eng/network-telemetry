#!/usr/bin/env python3
"""Expose selected Linux interface counters in Prometheus text format."""

from __future__ import annotations

import argparse
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SYSFS_NET_ROOT = Path("/sys/class/net")
COUNTERS = (
    ("rx_bytes", "netpulse_interface_receive_bytes_total", "counter"),
    ("tx_bytes", "netpulse_interface_transmit_bytes_total", "counter"),
    ("rx_packets", "netpulse_interface_receive_packets_total", "counter"),
    ("tx_packets", "netpulse_interface_transmit_packets_total", "counter"),
    ("rx_errors", "netpulse_interface_receive_errors_total", "counter"),
    ("tx_errors", "netpulse_interface_transmit_errors_total", "counter"),
    ("rx_dropped", "netpulse_interface_receive_drops_total", "counter"),
    ("tx_dropped", "netpulse_interface_transmit_drops_total", "counter"),
)
CAPACITY_METRIC = "netpulse_interface_capacity_bits_per_second"
READABLE_METRIC = "netpulse_interface_readable"
INTERFACE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")

CounterReader = Callable[[Path], int]


@dataclass(frozen=True)
class MetricSample:
    """One metric sample with fixed router-interface labels."""

    name: str
    kind: str
    router: str
    interface: str
    link: str
    value: int


def parse_interface_links(value: str) -> dict[str, str]:
    """Parse `eth1:r1-r2,eth2:r1-r3` environment syntax safely."""
    mappings: dict[str, str] = {}
    for item in filter(None, (part.strip() for part in value.split(","))):
        interface, separator, link = item.partition(":")
        if (
            not separator
            or not INTERFACE_PATTERN.fullmatch(interface)
            or not INTERFACE_PATTERN.fullmatch(link)
        ):
            raise ValueError(f"invalid interface mapping: {item!r}")
        if interface in mappings:
            raise ValueError(f"duplicate interface mapping: {interface}")
        mappings[interface] = link
    if not mappings:
        raise ValueError("at least one interface mapping is required")
    return mappings


def read_counter(path: Path) -> int:
    """Read one Linux interface statistic."""
    return int(path.read_text(encoding="utf-8").strip())


def collect_interface_metrics(
    *,
    router: str,
    interface_links: Mapping[str, str],
    capacity_bps: int,
    reader: CounterReader = read_counter,
    sysfs_root: Path = SYSFS_NET_ROOT,
) -> tuple[list[MetricSample], list[tuple[str, str, str]]]:
    """Collect all counters per configured interface without exposing partial data."""
    samples: list[MetricSample] = []
    unreadable: list[tuple[str, str, str]] = []
    for interface, link in interface_links.items():
        try:
            values = {
                counter: reader(sysfs_root / interface / "statistics" / counter)
                for counter, _, _ in COUNTERS
            }
        except (OSError, ValueError):
            unreadable.append((router, interface, link))
            continue

        for counter, metric_name, kind in COUNTERS:
            samples.append(
                MetricSample(metric_name, kind, router, interface, link, values[counter])
            )
        samples.append(
            MetricSample(CAPACITY_METRIC, "gauge", router, interface, link, capacity_bps)
        )
    return samples, unreadable


def _labels(router: str, interface: str, link: str) -> str:
    return f'router="{router}",interface="{interface}",link="{link}"'


def render_metrics(samples: list[MetricSample], unreadable: list[tuple[str, str, str]]) -> str:
    """Render Prometheus 0.0.4 text exposition."""
    metric_kinds = {name: kind for _, name, kind in COUNTERS}
    metric_kinds[CAPACITY_METRIC] = "gauge"
    metric_kinds[READABLE_METRIC] = "gauge"
    lines: list[str] = []
    for name, kind in metric_kinds.items():
        lines.append(f"# TYPE {name} {kind}")
    for sample in samples:
        lines.append(
            f"{sample.name}{{{_labels(sample.router, sample.interface, sample.link)}}} "
            f"{sample.value}"
        )
    for sample in samples:
        if sample.name == CAPACITY_METRIC:
            lines.append(
                f"{READABLE_METRIC}{{{_labels(sample.router, sample.interface, sample.link)}}} 1"
            )
    for router, interface, link in unreadable:
        lines.append(f"{READABLE_METRIC}{{{_labels(router, interface, link)}}} 0")
    return "\n".join(lines) + "\n"


class MetricsHandler(BaseHTTPRequestHandler):
    """Serve metrics from router namespace sysfs."""

    router = ""
    interface_links: Mapping[str, str] = {}
    capacity_bps = 0

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return
        if self.path != "/metrics":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        samples, unreadable = collect_interface_metrics(
            router=self.router,
            interface_links=self.interface_links,
            capacity_bps=self.capacity_bps,
        )
        body = render_metrics(samples, unreadable).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        """Keep scrape requests out of stdout; Docker retains application errors."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9100)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    router = os.environ.get("NETPULSE_ROUTER", "").strip()
    if not INTERFACE_PATTERN.fullmatch(router):
        raise SystemExit("NETPULSE_ROUTER must be a non-empty router name")
    try:
        interface_links = parse_interface_links(os.environ.get("NETPULSE_INTERFACE_LINKS", ""))
        capacity_bps = int(os.environ.get("NETPULSE_LINK_CAPACITY_BPS", "100000000"))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    if capacity_bps <= 0:
        raise SystemExit("NETPULSE_LINK_CAPACITY_BPS must be positive")

    handler = type(
        "NetPulseMetricsHandler",
        (MetricsHandler,),
        {
            "router": router,
            "interface_links": interface_links,
            "capacity_bps": capacity_bps,
        },
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Serving router-interface metrics for {router} on {args.host}:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
