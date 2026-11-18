"""FastAPI webhook boundary for guarded NetPulse remediation."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Response

from .actions import OspfCostAdapter
from .policy import PolicyError
from .service import RemediationService


def _bool_env(name: str, default: bool) -> bool:
    value = os.environ.get(name, str(default)).strip().lower()
    if value in {"1", "true", "yes"}:
        return True
    if value in {"0", "false", "no"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class RemediationConfig:
    """Configuration with live execution behind two explicit safety switches."""

    dry_run: bool
    live_actions_enabled: bool
    cooldown_seconds: float
    global_cooldown_seconds: float
    cost: int
    command_timeout_seconds: float
    audit_path: Path

    @classmethod
    def from_env(cls) -> RemediationConfig:
        dry_run = _bool_env("NETPULSE_DRY_RUN", True)
        live_actions_enabled = _bool_env("NETPULSE_ENABLE_LIVE_ACTIONS", False)
        if not dry_run and not live_actions_enabled:
            raise ValueError(
                "live remediation requires NETPULSE_DRY_RUN=false and "
                "NETPULSE_ENABLE_LIVE_ACTIONS=true"
            )
        config = cls(
            dry_run=dry_run,
            live_actions_enabled=live_actions_enabled,
            cooldown_seconds=float(os.environ.get("NETPULSE_REMEDIATION_COOLDOWN_SECONDS", "300")),
            global_cooldown_seconds=float(
                os.environ.get("NETPULSE_REMEDIATION_GLOBAL_COOLDOWN_SECONDS", "300")
            ),
            cost=int(os.environ.get("NETPULSE_REMEDIATION_COST", "100")),
            command_timeout_seconds=float(
                os.environ.get("NETPULSE_REMEDIATION_COMMAND_TIMEOUT_SECONDS", "10")
            ),
            audit_path=Path(os.environ.get("NETPULSE_REMEDIATION_AUDIT_PATH", "/data/audit.jsonl")),
        )
        if not math.isfinite(config.cooldown_seconds) or config.cooldown_seconds < 0:
            raise ValueError(
                "NETPULSE_REMEDIATION_COOLDOWN_SECONDS must be finite and non-negative"
            )
        if not math.isfinite(config.global_cooldown_seconds) or config.global_cooldown_seconds < 0:
            raise ValueError(
                "NETPULSE_REMEDIATION_GLOBAL_COOLDOWN_SECONDS must be finite and non-negative"
            )
        if not math.isfinite(config.command_timeout_seconds) or config.command_timeout_seconds <= 0:
            raise ValueError(
                "NETPULSE_REMEDIATION_COMMAND_TIMEOUT_SECONDS must be finite and positive"
            )
        return config


def create_app(service: RemediationService | None = None) -> FastAPI:
    """Create a webhook app, optionally with a test-provided service instance."""
    if service is None:
        config = RemediationConfig.from_env()
        service = RemediationService(
            adapter=OspfCostAdapter(
                dry_run=config.dry_run,
                cost=config.cost,
                timeout_seconds=config.command_timeout_seconds,
            ),
            cooldown_seconds=config.cooldown_seconds,
            global_cooldown_seconds=config.global_cooldown_seconds,
            audit_path=config.audit_path,
        )

    app = FastAPI(title="NetPulse remediation", docs_url=None, redoc_url=None)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "mode": service.mode}

    @app.get("/metrics")
    async def metrics() -> Response:
        return Response(service.metrics(), media_type="text/plain; version=0.0.4")

    @app.post("/alerts", status_code=202)
    async def alerts(payload: Any = Body(...)) -> dict[str, object]:
        try:
            # Decisions are intentionally serialized by RemediationService; keeping this
            # boundary async also works with the pinned ASGI test transport.
            decisions = service.handle(payload)
        except PolicyError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"status": "accepted", "mode": service.mode, "decisions": decisions}

    return app


app = create_app()
