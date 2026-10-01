"""Local Model **Activation** — the bridge between the declarative Model Catalog and
the models that are *actually installed* on the local runtime.

Why a separate layer?
---------------------
``models/catalog.py`` declares what *could* exist. ``models/registry.py`` discovers
what a provider *exposes right now* and probes it. Neither answers the operational
question: *"of the models declared for my local runtime, which are physically
installed here, and which of those can I really use?"* This module answers exactly
that, and nothing more.

Scope & honesty rules (identical spirit to the catalog and the registry):

* **Local only.** Activation covers catalog entries served by a *local* provider
  (:data:`models.catalog.LOCAL_PROVIDERS`, i.e. Ollama). Cloud / hosted catalog
  ids are out of scope — they are not "installed" anywhere and never touched.
* **Nothing is ever downloaded.** Discovery only *lists* what the local runtime
  already holds; a catalog id that is not present in that list is reported
  ``NOT_INSTALLED`` and keeps the registry status ``NOT_CONFIGURED``. There is no
  pull / download path anywhere in this module.
* **No extra network I/O.** Activation reuses the registry's own cached discovery
  (:meth:`ModelRegistry.refresh`) and its cached probes
  (:meth:`ModelRegistry.check_model_health`). It adds no provider round-trips of
  its own, needs no API key and talks to no cloud endpoint.
* **``AVAILABLE`` only after a real probe.** An installed model is ``ACTIVE`` with
  runtime status ``AVAILABLE`` **only** when a real minimal request genuinely
  succeeds. A probe that fails (or a disabled prober) leaves the model at its
  honest non-available status.
* **The registry status always wins.** Activation reports the probed status; it
  never overrides it, and it never invents a capability. Capability metadata comes
  from the catalog, via the registry merge.

The layer is deliberately additive: it changes no existing behaviour, exposes no
new HTTP surface and is safe to disable (``LAIW_LOCAL_ACTIVATION_ENABLED=false``).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.core.observability import get_logger
from configs.settings import settings
from models.base import (
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
)
from models.catalog import LOCAL_PROVIDERS, catalog_entries, get_catalog_entry

logger = get_logger("local_model_activation")

# --------------------------------------------------------------------------- #
# Activation vocabulary (what the *local* layer says about a catalog entry)
# --------------------------------------------------------------------------- #
#: Installed on the local runtime **and** confirmed usable by a real probe. This is
#: the *only* activation whose runtime status is ``AVAILABLE``.
ACTIVATION_ACTIVE = "ACTIVE"
#: Installed on the local runtime, but the real probe did **not** succeed (or
#: probing is disabled) — discovered and present, yet not usable right now.
ACTIVATION_INSTALLED = "INSTALLED"
#: Declared for the local runtime but *not installed* on this host — nothing was
#: (or will be) downloaded, so it stays ``NOT_CONFIGURED``.
ACTIVATION_NOT_INSTALLED = "NOT_INSTALLED"
#: Local activation is switched off (``LAIW_LOCAL_ACTIVATION_ENABLED=false``), so no
#: install verdict is asserted and the registry status is reported as-is.
ACTIVATION_DISABLED = "DISABLED"
#: Not a local catalog entry — outside the local activation scope.
ACTIVATION_OUT_OF_SCOPE = "OUT_OF_SCOPE"

ALL_ACTIVATIONS = (
    ACTIVATION_ACTIVE,
    ACTIVATION_INSTALLED,
    ACTIVATION_NOT_INSTALLED,
    ACTIVATION_DISABLED,
    ACTIVATION_OUT_OF_SCOPE,
)


@dataclass
class LocalModelOutcome:
    """The activation verdict for one catalog entry.

    ``runtime_status`` is the **authoritative**, probed status (from the registry);
    ``activation`` is the local layer's verdict about *installation*. The two are
    kept separate on purpose: the catalog can never turn a not-installed model into
    an available one, and activation can never contradict a failed probe.
    """

    id: str
    provider: str
    kind: str
    installed: bool
    activation: str
    runtime_status: str
    probed: bool = False
    probe_ok: bool = False
    probe_status: str = ""
    probe_error: str = ""
    latency_ms: int = 0
    catalog: bool = True
    capabilities: list[str] = field(default_factory=list)
    modality: list[str] = field(default_factory=list)
    local: bool = True

    @property
    def available(self) -> bool:
        """Usable *right now*: installed + a genuinely successful real probe."""
        return self.activation == ACTIVATION_ACTIVE and self.runtime_status == STATUS_AVAILABLE

    @property
    def active(self) -> bool:
        """Alias of :attr:`available` — the model is installed and usable."""
        return self.available

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["available"] = self.available
        return data


# --------------------------------------------------------------------------- #
# Pure classification (no I/O — the testable core)
# --------------------------------------------------------------------------- #
def installed_local_ids(runtime_models: dict[str, Any]) -> set[str]:
    """Ids of models the local runtime currently exposes (i.e. is installed).

    A model counts as installed when the registry discovered it from a *local*
    provider. This is derived purely from the registry's own discovery — no extra
    request is made here.
    """
    installed: set[str] = set()
    for model_id, info in runtime_models.items():
        provider = str(getattr(info, "provider", "") or "").lower()
        if provider in LOCAL_PROVIDERS or bool(getattr(info, "local", False)):
            installed.add(model_id)
    return installed


def is_local_catalog_entry(model_id: str) -> bool:
    """True when ``model_id`` is declared for a local runtime in the catalog."""
    entry = get_catalog_entry(model_id)
    return entry is not None and (entry.local or entry.provider in LOCAL_PROVIDERS)


def _status_of(info: Any) -> str:
    return str(getattr(info, "status", STATUS_NOT_CONFIGURED) or STATUS_NOT_CONFIGURED)


def _probe_view(info: Any) -> dict[str, Any]:
    """Extract the registry's *real* probe result for ``info`` (if any)."""
    health = getattr(info, "health", None) or {}
    if not isinstance(health, dict) or not health:
        return {}
    return health


