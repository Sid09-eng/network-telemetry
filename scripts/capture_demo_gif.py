#!/usr/bin/env python3
"""Capture a terminal-style GIF from a verified local NetPulse stack.

The artifact deliberately displays direct command and API results rather than fabricated
telemetry. It never reads credentials and does not alter topology, traffic, or remediation state.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import textwrap
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1280
HEIGHT = 720
BACKGROUND = "#101418"
PANEL = "#182027"
TEXT = "#e5edf5"
MUTED = "#a8b5c2"
GREEN = "#66d18f"
CYAN = "#63d8f2"
PINK = "#f699c5"


def get_json(url: str, *, query: str | None = None) -> dict[str, Any]:
    """Fetch one unauthenticated local JSON endpoint."""
    if query:
        url = f"{url}?{urlencode({'query': query})}"
    with urlopen(url, timeout=10) as response:  # noqa: S310 - fixed loopback endpoints only
        return json.load(response)


def run_topology_check() -> str:
    """Return the repository's live OSPF/ECMP acceptance output."""
    result = subprocess.run(
        ["make", "topology-check"],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def throughput_lines(response: dict[str, Any]) -> list[str]:
    """Summarise returned recording-rule values without inventing measurements."""
    results = response["data"]["result"]
    if not results:
        return ["No non-zero transmit throughput was returned at capture time."]
    lines = []
    for result in results:
        metric = result["metric"]
        value = float(result["value"][1]) / 1_000_000
        lines.append(
            f"{metric['router']} {metric['interface']} ({metric['link']}): {value:.3f} Mbit/s"
        )
    return lines


def draw_frame(title: str, lines: list[str], *, accent: str, timestamp: str) -> Image.Image:
    """Render a readable, terminal-style evidence frame."""
    frame = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(frame)
    regular = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", 23)
    heading = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 34)
    small = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 18)

    draw.rounded_rectangle((38, 36, WIDTH - 38, HEIGHT - 38), radius=18, fill=PANEL)
    draw.text((76, 73), "NETPULSE  /  LIVE EVIDENCE", fill=CYAN, font=small)
    draw.text((76, 112), title, fill=TEXT, font=heading)
    draw.text((76, 164), timestamp, fill=MUTED, font=small)
    draw.rounded_rectangle((76, 212, WIDTH - 76, HEIGHT - 92), radius=12, fill=BACKGROUND)

    y = 246
    for line in lines:
        for wrapped in textwrap.wrap(line, width=82, break_long_words=False) or [""]:
            draw.text((105, y), wrapped, fill=accent, font=regular)
            y += 37
        y += 10
    draw.text(
        (76, HEIGHT - 72),
        "Source: direct local command/API output · synthetic lab · no remediation action applied",
        fill=MUTED,
        font=small,
    )
    return frame


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("docs/demo.gif"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    captured_at = datetime.now(UTC).strftime("Captured %Y-%m-%d %H:%M:%S UTC")
    topology = run_topology_check().splitlines()
    with urlopen("http://127.0.0.1:9090/-/ready", timeout=10) as response:
        prom_ready = response.read().decode().strip()
    grafana = get_json("http://127.0.0.1:3000/api/health")
    targets = get_json("http://127.0.0.1:9090/api/v1/query", query="count(up == 1)")
    throughput = get_json(
        "http://127.0.0.1:9090/api/v1/query",
        query="topk(4, router_interface:transmit_bits:rate1m)",
    )
    target_count = targets["data"]["result"][0]["value"][1]

    frames = [
        draw_frame(
            "NetPulse live demonstration",
            [
                "Synthetic FRR diamond · telemetry · anomaly detection · guarded remediation",
                "This GIF is generated after live health checks; values are captured, not mocked.",
            ],
            accent=CYAN,
            timestamp=captured_at,
        ),
        draw_frame("Topology acceptance", topology, accent=GREEN, timestamp=captured_at),
        draw_frame(
            "Prometheus scrape readiness",
            [prom_ready, f"Live query: count(up == 1) = {target_count}"],
            accent=GREEN,
            timestamp=captured_at,
        ),
        draw_frame(
            "Grafana service health",
            [
                f"database: {grafana['database']}",
                f"Grafana version: {grafana['version']}",
                "Dashboard: http://127.0.0.1:3000 (loopback only)",
            ],
            accent=GREEN,
            timestamp=captured_at,
        ),
        draw_frame(
            "Recorded router transmit throughput",
            throughput_lines(throughput),
            accent=CYAN,
            timestamp=captured_at,
        ),
        draw_frame(
            "Evidence boundary",
            [
                "The topology, Prometheus, and Grafana responses above came from the live local "
                "stack.",
                "Traffic is synthetic. Remediation remains dry-run and no router configuration "
                "changed.",
                "Immutable control/remediated experiment artifacts live under runs/task10-*.",
            ],
            accent=PINK,
            timestamp=captured_at,
        ),
    ]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(
        args.output,
        save_all=True,
        append_images=frames[1:],
        duration=[5_000] * len(frames),
        loop=0,
        disposal=2,
        optimize=True,
    )
    print(f"Wrote {args.output} from live evidence captured at {captured_at}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
