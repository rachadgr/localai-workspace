"""Model provisioning — the explicit **CATALOG → INSTALLED → AVAILABLE** separation.

The workspace has three declarative/runtime layers that must never be conflated:

* :mod:`models.catalog` — the **CATALOG**: what *could* exist (no runtime claim);
* :mod:`models.local` / :mod:`models.generation` — the **INSTALLED** reality: what is
  physically present on this host (with **no** download path);
* :mod:`models.registry` — the **AVAILABLE** reality: what a *real* probe confirmed
  usable right now.

This module composes those three into one honest, per-model view so an operator can
see, for every declared model, exactly which of the three layers it has reached and
— when it is not usable — *why*.

Honesty rules:

* ``available`` is **only** true when the registry probed the model ``AVAILABLE``;
* ``installed`` means physically present/discovered here — never a download;
* a model whose runtime is unsupported in this build is ``NOT_CONFIGURED`` with a
  clear ``reason`` (never a fake adapter);
* no network I/O, no weights, no secrets.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from models.base import (
    KIND_CHAT,
    KIND_EMBEDDING,
    KIND_IMAGE,
    KIND_VIDEO,
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
)
from models.catalog import LOCAL_PROVIDERS, catalog_entries, get_catalog_entry
from models.generation import (
    GEN_NOT_CONFIGURED,
    classify_generation,
    get_generation_registration,
    is_generation_model,
)
from models.local import canonical_installed_ids, classify_local_activation, installed_local_ids, resolve_runtime_info
from models.runtimes import is_local_runtime, runtime_status

# --------------------------------------------------------------------------- #
# Provisioning state vocabulary (the three layers + the honest "cannot" case)
# --------------------------------------------------------------------------- #
#: Declared in the catalog only — not present on this host.
PROV_CATALOG = "CATALOG"
#: Physically present/discovered here, but not confirmed usable right now.
PROV_INSTALLED = "INSTALLED"
#: Present **and** confirmed usable by a real probe / real sink.
PROV_AVAILABLE = "AVAILABLE"
#: Known to the catalog but its runtime is unsupported in this build (clear reason).
PROV_NOT_CONFIGURED = "NOT_CONFIGURED"

ALL_PROVISIONING_STATES = (PROV_CATALOG, PROV_INSTALLED, PROV_AVAILABLE, PROV_NOT_CONFIGURED)


@dataclass
class ProvisionedModel:
    """One catalog model's position across the CATALOG → INSTALLED → AVAILABLE layers."""

    id: str
    name: str
    provider: str
    kind: str
    runtime: str
    runtime_supported: bool = True
    runtime_reason: str = ""
    local: bool = False
    #: Declared in the static catalog (always true for rows produced here).
    catalog: bool = True
    #: Discovered/physically present on this host.
    discovered: bool = False
    installed: bool = False
    #: Confirmed usable by a real probe / real generation sink.
    available: bool = False
    state: str = PROV_CATALOG
    reason: str = ""
    capabilities: list[str] = field(default_factory=list)
    modality: list[str] = field(default_factory=list)
    status: str = STATUS_NOT_CONFIGURED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def catalog_entry_runtime(model_id: str) -> str:
    """Resolve the serving runtime id for a catalog model id.

    Generation models map to their registration's runtime (e.g. ``diffusers``);
    everything else maps to its catalog provider label (``ollama``, ``openai``…).
    """
    reg = get_generation_registration(model_id)
    if reg is not None:
        return reg.runtime
    entry = get_catalog_entry(model_id)
    if entry is not None:
        return entry.provider
    return ""


def _kind_of(model_id: str) -> str:
    entry = get_catalog_entry(model_id)
    if entry is not None:
        return entry.kind
    reg = get_generation_registration(model_id)
    if reg is not None:
        return reg.kind
    return KIND_CHAT


