"""Central ModelRegistry.

States: AVAILABLE, UNAVAILABLE, MISCONFIGURED, DISABLED.
Availability is *probed*, never assumed. If no chat provider is reachable the
registry reports ``UNAVAILABLE`` and the orchestrator degrades honestly.
"""

from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from backend.app.core.errors import ModelUnavailableError
from backend.app.core.observability import get_logger
from configs.settings import settings
from models.adapters import AnthropicAdapter, BaseChatAdapter, ChatMessage, Completion, EchoAdapter, OpenAICompatibleAdapter

logger = get_logger("model_registry")

STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_MISCONFIGURED = "MISCONFIGURED"
STATUS_DISABLED = "DISABLED"


@dataclass
class ModelInfo:
    id: str
    provider: str
    kind: str = "chat"
    status: str = STATUS_UNAVAILABLE
    capabilities: list[str] = field(default_factory=list)
    context_window: int = 0
    notes: str = ""


class ModelRegistry:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._adapters: dict[str, BaseChatAdapter] = {}
        self._models: dict[str, ModelInfo] = {}
        self._last_probe: float = 0.0
        self._probe_ttl = 60.0
        self._chat_ready: bool | None = None
        self._chat_probe_at: float = 0.0
        self._chat_probe_reason: str = ""
        self._build_adapters()

    # ------------------------------------------------------------ adapters
    def _build_adapters(self) -> None:
        primary = OpenAICompatibleAdapter(settings.llm_base_url, settings.llm_api_key, label="openai_compatible")
        self._adapters["openai_compatible"] = primary
        self._adapters["anthropic"] = AnthropicAdapter(settings.llm_anthropic_base_url, settings.llm_anthropic_api_key)
        self._adapters["echo"] = EchoAdapter()

    def register_adapter(self, name: str, adapter: BaseChatAdapter) -> None:
        with self._lock:
            self._adapters[name] = adapter
            self._last_probe = 0.0

    def get_adapter(self, model_id: str) -> BaseChatAdapter:
        info = self._models.get(model_id)
        if info and info.provider in self._adapters:
            return self._adapters[info.provider]
        if settings.llm_base_url and settings.llm_api_key:
            return self._adapters["openai_compatible"]
        echo = self._adapters.get("echo")
        if echo and echo.is_configured():
            return echo
        raise ModelUnavailableError("No chat model provider is available")

    # -------------------------------------------------------------- probe
    def refresh(self, force: bool = False) -> dict[str, ModelInfo]:
        with self._lock:
            if not force and (time.time() - self._last_probe) < self._probe_ttl and self._models:
                return dict(self._models)
            models: dict[str, ModelInfo] = {}

            primary = self._adapters["openai_compatible"]
            if not primary.is_configured():
                primary_status = STATUS_MISCONFIGURED
                primary_models: list[str] = []
            else:
                try:
                    primary_models = primary.list_models()
                    primary_status = STATUS_AVAILABLE if primary_models else STATUS_UNAVAILABLE
                except Exception as exc:
                    logger.warning("primary model probe failed: %s", exc)
                    primary_models = []
                    primary_status = STATUS_UNAVAILABLE

            for model_id in primary_models:
                models[model_id] = ModelInfo(
                    id=model_id,
                    provider="openai_compatible",
                    kind=_infer_kind(model_id),
                    status=primary_status,
                    capabilities=_infer_capabilities(model_id),
                    context_window=_infer_context(model_id),
                )

            anthropic = self._adapters["anthropic"]
            if anthropic.is_configured():
                for model_id in anthropic.list_models():
                    models.setdefault(
                        model_id,
                        ModelInfo(id=model_id, provider="anthropic", status=STATUS_AVAILABLE, capabilities=["chat", "reasoning"]),
                    )

            echo = self._adapters["echo"]
            if echo.is_configured():
                models["echo"] = ModelInfo(id="echo", provider="echo", status=STATUS_AVAILABLE, capabilities=["chat"], notes="deterministic test adapter")
            else:
                models["echo"] = ModelInfo(id="echo", provider="echo", status=STATUS_DISABLED, notes="enabled only via LAIW_ENABLE_ECHO_MODEL=true")

            self._models = models
            self._last_probe = time.time()
            self._persist(models)
            return dict(models)

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
                    row.kind = info.kind
                    row.status = info.status
                    row.context_window = info.context_window
                    row.capabilities = info.capabilities
                    row.notes = info.notes
        except Exception as exc:  # pragma: no cover
            logger.debug("model persist skipped: %s", exc)

    # ----------------------------------------------------------- querying
    def list_models(self) -> list[ModelInfo]:
        return sorted(self.refresh().values(), key=lambda m: (m.kind, m.id))

    def chat_models(self) -> list[ModelInfo]:
        return [m for m in self.list_models() if m.kind == "chat" and m.status == STATUS_AVAILABLE]

    def chat_available(self, force: bool = False) -> bool:
        """True only if a real completion round-trip succeeds.

        ``/models`` listing is not proof of usability (a proxy may list models
        while refusing completions for billing reasons), so we send one tiny
        probe request and cache the verdict briefly.
        """
        with self._lock:
            if not force and self._chat_ready is not None and (time.time() - self._chat_probe_at) < self._probe_ttl:
                return self._chat_ready

        candidate: BaseChatAdapter | None = None
        try:
            candidate = self.get_adapter(self.default_chat_model())
        except Exception:
            candidate = self._adapters.get("openai_compatible") if self._adapters["openai_compatible"].is_configured() else self._adapters.get("echo")

        ready = False
        reason = ""
        if candidate is not None and candidate.status() in (STATUS_AVAILABLE,):
            try:
                candidate.complete([ChatMessage("user", "ping")], model=self._probe_model_name(candidate), max_tokens=5)
                ready = True
            except Exception as exc:  # noqa: BLE001
                reason = str(exc)[:200]
        else:
            reason = "no configured chat adapter"

        with self._lock:
            self._chat_ready = ready
            self._chat_probe_at = time.time()
            self._chat_probe_reason = reason
        if not ready:
            logger.info("chat availability probe failed: %s", reason)
        return ready

    def _probe_model_name(self, adapter: BaseChatAdapter) -> str:
        try:
            return self.default_chat_model()
        except Exception:  # noqa: BLE001
            return "echo" if adapter.name == "echo" else "gpt-5-nano"

    def get(self, model_id: str) -> ModelInfo | None:
        return self.refresh().get(model_id)

    def default_chat_model(self) -> str:
        available = self.chat_models()
        ids = {m.id for m in available}
        if settings.llm_default_model in ids:
            return settings.llm_default_model
        if settings.llm_fast_model in ids:
            return settings.llm_fast_model
        for preferred in ("gpt-5.4-mini", "gpt-5-mini", "claude-sonnet-4-5"):
            if preferred in ids:
                return preferred
        if available:
            return available[0].id
        raise ModelUnavailableError("No chat model AVAILABLE")

    # ---------------------------------------------------------- execution
    def complete(self, messages: list[ChatMessage], model: str | None = None, **opts: Any) -> Completion:
        model = model or self.default_chat_model()
        adapter = self.get_adapter(model)
        if adapter.status() in (STATUS_DISABLED,):
            raise ModelUnavailableError(f"Model '{model}' is DISABLED")
        if adapter.status() == STATUS_MISCONFIGURED:
            raise ModelUnavailableError(f"Model provider for '{model}' is MISCONFIGURED")
        return adapter.complete(_as_messages(messages), model, **opts)

    def stream(self, messages: list[ChatMessage], model: str | None = None, **opts: Any):
        model = model or self.default_chat_model()
        adapter = self.get_adapter(model)
        return adapter.stream(_as_messages(messages), model, **opts)

    def health(self) -> dict[str, Any]:
        models = self.refresh()
        chat = [m for m in models.values() if m.kind == "chat"]
        listing = [m for m in chat if m.status == STATUS_AVAILABLE]
        ready = self.chat_available()
        return {
            "models_total": len(models),
            "chat_available": len(listing) if ready else 0,
            "chat_listed": len(listing),
            "chat_usable": ready,
            "unavailable_reason": self._chat_probe_reason,
            "providers": {name: adapter.status() for name, adapter in self._adapters.items()},
            "default_model": listing[0].id if listing else None,
            "status": STATUS_AVAILABLE if ready else STATUS_UNAVAILABLE,
            "models": [asdict(m) for m in sorted(models.values(), key=lambda x: x.id)],
        }


