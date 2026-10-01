"""Central ModelRegistry — an extensible, provider-agnostic model layer.

The registry is the single place the Super Agent asks for models. It never
hardcodes provider names: providers are *adapters* registered by name, each
implementing the unified :class:`models.base.ModelAdapter` interface.

States
------
``AVAILABLE`` / ``UNAVAILABLE`` / ``MISCONFIGURED`` / ``DISABLED`` / ``LOADING``
/ ``ERROR``.

Availability is **probed, never assumed**. Appearing in a provider's model list
is *not* proof of usability, so a model is only marked ``AVAILABLE`` after a real
minimal capability request succeeds. Verdicts are cached with a TTL so providers
are not hammered. If no provider is configured the registry reports
``UNAVAILABLE`` and the application keeps running (honest degradation).
"""

from __future__ import annotations

import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.core.errors import ModelUnavailableError
from backend.app.core.observability import get_logger
from configs.settings import settings
from models.base import (
    COST_TIER_UNKNOWN,
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
    ChatMessage,
    Completion,
    EmbeddingResult,
    HealthReport,
    ImageResult,
    ModelAdapter,
    ModelCapabilities,
    ModelDescriptor,
    infer_capabilities,
    infer_context,
    infer_kind,
    infer_modality,
)
from models.adapters import (
    AnthropicAdapter,
    EchoAdapter,
    OllamaAdapter,
    OpenAICompatibleAdapter,
)
from models.catalog import ModelCatalogEntry, catalog_entries, entry_runtime, entry_runtime_supported, get_catalog_entry

logger = get_logger("model_registry")

# Backwards-compatible re-exports (older code imports these from the registry).
__all__ = [
    "ModelRegistry",
    "ModelInfo",
    "registry",
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "STATUS_MISCONFIGURED",
    "STATUS_DISABLED",
    "STATUS_LOADING",
    "STATUS_ERROR",
    "STATUS_NOT_CONFIGURED",
]

_KNOWN_CHAT_PREFERENCE = (
    "gpt-5.4-mini",
    "gpt-5-mini",
    "gpt-5",
    "claude-sonnet-4-5",
    "qwen2.5",
    "llama3.1",
)


