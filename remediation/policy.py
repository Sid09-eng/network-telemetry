"""Strict Alertmanager payload validation and remediation cooldown policy."""

from __future__ import annotations

import math
from dataclasses import dataclass


class PolicyError(ValueError):
    """Raised when a webhook payload cannot safely select a remediation target."""


@dataclass(frozen=True)
class RemediationTarget:
    """One allow-listed FRR interface selected from a physical topology link."""

    link: str
    router: str
    interface: str
    fingerprint: str


# These are OSPF-enabled interfaces only. Host-facing links are intentionally absent.
LINK_TARGETS: dict[str, tuple[str, str]] = {
    "r1-r2": ("r1", "eth1"),
    "r1-r3": ("r1", "eth2"),
    "r2-r4": ("r2", "eth2"),
    "r3-r4": ("r3", "eth2"),
}
ALERT_NAME = "NetPulseLinkAnomaly"


def parse_alertmanager_payload(
    payload: object, *, include_resolved: bool = False
) -> list[RemediationTarget]:
    """Validate a firing Alertmanager webhook and map it to fixed safe targets."""
    if not isinstance(payload, dict):
        raise PolicyError("webhook payload must be an object")
    if not isinstance(payload.get("version"), str):
        raise PolicyError("webhook payload must include an Alertmanager version")
    if payload.get("status") not in {"firing", "resolved"}:
        raise PolicyError("webhook status must be firing or resolved")
    alerts = payload.get("alerts")
    if not isinstance(alerts, list) or not alerts:
        raise PolicyError("webhook payload must include at least one alert")

    targets: list[RemediationTarget] = []
    seen: set[tuple[str, str]] = set()
    for alert in alerts:
        if not isinstance(alert, dict) or alert.get("status") not in {"firing", "resolved"}:
            raise PolicyError("each alert must include a firing or resolved status")
        if alert["status"] == "resolved" and not include_resolved:
            continue
        labels = alert.get("labels")
        if not isinstance(labels, dict) or labels.get("alertname") != ALERT_NAME:
            raise PolicyError("alert is not a NetPulse link-anomaly alert")
        link = labels.get("link")
        if not isinstance(link, str) or link not in LINK_TARGETS:
            raise PolicyError("alert link is not an allow-listed OSPF target")
        router, interface = LINK_TARGETS[link]
        key = (router, interface)
        if key in seen:
            continue
        seen.add(key)
        fingerprint = alert.get("fingerprint")
        targets.append(
            RemediationTarget(
                link=link,
                router=router,
                interface=interface,
                fingerprint=str(fingerprint) if fingerprint is not None else f"{ALERT_NAME}:{link}",
            )
        )
    return targets


class CooldownPolicy:
    """Monotonic per-interface cooldown with no wall-clock dependency."""

    def __init__(self, *, cooldown_seconds: float) -> None:
        if not math.isfinite(cooldown_seconds) or cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be finite and non-negative")
        self.cooldown_seconds = cooldown_seconds
        self._last_applied: dict[tuple[str, str], float] = {}

    def allow(self, target: RemediationTarget, *, now: float) -> bool:
        """Reserve a target when outside the cooldown; otherwise reject it."""
        key = (target.router, target.interface)
        previous = self._last_applied.get(key)
        if previous is not None and now - previous < self.cooldown_seconds:
            return False
        self._last_applied[key] = now
        return True