def _as_messages(messages: list[Any]) -> list[ChatMessage]:
    out: list[ChatMessage] = []
    for m in messages:
        if isinstance(m, ChatMessage):
            out.append(m)
        elif isinstance(m, dict):
            out.append(ChatMessage(role=m.get("role", "user"), content=m.get("content", "")))
    return out


def _infer_kind(model_id: str) -> str:
    lower = model_id.lower()
    if any(t in lower for t in ("embed", "embedding", "bge", "text-embedding")):
        return "embedding"
    if any(t in lower for t in ("dall", "image", "flux", "stable-diffusion", "imagen", "midjourney")):
        return "image"
    if any(t in lower for t in ("search", "rerank")):
        return "search"
    return "chat"


def _infer_capabilities(model_id: str) -> list[str]:
    lower = model_id.lower()
    caps = ["chat", "reasoning"]
    if "codex" in lower or "code" in lower:
        caps.append("code")
    if "vision" in lower or "-v" in lower or "gpt-5" in lower or "claude" in lower:
        caps.append("vision")
    if any(t in lower for t in ("gpt-5", "claude", "deep-seek", "luna", "sol", "astra")):
        caps.append("long-context")
    return caps


def _infer_context(model_id: str) -> int:
    lower = model_id.lower()
    if "1m" in lower:
        return 1_000_000
    if any(t in lower for t in ("gpt-5", "claude-opus", "claude-sonnet", "deep-seek")):
        return 200_000
    return 128_000


registry = ModelRegistry()

__all__ = ["ModelRegistry", "ModelInfo", "registry", "STATUS_AVAILABLE", "STATUS_UNAVAILABLE", "STATUS_MISCONFIGURED", "STATUS_DISABLED"]