@dataclass
class ModelInfo:
    """Rich metadata for a single model (spec-required fields).

    ``catalog`` is ``True`` when the row originates from the static model
    catalog and ``False`` when it was produced purely by runtime discovery.
    The catalog *enriches* metadata but never overrides the probed ``status``.
    """

    id: str
    name: str = ""
    provider: str = ""
    type: str = KIND_CHAT  # chat | embedding | image | video | search
    kind: str = KIND_CHAT  # alias kept for older callers/tests
    capabilities: list[str] = field(default_factory=list)
    context_length: int = 0
    context_window: int = 0  # alias kept for older callers/tests
    vision: bool = False
    tools: bool = False
    streaming: bool = False
    local: bool = False
    endpoint: str = ""
    status: str = STATUS_UNAVAILABLE
    health: dict[str, Any] = field(default_factory=dict)
    last_checked: float = 0.0
    error: str = ""
    config_source: str = "environment"
    notes: str = ""
    #: Catalog enrichment (unified metadata vocabulary).
    family: str = ""
    modality: list[str] = field(default_factory=list)
    reasoning: bool = False
    cost_tier: str = COST_TIER_UNKNOWN
    catalog: bool = False
    #: Serving runtime id (see :mod:`models.runtimes`); ``runtime_supported`` is
    #: ``False`` when this build wires no adapter for that runtime, so the model is
    #: reported ``NOT_CONFIGURED`` downstream (clear reason, never a fake adapter).
    runtime: str = ""
    runtime_supported: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ModelRegistry:
    def __init__(self, *, build_adapters: bool = True) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, ModelAdapter] = {}
        self._models: dict[str, ModelInfo] = {}
        self._provider_status: dict[str, str] = {}
        self._provider_error: dict[str, str] = {}
        self._last_discovery: float = 0.0
        self._discovery_ttl = max(5.0, float(getattr(settings, "model_health_ttl_seconds", 120.0)))
        # Cached chat-usability verdict (real round-trip probe).
        self._chat_ready: bool | None = None
        self._chat_probe_at: float = 0.0
        self._chat_probe_reason: str = ""
        # Per-model health cache: model_id -> (HealthReport, timestamp)
        self._health_cache: dict[str, tuple[HealthReport, float]] = {}
        if build_adapters:
            self._build_adapters()

    # ------------------------------------------------------------ adapters
    def _build_adapters(self) -> None:
        """Instantiate every provider adapter from environment configuration."""
        self._adapters = {}

        # 1. Primary OpenAI-compatible endpoint (sandbox proxy / any OpenAI API).
        primary = OpenAICompatibleAdapter(settings.llm_base_url, settings.llm_api_key, label="openai_compatible")
        self._adapters["openai_compatible"] = primary

        # 2. Anthropic Messages API.
        self._adapters["anthropic"] = AnthropicAdapter(settings.llm_anthropic_base_url, settings.llm_anthropic_api_key)

        # 3. Local runtime: Ollama (native discovery) or a generic local OpenAI server.
        ollama_url = getattr(settings, "ollama_base_url", "") or ""
        if ollama_url:
            self._adapters["ollama"] = OllamaAdapter(ollama_url, getattr(settings, "ollama_api_key", ""))

        # 4. Optional extra named OpenAI-compatible providers (LAIW_PROVIDER_<NAME>_URL/_KEY).
        for name, (url, key) in _extra_provider_configs().items():
            self._adapters[name] = OpenAICompatibleAdapter(url, key, label=name)

        # 5. Deterministic test adapter (DISABLED unless explicitly enabled).
        self._adapters["echo"] = EchoAdapter()

        for name, adapter in self._adapters.items():
            self._provider_status[name] = adapter.status() if _safe_status(adapter) else STATUS_ERROR

    def register_adapter(self, name: str, adapter: ModelAdapter) -> None:
        """Register (or replace) a provider adapter at runtime."""
        with self._lock:
            self._adapters[name] = adapter
            self._last_discovery = 0.0
            self._chat_ready = None

    def adapters(self) -> dict[str, ModelAdapter]:
        with self._lock:
            return dict(self._adapters)

    def get_adapter(self, model_id: str) -> ModelAdapter:
        """Resolve the adapter for a model id (falls back sensibly)."""
        info = self._models.get(model_id)
        if info and info.provider in self._adapters:
            return self._adapters[info.provider]

        # No discovery yet / unknown id → prefer a configured chat provider.
        for name in ("openai_compatible", "anthropic", "ollama"):
            adapter = self._adapters.get(name)
            if adapter and adapter.is_configured() and _supports_chat(adapter):
                return adapter
        for adapter in self._adapters.values():
            if adapter.is_configured() and _supports_chat(adapter):
                return adapter
        echo = self._adapters.get("echo")
        if echo and echo.is_configured():
            return echo
        raise ModelUnavailableError("No model provider is available")

    # ----------------------------------------------------------- discovery
    def refresh(self, force: bool = False) -> dict[str, ModelInfo]:
        """Discover models across all providers, probing each for real usability."""
        with self._lock:
            if not force and (time.time() - self._last_discovery) < self._discovery_ttl and self._models:
                return dict(self._models)

            models: dict[str, ModelInfo] = {}
            provider_status: dict[str, str] = {}
            provider_error: dict[str, str] = {}

            for name, adapter in self._adapters.items():
                status, descriptors, error = self._discover_provider(name, adapter)
                provider_status[name] = status
                if error:
                    provider_error[name] = error

                for desc in descriptors:
                    # Do not mark a model AVAILABLE just because it was listed.
                    model_status = status
                    health: dict[str, Any] = {}
                    if status in (STATUS_AVAILABLE,):
                        report = self._probe_model(adapter, desc, force=force)
                        model_status = report.status
                        health = report.to_dict()
                        if not report.ok and report.error:
                            provider_error.setdefault(name, report.error)

                    models[desc.id] = self._build_model_info(
                        desc,
                        model_status=model_status,
                        health=health,
                        endpoint=desc.endpoint or self._endpoint_for(desc.provider),
                    )

            self._models = models
            self._provider_status = provider_status
            self._provider_error = provider_error
            self._last_discovery = time.time()
            self._persist(models)
            return dict(models)

    def _endpoint_for(self, provider: str) -> str:
        """Display-safe endpoint label for a provider (host only, never secrets)."""
        adapter = self._adapters.get(provider)
        if adapter is None:
            return ""
        try:
            return adapter.endpoint_label()
        except Exception:  # noqa: BLE001
            return ""

    def _build_model_info(
        self,
        desc: ModelDescriptor,
        *,
        model_status: str,
        health: dict[str, Any],
        endpoint: str,
    ) -> ModelInfo:
        """Build a :class:`ModelInfo` from a discovered descriptor.

        Catalog metadata (``family`` / ``reasoning`` / ``cost_tier`` / canonical
        ``name`` / ``notes``) is *merged in* when the id is known — it can enrich a
        discovered model but **never** overrides its probed ``status``.
        """
        caps = ModelCapabilities.from_list(desc.capabilities)
        info = ModelInfo(
            id=desc.id,
            name=desc.id,
            provider=desc.provider,
            type=desc.kind,
            kind=desc.kind,
            capabilities=list(desc.capabilities),
            context_length=desc.context_length,
            context_window=desc.context_length,
            vision=caps.vision,
            tools=caps.tools,
            streaming=caps.streaming,
            local=desc.local,
            endpoint=endpoint,
            status=model_status,
            health=health,
            last_checked=time.time(),
            error=health.get("error", ""),
            config_source="environment",
            modality=list(infer_modality(desc.kind, vision=caps.vision)),
            runtime=desc.provider,
        )
        entry = get_catalog_entry(desc.id)
        if entry is not None:
            self._apply_catalog_metadata(info, entry)
        else:
            # A discovered model unknown to the catalog: it was literally discovered
            # by a working adapter, so its runtime is supported by definition.
            info.runtime_supported = True
        return info

    @staticmethod
    def _apply_catalog_metadata(info: ModelInfo, entry: ModelCatalogEntry) -> None:
        """Copy declared catalog metadata onto ``info`` (status is left untouched).

        The catalog is the *declared* source of truth for descriptive metadata, so
        for a catalog-known model we adopt its declared capability vocabulary —
        ``capabilities``/``modality``/``reasoning``/``vision``/``tools`` — in place
        of the coarse id heuristic. This is what lets a declared multimodal /
        reasoning model route correctly once it is ``AVAILABLE`` (e.g. ``qwen3:4b``
        carries ``reasoning``, which the id heuristic cannot infer).

        The probed ``status`` (and ``health``/``endpoint``/``last_checked``) are
        runtime facts and are **never** touched here, so catalog metadata can never
        fabricate availability or contradict a failed probe.
        """
        info.catalog = True
        info.family = entry.family or info.family
        info.name = entry.name or info.name
        info.cost_tier = entry.cost_tier
        info.reasoning = entry.reasoning
        info.vision = entry.vision
        info.tools = entry.tools
        # Catalog capabilities replace the id-heuristic ones for a known model.
        info.capabilities = list(entry.capabilities)
        info.modality = list(entry.modality)
        info.runtime = entry_runtime(entry)
        info.runtime_supported = entry_runtime_supported(entry)
        if not info.notes:
            info.notes = entry.notes

    @staticmethod
    def _catalog_model_info(entry: ModelCatalogEntry, endpoint: str = "") -> ModelInfo:
        """A ``NOT_CONFIGURED`` placeholder for a known-but-undiscovered model."""
        return ModelInfo(
            id=entry.id,
            name=entry.name,
            provider=entry.provider,
            type=entry.kind,
            kind=entry.kind,
            capabilities=list(entry.capabilities),
            context_length=entry.context_window,
            context_window=entry.context_window,
            vision=entry.vision,
            tools=entry.tools,
            streaming=entry.streaming,
            local=entry.local,
            endpoint=endpoint,
            status=STATUS_NOT_CONFIGURED,
            health={},
            last_checked=0.0,
            error="",
            config_source="catalog",
            notes=entry.notes,
            family=entry.family,
            modality=list(entry.modality),
            reasoning=entry.reasoning,
            cost_tier=entry.cost_tier,
            catalog=True,
            runtime=entry_runtime(entry),
            runtime_supported=entry_runtime_supported(entry),
        )

    def _discover_provider(self, name: str, adapter: ModelAdapter) -> tuple[str, list[ModelDescriptor], str]:
        if not adapter.is_configured():
            status = STATUS_DISABLED if isinstance(adapter, EchoAdapter) else STATUS_MISCONFIGURED
            return status, [], "Provider is not configured"
        try:
            descriptors = adapter.discover()
        except Exception as exc:  # noqa: BLE001 - classified honestly
            logger.warning("provider %s discovery failed: %s", name, exc)
            from models.base import classify_probe_error

            return classify_probe_error(exc), [], str(exc)[:300]
        if not descriptors:
            return STATUS_UNAVAILABLE, [], "Provider returned no models"
        return STATUS_AVAILABLE, descriptors, ""

    def _probe_model(self, adapter: ModelAdapter, desc: ModelDescriptor, *, force: bool = False) -> HealthReport:
        """Real capability/health request, cached with the configured TTL."""
        if not getattr(settings, "model_probe_enabled", True):
            # Probing disabled → report LOADING (unknown) rather than falsely AVAILABLE.
            return HealthReport(status=STATUS_LOADING, ok=False, error="Model probing disabled")

        ttl = max(5.0, float(getattr(settings, "model_health_ttl_seconds", 120.0)))
        cached = self._health_cache.get(desc.id)
        if cached and not force and (time.time() - cached[1]) < ttl:
            return cached[0]

        report = self._run_probe(adapter, desc)
        self._health_cache[desc.id] = (report, time.time())
        return report

    @staticmethod
    def _run_probe(adapter: ModelAdapter, desc: ModelDescriptor) -> HealthReport:
        kind = desc.kind
        try:
            if kind == KIND_EMBEDDING:
                adapter.embed(["ping"], model=desc.id)
            elif kind == KIND_IMAGE:
                # Image providers are expensive; a listing + configured provider is
                # the strongest cheap signal we can assert without side effects.
                if not adapter.is_configured():
                    return HealthReport(status=STATUS_MISCONFIGURED, ok=False, error="Provider not configured")
                return HealthReport(status=STATUS_AVAILABLE, ok=True, detail="image provider configured")
            elif kind == KIND_VIDEO:
                if not adapter.is_configured():
                    return HealthReport(status=STATUS_MISCONFIGURED, ok=False, error="Provider not configured")
                return HealthReport(status=STATUS_AVAILABLE, ok=True, detail="video provider configured")
            else:
                adapter.complete([ChatMessage("user", "ping")], model=desc.id, max_tokens=5)
        except Exception as exc:  # noqa: BLE001
            from models.base import classify_probe_error

            return HealthReport(status=classify_probe_error(exc), ok=False, error=str(exc)[:300])
        return HealthReport(status=STATUS_AVAILABLE, ok=True)

    def check_model_health(self, model_id: str, force: bool = False) -> HealthReport:
        """Probe a single model on demand (cached)."""
        info = self.refresh().get(model_id)
        if info is None:
            return HealthReport(status=STATUS_UNAVAILABLE, ok=False, error=f"Unknown model '{model_id}'")
        adapter = self._adapters.get(info.provider)
        if adapter is None:
            return HealthReport(status=STATUS_UNAVAILABLE, ok=False, error=f"Unknown provider '{info.provider}'")
        desc = ModelDescriptor(
            id=info.id,
            provider=info.provider,
            kind=info.type,
            capabilities=info.capabilities,
            context_length=info.context_length,
            local=info.local,
            endpoint=info.endpoint,
        )
        report = self._probe_model(adapter, desc, force=force)
        if model_id in self._models:
            self._models[model_id].status = report.status
            self._models[model_id].health = report.to_dict()
            self._models[model_id].last_checked = report.checked_at
            self._models[model_id].error = report.error
        return report

    # ------------------------------------------------------------- persist
    @staticmethod
    def _persist(models: dict[str, ModelInfo]) -> None:
        try:
            from database.models import ModelRecord, session_scope

            with session_scope() as db:
                for info in models.values():
                    row = db.get(ModelRecord, info.id)
                    if row is None:
                        row = ModelRecord(id=info.id)
                        db.add(row)
                    row.provider = info.provider
                    row.kind = info.type
                    row.status = info.status
                    row.context_window = info.context_length
                    row.capabilities = info.capabilities
                    row.notes = info.error or info.notes
        except Exception as exc:  # pragma: no cover
            logger.debug("model persist skipped: %s", exc)

    # ----------------------------------------------------------- querying
    def list_models(self) -> list[ModelInfo]:
        return sorted(self.refresh().values(), key=lambda m: (m.type, m.id))

    def models_by_kind(self, kind: str, available_only: bool = True) -> list[ModelInfo]:
        out = [m for m in self.refresh().values() if m.type == kind]
        if available_only:
            out = [m for m in out if m.status == STATUS_AVAILABLE]
        return sorted(out, key=lambda m: m.id)

    def chat_models(self) -> list[ModelInfo]:
        return self.models_by_kind(KIND_CHAT, available_only=True)

    def embedding_models(self) -> list[ModelInfo]:
        return self.models_by_kind(KIND_EMBEDDING, available_only=True)

    def image_models(self) -> list[ModelInfo]:
        return self.models_by_kind(KIND_IMAGE, available_only=True)

    def video_models(self) -> list[ModelInfo]:
        return self.models_by_kind(KIND_VIDEO, available_only=True)

    def get(self, model_id: str) -> ModelInfo | None:
        return self.refresh().get(model_id)

    # ------------------------------------------------------------- catalog
    def catalog(self) -> list[ModelInfo]:
        """Declared catalog models merged with the **real** runtime state.

        For every catalog entry:

        * if the model was discovered at runtime, its probed ``status`` /
          ``health`` / ``endpoint`` are used (the catalog only enriches metadata);
        * otherwise the entry is reported as ``NOT_CONFIGURED`` — it is *known*
          but not installed/reachable, and is never falsely ``AVAILABLE``.

        The catalog is deliberately separate from runtime discovery: this method
        never triggers a probe, never downloads weights and never calls a cloud API.
        """
        runtime = self.refresh()
        merged: list[ModelInfo] = []
        for entry in catalog_entries():
            live = runtime.get(entry.id)
            if live is not None:
                merged.append(live)
                continue
            merged.append(self._catalog_model_info(entry, self._endpoint_for(entry.provider)))
        return merged

    def get_catalog_entry(self, model_id: str) -> ModelInfo | None:
        """Return the merged catalog view for a single model id."""
        return next((m for m in self.catalog() if m.id == model_id), None)

    # ------------------------------------------------- local model activation
    def local_activation(self, *, force: bool = False):
        """Return a :class:`models.local.LocalModelActivation` bound to this registry.

        Local Model Activation reports which *local* catalog models are actually
        installed and genuinely usable (installed + a real successful probe). It is
        additive, needs no API key / cloud provider, adds no provider round-trip of
        its own (it reuses this registry's cached discovery + probes) and **never**
        downloads weights.
        """
        from models.local import LocalModelActivation

        return LocalModelActivation(self)

    def local_activation_summary(self, *, force: bool = False) -> dict[str, Any]:
        """Compact local-activation report (installed / active / available ids)."""
        return self.local_activation().summary(force=force)

    # ---------------------------------------------------- generation / runtimes
    def generation_registrations(self) -> tuple[Any, ...]:
        """Declarative image/video/i2v registrations (no runtime claim, no download).

        Additive, offline: it returns the declarative registrations from
        :mod:`models.generation`. Availability is *not* asserted here — call
        :meth:`generation_summary` for the reconciled, honest state.
        """
        from models.generation import generation_registrations

        return generation_registrations()

    def generation_summary(
        self,
        *,
        runtime_models: dict[str, Any] | None = None,
        endpoint_models: dict[str, tuple[str, ...]] | None = None,
    ) -> dict[str, Any]:
        """Honest image/video/i2v state (supported runtime + a real sink ⇒ AVAILABLE).

        Additive and read-only: this build wires **no** diffusers adapter, so every
        registered generation model is reported ``NOT_CONFIGURED`` with a clear
        reason unless an operator has genuinely wired a runtime/endpoint. No weights
        are downloaded and no fake adapter is used.
        """
        from models.generation import generation_summary

        return generation_summary(runtime_models=runtime_models, endpoint_models=endpoint_models)

    def runtimes(self) -> dict[str, Any]:
        """The runtime matrix (which runtimes this build can actually serve)."""
        from models.runtimes import runtime_view

        return runtime_view()

    # --------------------------------------------------------- provisioning
    def provisioning_summary(
        self,
        *,
        runtime_models: dict[str, Any] | None = None,
        generation_runtime_models: dict[str, Any] | None = None,
        endpoint_models: dict[str, tuple[str, ...]] | None = None,
    ) -> dict[str, Any]:
        """Explicit **CATALOG → INSTALLED → AVAILABLE** view of every catalog model.

        Composes the static catalog, the local install view and the probed status
        into one honest per-model row (see :mod:`models.provisioning`). ``AVAILABLE``
        is only ever reported when the registry probed the model itself; a model
        whose runtime is unsupported here is ``NOT_CONFIGURED`` with a clear reason.
        Performs **no** new network I/O and never downloads weights.
        """
        from models.provisioning import provisioning_summary

        return provisioning_summary(
            self,
            runtime_models=runtime_models,
            generation_runtime_models=generation_runtime_models,
            endpoint_models=endpoint_models,
            enabled=bool(getattr(settings, "local_activation_enabled", True)),
        )

    def provisioned_model(self, model_id: str) -> dict[str, Any] | None:
        """Provisioning row for a single model id (``None`` when unknown)."""
        views = self.provisioning_summary()["models"]
        return next((m for m in views if m["id"] == model_id), None)

    # ------------------------------------------------------------- health
    def chat_available(self, force: bool = False) -> bool:
        """True only if a real completion round-trip succeeds.

        ``/models`` listing is not proof of usability (a proxy may list models
        while refusing completions for billing reasons), so we send one tiny
        probe request and cache the verdict briefly.
        """
        with self._lock:
            ttl = max(5.0, float(getattr(settings, "model_health_ttl_seconds", 120.0)))
            if not force and self._chat_ready is not None and (time.time() - self._chat_probe_at) < ttl:
                return self._chat_ready

        candidate: ModelAdapter | None = None
        model_name = ""
        try:
            model_name = self.default_chat_model()
            candidate = self.get_adapter(model_name)
        except Exception:
            for name in ("openai_compatible", "anthropic", "ollama"):
                adapter = self._adapters.get(name)
                if adapter and adapter.is_configured():
                    candidate = adapter
                    break
            if candidate is None:
                candidate = self._adapters.get("echo")

        ready = False
        reason = ""
        if candidate is not None and candidate.is_configured():
            probe_model = model_name or self._probe_model_name(candidate)
            report = candidate.health_check(probe_model)
            ready = report.ok
            reason = report.error
        else:
            reason = "no configured chat adapter"

        with self._lock:
            self._chat_ready = ready
            self._chat_probe_at = time.time()
            self._chat_probe_reason = reason
        if not ready:
            logger.info("chat availability probe failed: %s", reason)
        return ready

    def _probe_model_name(self, adapter: ModelAdapter) -> str:
        try:
            return self.default_chat_model()
        except Exception:  # noqa: BLE001
            if adapter.name == "echo":
                return "echo"
            try:
                listed = adapter.list_models()
            except Exception:  # noqa: BLE001 - provider unreachable; no name to probe
                return ""
            return listed[0] if listed else ""

    def default_chat_model(self) -> str:
        available = self.chat_models()
        ids = {m.id for m in available}
        if settings.llm_default_model in ids:
            return settings.llm_default_model
        if settings.llm_fast_model in ids:
            return settings.llm_fast_model
        for preferred in _KNOWN_CHAT_PREFERENCE:
            if preferred in ids:
                return preferred
        if available:
            return available[0].id
        raise ModelUnavailableError("No chat model AVAILABLE")

    # ---------------------------------------------------------- execution
    def complete(self, messages: list[Any], model: str | None = None, **opts: Any) -> Completion:
        model = model or self.default_chat_model()
        adapter = self.get_adapter(model)
        if adapter.status() == STATUS_DISABLED:
            raise ModelUnavailableError(f"Model '{model}' is DISABLED")
        if adapter.status() == STATUS_MISCONFIGURED:
            raise ModelUnavailableError(f"Model provider for '{model}' is MISCONFIGURED")
        return adapter.complete(_as_messages(messages), model, **opts)

    def stream(self, messages: list[Any], model: str | None = None, **opts: Any):
        model = model or self.default_chat_model()
        adapter = self.get_adapter(model)
        return adapter.stream(_as_messages(messages), model, **opts)

    def embed(self, texts: list[str], model: str | None = None, **opts: Any) -> EmbeddingResult:
        model = model or self._default_embedding_model()
        adapter = self.get_adapter(model)
        return adapter.embed(texts, model, **opts)

    def _default_embedding_model(self) -> str:
        models = self.embedding_models()
        if models:
            return models[0].id
        raise ModelUnavailableError("No embedding model AVAILABLE")

    # -------------------------------------------------------------- routing
    def router(self):
        """Return a :class:`models.router.ModelRouter` bound to this registry."""
        from models.router import ModelRouter

        return ModelRouter(self)

    def route(self, task: str, **kwargs: Any):
        """Task-based model selection (delegates to :class:`ModelRouter`)."""
        return self.router().select(task, **kwargs)

    def resolve_model(self, task: str, explicit: str = "", **kwargs: Any) -> str | None:
        """Resolve an explicit model if usable, else route by task requirement."""
        return self.router().resolve(task, explicit, **kwargs)

    # ------------------------------------------------------------- health
    def health(self) -> dict[str, Any]:
        models = self.refresh()
        chat = [m for m in models.values() if m.type == KIND_CHAT]
        listing = [m for m in chat if m.status == STATUS_AVAILABLE]
        ready = self.chat_available()
        providers = {}
        for name, adapter in self._adapters.items():
            providers[name] = {
                "status": self._provider_status.get(name, adapter.status()),
                "configured": adapter.is_configured(),
                "local": getattr(adapter, "is_local", False),
                "endpoint": adapter.endpoint_label(),
                "error": self._provider_error.get(name, ""),
            }
        return {
            "models_total": len(models),
            "chat_available": len(listing) if ready else 0,
            "chat_listed": len(listing),
            "chat_usable": ready,
            "unavailable_reason": self._chat_probe_reason,
            "providers": providers,
            "default_model": listing[0].id if listing else None,
            "status": STATUS_AVAILABLE if ready else STATUS_UNAVAILABLE,
            "models": [m.to_dict() for m in sorted(models.values(), key=lambda x: x.id)],
        }