def classify_local_activation(
    runtime_models: dict[str, Any],
    *,
    enabled: bool = True,
    scope_ids: set[str] | None = None,
) -> dict[str, LocalModelOutcome]:
    """Pure classification of every local catalog entry (no network, no download).

    Parameters
    ----------
    runtime_models:
        ``{model_id: ModelInfo}`` as returned by ``ModelRegistry.refresh()`` — the
        already-discovered, already-probed runtime view.
    enabled:
        When ``False`` the whole layer is disabled: nothing is asserted about
        installation and each local entry is reported ``DISABLED`` with its real
        registry status.
    scope_ids:
        Restrict the report to these ids (used by the ``probe_all=False`` fast
        path). ``None`` reports every local catalog entry.

    Notes
    -----
    * Only *local* catalog entries are reported; cloud ids are ``OUT_OF_SCOPE``.
    * A local entry absent from ``runtime_models`` is ``NOT_INSTALLED`` and keeps
      the ``NOT_CONFIGURED`` status — **never** ``AVAILABLE``.
    """
    installed = installed_local_ids(runtime_models)
    outcomes: dict[str, LocalModelOutcome] = {}

    for entry in catalog_entries():
        is_local = entry.local or entry.provider in LOCAL_PROVIDERS
        if not is_local:
            continue  # local activation never touches cloud/hosted models
        if scope_ids is not None and entry.id not in scope_ids:
            continue

        info = runtime_models.get(entry.id)
        installed_here = entry.id in installed
        caps = list(getattr(info, "capabilities", None) or entry.capabilities) if info is not None else list(entry.capabilities)
        modality = list(getattr(info, "modality", None) or entry.modality) if info is not None else list(entry.modality)

        if not enabled:
            outcomes[entry.id] = LocalModelOutcome(
                id=entry.id,
                provider=entry.provider,
                kind=(getattr(info, "type", None) or entry.kind),
                installed=installed_here,
                activation=ACTIVATION_DISABLED,
                runtime_status=_status_of(info) if info is not None else STATUS_NOT_CONFIGURED,
                catalog=True,
                capabilities=caps,
                modality=modality,
                local=True,
            )
            continue

        if info is None or not installed_here:
            # Declared locally but not present on this host: NOT_CONFIGURED, and
            # explicitly NOT downloaded (no pull path exists in this module).
            outcomes[entry.id] = LocalModelOutcome(
                id=entry.id,
                provider=entry.provider,
                kind=entry.kind,
                installed=False,
                activation=ACTIVATION_NOT_INSTALLED,
                runtime_status=STATUS_NOT_CONFIGURED,
                probed=False,
                probe_ok=False,
                catalog=True,
                capabilities=caps,
                modality=modality,
                local=True,
            )
            continue

        probe = _probe_view(info)
        runtime_status = _status_of(info)
        probed = bool(probe)
        probe_ok = bool(probe.get("ok", False))
        # AVAILABLE only when the real probe succeeded (and the registry agrees).
        active = runtime_status == STATUS_AVAILABLE and probed and probe_ok
        outcomes[entry.id] = LocalModelOutcome(
            id=entry.id,
            provider=getattr(info, "provider", entry.provider),
            kind=(getattr(info, "type", None) or entry.kind),
            installed=True,
            activation=ACTIVATION_ACTIVE if active else ACTIVATION_INSTALLED,
            # Runtime status is the probed status — authoritative, never forged.
            runtime_status=runtime_status,
            probed=probed,
            probe_ok=probe_ok,
            probe_status=str(probe.get("status", "") or ""),
            probe_error=str(probe.get("error", "") or ""),
            latency_ms=int(probe.get("latency_ms", 0) or 0),
            catalog=bool(getattr(info, "catalog", True)),
            capabilities=caps,
            modality=modality,
            local=True,
        )
    return outcomes


