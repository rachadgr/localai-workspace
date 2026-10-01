"""Models & Providers API.

Exposes provider status, discovered models, capabilities, health, last error and
configuration — **without ever leaking API keys**. Includes a safe connection-test
endpoint that performs a real minimal request and returns structured diagnostics
with all secrets redacted.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from backend.app.core.security import redact
from backend.app.deps import get_current_user
from database.models import User
from models.registry import registry as model_registry
from models.router import TASK_REQUIREMENTS, ModelRouter

router = APIRouter()


# --------------------------------------------------------------------------- #
# Schemas
# --------------------------------------------------------------------------- #
class ConnectionTestRequest(BaseModel):
    provider: str = Field(default="", description="Provider name; empty = test every configured provider")
    model: str = Field(default="", description="Specific model id to probe; empty = first discovered")


# --------------------------------------------------------------------------- #
# Provider / model views (never include secrets)
# --------------------------------------------------------------------------- #
def _provider_view() -> dict[str, Any]:
    health = model_registry.health()
    return health["providers"]


@router.get("/models", tags=["models"])
def list_models(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Registry health: provider states, model list, capabilities and usability."""
    return model_registry.health()


@router.get("/models/providers", tags=["models"])
def list_providers(_: User = Depends(get_current_user)) -> dict[str, Any]:
    return {
        "providers": _provider_view(),
        "config_source": "environment",
        "secrets_exposed": False,
    }


@router.get("/models/router", tags=["models"])
def router_preview(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Deterministic routing decision for each task class (no execution)."""
    router_obj = ModelRouter(model_registry)
    out: dict[str, Any] = {}
    for task in TASK_REQUIREMENTS:
        out[task] = router_obj.select(task).to_dict()
    return {"tasks": out, "prefer_local": False}


@router.get("/models/{model_id:path}/health", tags=["models"])
def model_health(model_id: str, force: bool = False, _: User = Depends(get_current_user)) -> dict[str, Any]:
    report = model_registry.check_model_health(model_id, force=force)
    return {"model": model_id, **report.to_dict()}


@router.get("/models/{model_id:path}", tags=["models"])
def model_detail(model_id: str, _: User = Depends(get_current_user)) -> dict[str, Any]:
    info = model_registry.get(model_id)
    if info is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Model '{model_id}' not found")
    return info.to_dict()


# --------------------------------------------------------------------------- #
# Safe connection test
# --------------------------------------------------------------------------- #
@router.post("/models/test-connection", tags=["models"])
def test_connection(payload: ConnectionTestRequest, _: User = Depends(get_current_user)) -> dict[str, Any]:
    """Perform a real minimal request per provider and return redacted diagnostics.

    Never returns an API key, token or credential — only structured status,
    latency and a redacted error string.
    """
    adapters = model_registry.adapters()
    targets = {payload.provider: adapters[payload.provider]} if payload.provider and payload.provider in adapters else adapters
    if payload.provider and payload.provider not in adapters:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Unknown provider '{payload.provider}'")

    results: list[dict[str, Any]] = []
    for name, adapter in targets.items():
        if not adapter.is_configured():
            results.append(
                {
                    "provider": name,
                    "configured": False,
                    "status": "MISCONFIGURED",
                    "ok": False,
                    "model": payload.model,
                    "latency_ms": 0,
                    "error": "Provider is not configured",
                    "endpoint": adapter.endpoint_label(),
                    "local": getattr(adapter, "is_local", False),
                }
            )
            continue

        model = payload.model
        if not model:
            try:
                discovered = adapter.list_models()
                model = discovered[0] if discovered else ""
            except Exception:  # noqa: BLE001
                model = ""

        if not model:
            results.append(
                {
                    "provider": name,
                    "configured": True,
                    "status": "UNAVAILABLE",
                    "ok": False,
                    "model": "",
                    "latency_ms": 0,
                    "error": "No model available to probe",
                    "endpoint": adapter.endpoint_label(),
                    "local": getattr(adapter, "is_local", False),
                }
            )
            continue

        report = adapter.health_check(model)
        results.append(
            {
                "provider": name,
                "configured": True,
                "status": report.status,
                "ok": report.ok,
                "model": model,
                "latency_ms": report.latency_ms,
                "error": redact(report.error),
                "detail": redact(report.detail),
                "endpoint": adapter.endpoint_label(),
                "local": getattr(adapter, "is_local", False),
            }
        )

    return {
        "checked_at": __import__("time").time(),
        "results": results,
        "secrets_exposed": False,
    }
