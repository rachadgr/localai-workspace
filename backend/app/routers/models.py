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
from models.base import (
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_ERROR,
    STATUS_LOADING,
    STATUS_MISCONFIGURED,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
)
from models.registry import registry as model_registry
from models.router import TASK_REQUIREMENTS, ModelRouter

router = APIRouter()

# --------------------------------------------------------------------------- #
# Model Catalog — declared metadata merged with the *real* runtime status.
# --------------------------------------------------------------------------- #
#: Canonical status vocabulary exposed by the catalog view. Every value is one of
#: the explicit provider/model states; ``NOT_CONFIGURED`` is a *known catalog*
#: model that is not wired up / not installed on this instance.
_CATALOG_STATUSES: tuple[str, ...] = (
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_MISCONFIGURED,
    STATUS_UNAVAILABLE,
    STATUS_DISABLED,
    STATUS_LOADING,
    STATUS_ERROR,
)

#: Coarse UI categories a client can filter by. Derived **only** from declared
#: catalog metadata (never from a status), so a category never implies usability.
_CATALOG_CATEGORIES: tuple[str, ...] = (
    "chat",
    "reasoning",
    "coding",
    "vision",
    "image",
    "video",
    "embedding",
)

#: Map a runtime *kind* to its coarse category (chat is further refined below).
_KIND_TO_CATEGORY: dict[str, str] = {
    KIND_CHAT: "chat",
    KIND_IMAGE: "image",
    KIND_VIDEO: "video",
    KIND_EMBEDDING: "embedding",
}


def _catalog_categories(info: Any) -> list[str]:
    """Coarse UI category labels for a merged catalog model.

    Purely descriptive: an image model is always in the ``image`` category, even
    when it is ``NOT_CONFIGURED``. A chat model additionally joins ``reasoning`` /
    ``coding`` / ``vision`` when the catalog declares those capabilities.
    """
    kind = getattr(info, "type", "") or getattr(info, "kind", "")
    caps = set(getattr(info, "capabilities", []) or [])
    modality = set(getattr(info, "modality", []) or [])
    out: list[str] = []
    base = _KIND_TO_CATEGORY.get(kind, "chat")
    out.append(base)
    if kind == KIND_CHAT:
        if getattr(info, "reasoning", False) or "reasoning" in caps:
            out.append("reasoning")
        if "code" in caps:
            out.append("coding")
        if getattr(info, "vision", False) or "vision" in caps or "image" in modality:
            out.append("vision")
    # Preserve the canonical category order and drop duplicates.
    return [c for c in _CATALOG_CATEGORIES if c in out]


def _catalog_entry_view(info: Any) -> dict[str, Any]:
    """One merged catalog row: declared metadata **plus** the probed runtime status.

    The runtime fields (``status``/``health``/``last_checked``/``error``) always
    come from the registry; the catalog only ever enriches the descriptive fields
    (``family``/``modality``/``reasoning``/``vision``/``tools``/``streaming``/
    ``local``/``cost_tier``/``context_window``). ``catalog`` records whether the id
    was declared in the static catalog, and ``runtime`` whether it was actually
    discovered on a live provider.
    """
    return {
        # identity
        "id": info.id,
        "name": getattr(info, "name", "") or info.id,
        "family": getattr(info, "family", "") or "",
        "provider": info.provider,
        # classification (declared metadata)
        "kind": getattr(info, "type", "") or getattr(info, "kind", ""),
        "modality": list(getattr(info, "modality", []) or []),
        "capabilities": list(getattr(info, "capabilities", []) or []),
        "category": _catalog_categories(info),
        # declared capability flags
        "context_window": getattr(info, "context_length", 0) or getattr(info, "context_window", 0) or 0,
        "reasoning": bool(getattr(info, "reasoning", False)),
        "vision": bool(getattr(info, "vision", False)),
        "tools": bool(getattr(info, "tools", False)),
        "streaming": bool(getattr(info, "streaming", False)),
        "local": bool(getattr(info, "local", False)),
        "cost_tier": getattr(info, "cost_tier", "") or "unknown",
        # runtime status — NEVER replaced by catalog metadata
        "status": info.status,
        "available": info.status == STATUS_AVAILABLE,
        "runtime": bool(getattr(info, "catalog", False)) and info.status != STATUS_NOT_CONFIGURED,
        "catalog": bool(getattr(info, "catalog", False)),
        "config_source": getattr(info, "config_source", ""),
        "endpoint": getattr(info, "endpoint", ""),
        "last_checked": getattr(info, "last_checked", 0.0) or 0.0,
        "error": redact(getattr(info, "error", "") or ""),
        "notes": getattr(info, "notes", "") or "",
    }


@router.get("/models/catalog", tags=["models"])
def list_model_catalog(_: User = Depends(get_current_user)) -> dict[str, Any]:
    """Declarative **Model Catalog** merged with the real runtime status.

    Additive endpoint: it enriches the existing ``/api/models`` surface with the
    declared multi-modal metadata (``provider``/``family``/``modality``/
    ``capabilities``/``context_window``/``reasoning``/``vision``/``tools``/
    ``streaming``/``local``/``cost_tier``) while keeping the probed ``status``
    authoritative.

    Honesty rules:

    * ``AVAILABLE`` is only ever reported when the runtime registry confirmed it
      with a real probe — the catalog **never** overrides or fabricates a status;
    * a declared-but-not-discovered model is ``NOT_CONFIGURED`` (never
      ``AVAILABLE``);
    * no credentials, tokens or endpoint secrets are ever returned
      (``secrets_exposed: false``).

    This endpoint performs **no** new network I/O: it reuses the registry's cached
    discovery and never downloads weights.
    """
    models = model_registry.catalog()
    entries = [_catalog_entry_view(m) for m in models]
    # Stable, human-friendly ordering: category → provider → id.
    entries.sort(key=lambda e: (e["kind"], e["provider"], e["id"]))

    providers = sorted({e["provider"] for e in entries if e["provider"]})
    counts = {status: 0 for status in _CATALOG_STATUSES}
    for entry in entries:
        if entry["status"] in counts:
            counts[entry["status"]] += 1

    runtime_confirmed = sum(1 for e in entries if e["available"])

    return {
        "total": len(entries),
        "available": runtime_confirmed,
        "providers": providers,
        "categories": list(_CATALOG_CATEGORIES),
        "statuses": list(_CATALOG_STATUSES),
        "counts": counts,
        "models": entries,
        "config_source": "catalog+runtime",
        "secrets_exposed": False,
    }


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
    """Deterministic routing decision for each task class (no execution).

    Each entry now carries an explicit ``outcome``
    (``SELECTED`` / ``NO_CAPABLE_MODEL`` / ``REGISTRY_UNAVAILABLE``) plus the hard
    ``required`` capabilities and ``modalities`` the router enforced, so a client
    can tell a real pick apart from an honest "no capable model" verdict.
    """
    router_obj = ModelRouter(model_registry)
    out: dict[str, Any] = {}
    for task in TASK_REQUIREMENTS:
        out[task] = router_obj.select(task).to_dict()
    return {"tasks": out, "prefer_local": False, "capability_gated": True}


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