def classify_provisioning(
    registry: Any = None,
    *,
    runtime_models: dict[str, Any] | None = None,
    generation_runtime_models: dict[str, Any] | None = None,
    endpoint_models: dict[str, tuple[str, ...]] | None = None,
    provisioned_ids: set[str] | None = None,
    enabled: bool = True,
) -> dict[str, ProvisionedModel]:
    """Pure composition of the catalog, the install view and the probed status.

    Parameters
    ----------
    registry:
        A :class:`models.registry.ModelRegistry` (or any object exposing ``refresh()``
        and ``get()``). ``None`` yields a catalog-only view (everything is
        ``CATALOG``/``NOT_CONFIGURED`` — never ``AVAILABLE``).
    runtime_models:
        Discovered runtime models (defaults to ``registry.refresh()`` when available).
    generation_runtime_models:
        Descriptors for generation models a *supported* runtime reconciled.
    endpoint_models:
        Operator-configured HTTP generation endpoints per model id.
    provisioned_ids:
        Generation ids whose weights an operator confirmed *local* on a wired runtime.
        ``None`` (the pure default) asserts nothing — a wired-but-unprovisioned
        generation model stays ``NOT_CONFIGURED`` with a clear reason.
    enabled:
        When ``False`` no install verdict is asserted for local models.
    """
    models: dict[str, Any] = dict(runtime_models or {})
    if not models and registry is not None:
        try:
            models = dict(registry.refresh())
        except Exception:  # noqa: BLE001 - never crash a read-only view
            models = {}

    local_outcomes = classify_local_activation(models, enabled=enabled)
    installed_local = canonical_installed_ids(models)
    gen_outcomes = classify_generation(
        runtime_models=generation_runtime_models or {},
        endpoint_models=endpoint_models or {},
        provisioned_ids=provisioned_ids or set(),
    )

    out: dict[str, ProvisionedModel] = {}
    for entry in catalog_entries():
        runtime = catalog_entry_runtime(entry.id)
        supported, reason = runtime_status(runtime)
        is_local = entry.local or entry.provider in LOCAL_PROVIDERS or is_local_runtime(runtime)
        info = resolve_runtime_info(models, entry.id)

        discovered = info is not None
        installed = False
        available = False
        state = PROV_CATALOG
        state_reason = ""

        if is_generation_model(entry.id):
            gen = gen_outcomes.get(entry.id)
            runtime_supported = gen.runtime_supported if gen else supported
            runtime_reason = "" if runtime_supported else (reason or "")
            if gen is not None:
                installed = gen.installed
                available = gen.available
                state = _gen_state_to_prov(gen.state)
                state_reason = gen.reason
            else:
                state = PROV_NOT_CONFIGURED if not runtime_supported else PROV_CATALOG
                state_reason = runtime_reason
        else:
            runtime_supported = supported
            runtime_reason = reason if not supported else ""
            local_outcome = local_outcomes.get(entry.id)
            if is_local:
                # Local models: installed == discovered by the local runtime.
                installed = entry.id in installed_local
                if local_outcome is not None:
                    installed = installed or bool(local_outcome.installed)
            else:
                installed = discovered
            available = bool(info is not None and getattr(info, "status", "") == STATUS_AVAILABLE)
            if available:
                state = PROV_AVAILABLE
            elif installed:
                state = PROV_INSTALLED
            else:
                state = PROV_CATALOG
            state_reason = ""

        caps = list(getattr(info, "capabilities", None) or entry.capabilities)
        modality = list(getattr(info, "modality", None) or entry.modality)
        out[entry.id] = ProvisionedModel(
            id=entry.id,
            name=entry.name,
            provider=entry.provider,
            kind=entry.kind,
            runtime=runtime,
            runtime_supported=runtime_supported,
            runtime_reason=runtime_reason,
            local=is_local,
            catalog=True,
            discovered=discovered,
            installed=installed,
            available=available,
            state=state,
            reason=state_reason,
            capabilities=caps,
            modality=modality,
            status=getattr(info, "status", STATUS_NOT_CONFIGURED) if info is not None else STATUS_NOT_CONFIGURED,
        )
    return out


def _gen_state_to_prov(gen_state: str) -> str:
    if gen_state == GEN_NOT_CONFIGURED:
        return PROV_NOT_CONFIGURED
    if gen_state == "AVAILABLE":
        return PROV_AVAILABLE
    if gen_state == "INSTALLED":
        return PROV_INSTALLED
    return PROV_CATALOG


def provisioning_summary(
    registry: Any = None,
    *,
    runtime_models: dict[str, Any] | None = None,
    generation_runtime_models: dict[str, Any] | None = None,
    endpoint_models: dict[str, tuple[str, ...]] | None = None,
    provisioned_ids: set[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """JSON-safe provisioning report grouped by kind + state (never contains secrets)."""
    rows = classify_provisioning(
        registry,
        runtime_models=runtime_models,
        generation_runtime_models=generation_runtime_models,
        endpoint_models=endpoint_models,
        provisioned_ids=provisioned_ids,
        enabled=enabled,
    )
    models = [m.to_dict() for m in sorted(rows.values(), key=lambda m: (m.kind, m.id))]

    def ids(pred) -> list[str]:
        return sorted(m["id"] for m in models if pred(m))

    by_kind: dict[str, list[str]] = {k: [] for k in (KIND_CHAT, KIND_EMBEDDING, KIND_IMAGE, KIND_VIDEO)}
    for m in models:
        by_kind.setdefault(m["kind"], []).append(m["id"])
    for key in by_kind:
        by_kind[key] = sorted(by_kind[key])

    return {
        "layers": ["CATALOG", "INSTALLED", "AVAILABLE"],
        "states": list(ALL_PROVISIONING_STATES),
        "catalog": ids(lambda m: m["catalog"]),
        "installed": ids(lambda m: m["installed"]),
        "available": ids(lambda m: m["available"]),
        "catalog_only": ids(lambda m: m["state"] == PROV_CATALOG),
        "not_configured": ids(lambda m: m["state"] == PROV_NOT_CONFIGURED),
        "by_kind": by_kind,
        "total": len(models),
        "models": models,
        "config_source": "catalog+runtime",
        "secrets_exposed": False,
    }


__all__ = [
    "PROV_CATALOG",
    "PROV_INSTALLED",
    "PROV_AVAILABLE",
    "PROV_NOT_CONFIGURED",
    "ALL_PROVISIONING_STATES",
    "ProvisionedModel",
    "catalog_entry_runtime",
    "classify_provisioning",
    "provisioning_summary",
]