def _as_messages(messages: list[Any]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            out.append(m)
        elif isinstance(m, dict):
            out.append(ChatMessage(role=m.get("role", "user"), content=m.get("content", "")))
    return out


def _supports_chat(adapter: ModelAdapter) -> bool:
    try:
        return "chat" in (adapter.capabilities("chat").to_list())
    except Exception:  # noqa: BLE001
        return True


def _safe_status(adapter: ModelAdapter) -> bool:
    try:
        adapter.status()
        return True
    except Exception:  # noqa: BLE001
        return False


_EXTRA_PROVIDER_RE = re.compile(r"^LAIW_PROVIDER_([A-Z0-9_]+)_(URL|KEY)$")


def _extra_provider_configs() -> dict[str, tuple[str, str]]:
    """Parse optional ``LAIW_PROVIDER_<NAME>_URL/_KEY`` environment pairs."""
    found: dict[str, dict[str, str]] = {}
    for key, value in os.environ.items():
        match = _EXTRA_PROVIDER_RE.match(key)
        if not match or not value:
            continue
        name, field_name = match.group(1), match.group(2)
        found.setdefault(name, {})[field_name] = value
    out: dict[str, tuple[str, str]] = {}
    for name, fields in found.items():
        if fields.get("URL"):
            out[name.lower()] = (fields["URL"], fields.get("KEY", ""))
    return out


registry = ModelRegistry()
