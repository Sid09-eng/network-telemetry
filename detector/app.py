"""Expose residual anomaly state for Prometheus and Alertmanager wiring."""

from __future__ import annotations

import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LINK_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass
class DetectorState:
    """Thread-safe last anomaly state; scoring models update this via the local API."""

    threshold: float
    score: float = 0.0
    active: bool = False
    link: str = "unknown"
    scores: dict[str, float] = field(default_factory=dict)
    residuals: dict[str, float] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        if not math.isfinite(self.threshold) or self.threshold < 0:
            raise ValueError("threshold must be non-negative and finite")

    def update(self, *, link: str, score: float, residual: float = 0.0) -> None:
        if (
            not LINK_PATTERN.fullmatch(link)
            or not math.isfinite(score)
            or score < 0
            or not math.isfinite(residual)
        ):
            raise ValueError("link, score, and residual must be valid")
        with self.lock:
            self.link = link
            self.score = score
            self.active = score >= self.threshold
            self.scores[link] = score
            self.residuals[link] = residual

    def set_threshold(self, threshold: float) -> None:
        """Update the validation-selected residual threshold for future scoring."""
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("threshold must be non-negative and finite")
        with self.lock:
            self.threshold = threshold
            self.active = self.score >= threshold

    def metrics(self) -> bytes:
        with self.lock:
            states = self.scores or {self.link: self.score}
            body = "# TYPE netpulse_anomaly_score gauge\n"
            body += "# TYPE netpulse_anomaly_residual gauge\n"
            body += "# TYPE netpulse_anomaly_threshold gauge\n"
            body += "# TYPE netpulse_anomaly_active gauge\n"
            for link, score in sorted(states.items()):
                label = f'link="{link}"'
                body += f"netpulse_anomaly_score{{{label}}} {score}\n"
                body += f"netpulse_anomaly_residual{{{label}}} {self.residuals.get(link, 0.0)}\n"
                body += f"netpulse_anomaly_threshold{{{label}}} {self.threshold}\n"
                body += f"netpulse_anomaly_active{{{label}}} {int(score >= self.threshold)}\n"
        return body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    state = DetectorState(threshold=float(os.environ.get("NETPULSE_ANOMALY_THRESHOLD", "0.1")))

    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/healthz":
            self.send_response(HTTPStatus.OK)
            self.end_headers()
            return
        if self.path == "/metrics":
            body = self.state.metrics()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/plain; version=0.0.4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path not in {"/score", "/threshold"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            if self.path == "/threshold":
                threshold = float(payload["threshold"])
                self.state.set_threshold(threshold)
                self._send_json({"threshold": threshold})
                return
            link = str(payload["link"])
            score = (
                float(payload["score"])
                if "score" in payload
                else abs(float(payload["actual"]) - float(payload["predicted"]))
            )
            residual = (
                float(payload["residual"])
                if "residual" in payload
                else float(payload.get("actual", 0.0)) - float(payload.get("predicted", 0.0))
            )
            self.state.update(link=link, score=score, residual=residual)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            self.send_error(
                HTTPStatus.BAD_REQUEST,
                "expected threshold or link plus score or actual/predicted",
            )
            return

        self._send_json(
            {
                "link": link,
                "score": score,
                "residual": residual,
                "active": score >= self.state.threshold,
            }
        )

    def _send_json(self, payload: dict[str, float | str | bool]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8001), Handler).serve_forever()