# --------------------------------------------------------------------------- #
# The activation layer (I/O-minimal: reuses the registry's cache)
# --------------------------------------------------------------------------- #
class LocalModelActivation:
    """Runs Local Model Activation against a :class:`ModelRegistry`.

    The class performs no downloads and opens no new connection of its own: it
    reads the registry's cached discovery and, for installed models, relies on the
    registry's real probe (which is itself TTL-cached). Passing ``force=True``
    simply asks the registry to re-probe — still one tiny request per model, never
    a download.
    """

    def __init__(self, model_registry: Any) -> None:
        self.registry = model_registry

    # -------------------------------------------------------------- config
    @property
    def enabled(self) -> bool:
        return bool(getattr(settings, "local_activation_enabled", True))

    @property
    def probe_all(self) -> bool:
        return bool(getattr(settings, "local_activation_probe_all", True))

    @property
    def preferred_model(self) -> str:
        return str(getattr(settings, "local_activation_preferred_model", "") or "")

    def _scope_ids(self, runtime_models: dict[str, Any]) -> set[str] | None:
        """Ids to probe. ``None`` = every installed local model.

        With ``probe_all=False`` only the installed *preferred* model (falling back
        to the first installed local catalog model) is in scope, keeping activation
        fast on hosts with many local models — while every other installed local
        model is still *discovered* and reported, just not re-probed on each run.
        """
        if self.probe_all:
            return None
        installed = installed_local_ids(runtime_models)
        installed_catalog = [m for m in installed if is_local_catalog_entry(m)]
        if not installed_catalog:
            return set()
        preferred = self.preferred_model
        if preferred and preferred in installed_catalog:
            return {preferred}
        return {sorted(installed_catalog)[0]}

    # ------------------------------------------------------------ discovery
    def installed_model_ids(self, *, force: bool = False) -> set[str]:
        """Ids the local runtime actually has installed (no download)."""
        runtime = self.registry.refresh(force=force)
        return installed_local_ids(runtime)

    # --------------------------------------------------------------- probe
    def _ensure_probed(self, model_ids: list[str], *, force: bool) -> None:
        """Real probe for installed models, honouring the registry's own cache.

        This is the *only* place activation can cause provider traffic, and it goes
        exclusively through ``ModelRegistry.check_model_health`` — a single minimal
        request per model, cached by the registry TTL. No model weights are fetched.
        """
        for model_id in model_ids:
            try:
                self.registry.check_model_health(model_id, force=force)
            except Exception as exc:  # noqa: BLE001 - never let activation crash a caller
                logger.warning("local activation probe failed for %s: %s", model_id, exc)

    # ------------------------------------------------------------------ api
    def run(self, *, force: bool = False) -> dict[str, LocalModelOutcome]:
        """Discover installed local models, probe them, and classify each.

        Returns a mapping ``model_id -> LocalModelOutcome`` covering the local
        catalog entries (see :func:`classify_local_activation`). The registry's
        probed status is always authoritative.

        ``force=True`` re-probes **only the in-scope models** (one tiny request per
        model); it never forces a full provider re-discovery, so activation adds no
        broader traffic than the scope allows. No weights are ever fetched.
        """
        # Discovery is read from the registry cache (its own TTL governs refresh);
        # activation never forces a full re-discovery of every model.
        runtime = self.registry.refresh(force=False)

        if not self.enabled:
            return classify_local_activation(runtime, enabled=False)

        installed = installed_local_ids(runtime)
        scope = self._scope_ids(runtime)
        to_probe = sorted(
            model_id for model_id in installed if is_local_catalog_entry(model_id) and (scope is None or model_id in scope)
        )
        self._ensure_probed(to_probe, force=force)

        # Re-read the registry view: probes may have updated status/health.
        runtime = self.registry.refresh(force=False)
        return classify_local_activation(runtime, enabled=True, scope_ids=None)

    def summary(self, *, force: bool = False) -> dict[str, Any]:
        """Compact, JSON-safe activation report (never contains secrets)."""
        outcomes = self.run(force=force)
        models = [o.to_dict() for o in sorted(outcomes.values(), key=lambda o: o.id)]
        installed_models = [m for m in models if m["installed"]]
        active = [m for m in models if m["activation"] == ACTIVATION_ACTIVE]
        available = [m for m in active if m["runtime_status"] == STATUS_AVAILABLE]
        return {
            "enabled": self.enabled,
            "scope": "local",
            "preferred_model": self.preferred_model,
            "installed": sorted(m["id"] for m in installed_models),
            "installed_but_not_usable": sorted(
                m["id"] for m in models if m["activation"] == ACTIVATION_INSTALLED
            ),
            "active": sorted(m["id"] for m in active),
            "available": sorted(m["id"] for m in available),
            "not_installed": sorted(m["id"] for m in models if m["activation"] == ACTIVATION_NOT_INSTALLED),
            "total": len(models),
            "models": models,
            "secrets_exposed": False,
        }


# --------------------------------------------------------------------------- #
# Convenience helpers
# --------------------------------------------------------------------------- #
def available_local_models(model_registry: Any, *, force: bool = False) -> list[str]:
    """Ids of local catalog models that are installed *and* genuinely usable."""
    outcomes = LocalModelActivation(model_registry).run(force=force)
    return sorted(o.id for o in outcomes.values() if o.available)


def local_activation_summary(model_registry: Any, *, force: bool = False) -> dict[str, Any]:
    """Module-level shortcut for :meth:`LocalModelActivation.summary`."""
    return LocalModelActivation(model_registry).summary(force=force)


__all__ = [
    "ACTIVATION_ACTIVE",
    "ACTIVATION_INSTALLED",
    "ACTIVATION_NOT_INSTALLED",
    "ACTIVATION_DISABLED",
    "ACTIVATION_OUT_OF_SCOPE",
    "ALL_ACTIVATIONS",
    "LocalModelOutcome",
    "LocalModelActivation",
    "classify_local_activation",
    "installed_local_ids",
    "is_local_catalog_entry",
    "available_local_models",
    "local_activation_summary",
]
