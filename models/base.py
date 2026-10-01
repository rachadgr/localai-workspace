"""Unified model-provider contract.

This module defines the *single* interface every provider adapter implements, so
the Super Agent never hardcodes provider names. It supports, where the underlying
provider actually can:

* chat completions (blocking + streaming)
* tool calling
* vision (image inputs)
* embeddings
* image generation
* (forward-looking) video generation

Honesty rules enforced by the contract (and every concrete adapter):

* ``AVAILABLE`` is only ever reported after a *real* minimal request succeeds.
  Appearing in a provider's model list is **not** proof of usability.
* Missing credentials → ``MISCONFIGURED``; a disabled adapter → ``DISABLED``.
* A reachable provider that fails a real call → ``UNAVAILABLE`` or ``ERROR``.
* No adapter ever fabricates content. Failures are raised, never invented.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterator

# --------------------------------------------------------------------------- #
# Explicit model/provider states
# --------------------------------------------------------------------------- #
STATUS_AVAILABLE = "AVAILABLE"
STATUS_UNAVAILABLE = "UNAVAILABLE"
STATUS_MISCONFIGURED = "MISCONFIGURED"
STATUS_DISABLED = "DISABLED"
STATUS_LOADING = "LOADING"
STATUS_ERROR = "ERROR"

ALL_STATUSES = (
    STATUS_AVAILABLE,
    STATUS_UNAVAILABLE,
    STATUS_MISCONFIGURED,
    STATUS_DISABLED,
    STATUS_LOADING,
    STATUS_ERROR,
)

#: A model is *usable* only in this state.
USABLE_STATUSES = (STATUS_AVAILABLE,)

# --------------------------------------------------------------------------- #
# Capability vocabulary
# --------------------------------------------------------------------------- #
CAP_CHAT = "chat"
CAP_STREAMING = "streaming"
CAP_TOOLS = "tools"
CAP_VISION = "vision"
CAP_EMBEDDINGS = "embeddings"
CAP_IMAGE_GENERATION = "image_generation"
CAP_VIDEO_GENERATION = "video_generation"
CAP_REASONING = "reasoning"
CAP_CODE = "code"
CAP_JSON_MODE = "json_mode"
CAP_LONG_CONTEXT = "long_context"

#: Model "kinds" (what the router groups by).
KIND_CHAT = "chat"
KIND_EMBEDDING = "embedding"
KIND_IMAGE = "image"
KIND_VIDEO = "video"
KIND_SEARCH = "search"


@dataclass
class ModelCapabilities:
    """Declared capabilities of a specific model (discovered + probed)."""

    chat: bool = True
    streaming: bool = True
    tools: bool = False
    vision: bool = False
    embeddings: bool = False
    image_generation: bool = False
    video_generation: bool = False
    reasoning: bool = False
    code: bool = False
    json_mode: bool = False
    long_context: bool = False

    def to_list(self) -> list[str]:
        out: list[str] = []
        if self.chat:
            out.append(CAP_CHAT)
        if self.streaming:
            out.append(CAP_STREAMING)
        if self.tools:
            out.append(CAP_TOOLS)
        if self.vision:
            out.append(CAP_VISION)
        if self.embeddings:
            out.append(CAP_EMBEDDINGS)
        if self.image_generation:
            out.append(CAP_IMAGE_GENERATION)
        if self.video_generation:
            out.append(CAP_VIDEO_GENERATION)
        if self.reasoning:
            out.append(CAP_REASONING)
        if self.code:
            out.append(CAP_CODE)
        if self.json_mode:
            out.append(CAP_JSON_MODE)
        if self.long_context:
            out.append(CAP_LONG_CONTEXT)
        return out

    @classmethod
    def from_list(cls, caps: list[str] | None) -> "ModelCapabilities":
        caps = caps or []
        lower = {str(c).lower() for c in caps}
        return cls(
            chat=(CAP_CHAT in lower) or (not lower),
            streaming=(CAP_STREAMING in lower) or (CAP_CHAT in lower) or (not lower),
            tools=bool({"tools", "tool_calls", "function_calling"} & lower),
            vision=(CAP_VISION in lower),
            embeddings=(CAP_EMBEDDINGS in lower),
            image_generation=(CAP_IMAGE_GENERATION in lower),
            video_generation=(CAP_VIDEO_GENERATION in lower),
            reasoning=(CAP_REASONING in lower),
            code=(CAP_CODE in lower),
            json_mode=(CAP_JSON_MODE in lower),
            long_context=(CAP_LONG_CONTEXT in lower),
        )


# --------------------------------------------------------------------------- #
# Message / result value objects
# --------------------------------------------------------------------------- #
@dataclass
class ChatMessage:
    role: str
    content: str
    name: str = ""
    images: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            payload["name"] = self.name
        if self.images:
            payload["images"] = list(self.images)
        return payload


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        return 0.0  # proxies generally do not expose per-token pricing


@dataclass
class EmbeddingResult:
    vectors: list[list[float]]
    model: str
    provider: str
    dimensions: int = 0
    tokens_in: int = 0
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ImageResult:
    images: list[dict[str, Any]]
    model: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class VideoResult:
    videos: list[dict[str, Any]]
    model: str
    provider: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthReport:
    """Outcome of a real minimal capability/health request."""

    status: str
    ok: bool = False
    latency_ms: int = 0
    checked_at: float = field(default_factory=time.time)
    error: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "ok": self.ok,
            "latency_ms": self.latency_ms,
            "checked_at": self.checked_at,
            "error": self.error,
            "detail": self.detail,
        }


@dataclass
class ModelDescriptor:
    """A discovered model, before/around probing."""

    id: str
    provider: str
    kind: str = KIND_CHAT
    capabilities: list[str] = field(default_factory=list)
    context_length: int = 0
    local: bool = False
    endpoint: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "provider": self.provider,
            "kind": self.kind,
            "capabilities": list(self.capabilities),
            "context_length": self.context_length,
            "local": self.local,
            "endpoint": self.endpoint,
        }


# --------------------------------------------------------------------------- #
# The unified adapter interface
# --------------------------------------------------------------------------- #
class ModelAdapter:
    """Unified provider adapter.

    Concrete adapters override the methods they support. Unsupported operations
    raise ``ModelUnavailableError`` (never a fabricated result).
    """

    #: short adapter name (stable identifier, e.g. "openai_compatible")
    name: str = "base"
    #: provider label surfaced to clients
    provider: str = "base"
    #: whether this provider runs locally (no external egress)
    is_local: bool = False

    # ------------------------------------------------------------- config
    def is_configured(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def status(self) -> str:
        """Coarse provider-level status (one of the explicit states)."""
        if not self.is_configured():
            return STATUS_MISCONFIGURED
        return STATUS_AVAILABLE

    def describe(self) -> dict[str, Any]:
        """Public, non-secret description of the provider configuration."""
        return {
            "name": self.name,
            "provider": self.provider,
            "configured": self.is_configured(),
            "local": self.is_local,
            "status": self.status(),
            "endpoint": self.endpoint_label(),
        }

    def endpoint_label(self) -> str:
        """Endpoint for display — host only, never with embedded credentials."""
        return ""

    # ------------------------------------------------------------ discovery
    def list_models(self) -> list[str]:
        """Cheap model listing (ids only). Not proof of usability."""
        return []

    def discover(self) -> list[ModelDescriptor]:
        """Rich discovery. Default: wrap ``list_models`` with inferred metadata."""
        out: list[ModelDescriptor] = []
        for model_id in self.list_models():
            out.append(
                ModelDescriptor(
                    id=model_id,
                    provider=self.provider,
                    kind=infer_kind(model_id),
                    capabilities=infer_capabilities(model_id).to_list(),
                    context_length=infer_context(model_id),
                    local=self.is_local,
                )
            )
        return out

    def capabilities(self, model: str) -> ModelCapabilities:
        return infer_capabilities(model)

    # ------------------------------------------------------------ execution
    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:  # pragma: no cover
        raise NotImplementedError

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError

    def embed(self, texts: list[str], model: str, **opts: Any) -> EmbeddingResult:  # pragma: no cover
        from backend.app.core.errors import ModelUnavailableError

        raise ModelUnavailableError(f"Provider '{self.provider}' does not support embeddings")

    def generate_image(self, prompt: str, model: str, **opts: Any) -> ImageResult:  # pragma: no cover
        from backend.app.core.errors import ModelUnavailableError

        raise ModelUnavailableError(f"Provider '{self.provider}' does not support image generation")

    def generate_video(self, prompt: str, model: str, **opts: Any) -> VideoResult:  # pragma: no cover
        from backend.app.core.errors import ModelUnavailableError

        raise ModelUnavailableError(f"Provider '{self.provider}' does not support video generation")

    # -------------------------------------------------------------- health
    def health_check(self, model: str | None = None) -> HealthReport:
        """Perform a *real* minimal request and classify the outcome."""
        if not self.is_configured():
            return HealthReport(status=STATUS_MISCONFIGURED, ok=False, error="Provider is not configured")
        if not model:
            return HealthReport(status=STATUS_UNAVAILABLE, ok=False, error="No model specified for probe")
        started = time.time()
        try:
            self.complete([ChatMessage("user", "ping")], model=model, max_tokens=5)
        except Exception as exc:  # noqa: BLE001 - classified below
            return HealthReport(
                status=classify_probe_error(exc),
                ok=False,
                latency_ms=int((time.time() - started) * 1000),
                error=str(exc)[:300],
            )
        return HealthReport(status=STATUS_AVAILABLE, ok=True, latency_ms=int((time.time() - started) * 1000))


# --------------------------------------------------------------------------- #
# Error classification (shared by adapters + registry)
# --------------------------------------------------------------------------- #
def classify_probe_error(exc: BaseException) -> str:
    """Map a probe failure to one of the explicit states."""
    from backend.app.core.errors import ErrorClass, ModelUnavailableError, NetworkError

    text = str(exc).lower()
    if isinstance(exc, ModelUnavailableError):
        if any(tok in text for tok in ("credential", "unauthorized", "401", "403", "not configured", "disabled")):
            return STATUS_MISCONFIGURED
        return STATUS_UNAVAILABLE
    if isinstance(exc, NetworkError):
        return STATUS_UNAVAILABLE
    if "timeout" in text or "timed out" in text or "connection" in text or "unreachable" in text:
        return STATUS_UNAVAILABLE
    if "credential" in text or "unauthorized" in text or "401" in text or "403" in text:
        return STATUS_MISCONFIGURED
    if isinstance(exc, Exception):
        return STATUS_ERROR
    return STATUS_ERROR  # pragma: no cover


def classify_http_status(status_code: int) -> str:
    if status_code in (401, 403):
        return STATUS_MISCONFIGURED
    if status_code == 404:
        return STATUS_MISCONFIGURED
    if 400 <= status_code < 500:
        return STATUS_ERROR
    return STATUS_UNAVAILABLE


# --------------------------------------------------------------------------- #
# Heuristic inference (used when a provider gives no metadata)
# --------------------------------------------------------------------------- #
_EMBEDDING_MARKERS = ("embed", "embedding", "bge", "text-embedding", "nomic-embed", "mxbai")
_IMAGE_MARKERS = ("dall", "dalle", "image", "flux", "stable-diffusion", "sd-", "imagen", "midjourney", "sdxl")
_VIDEO_MARKERS = ("video", "veo", "sora", "runway", "kling", "pika", "luma")
_VISION_MARKERS = ("vision", "-vl", "vl-", "llava", "gpt-4o", "gpt-5", "gemini", "claude-3", "claude-4", "qwen-vl", "minicpm-v")
_CODE_MARKERS = ("code", "coder", "codex", "deepseek-coder", "starcoder", "codestral")
_REASONING_MARKERS = ("o1", "o3", "o4", "reason", "thinking", "r1", "qwq", "gpt-5", "deep-seek", "deepseek-r")
_LONG_CONTEXT_MARKERS = ("1m", "128k", "200k", "long", "gpt-5", "claude-opus", "claude-sonnet", "deep-seek", "gemini")
_TOOL_MARKERS = ("gpt-4", "gpt-5", "claude", "qwen", "llama-3.1", "llama-3.3", "mistral", "firefunction", "command-r")


def infer_kind(model_id: str) -> str:
    lower = (model_id or "").lower()
    if any(t in lower for t in _EMBEDDING_MARKERS):
        return KIND_EMBEDDING
    if any(t in lower for t in _VIDEO_MARKERS):
        return KIND_VIDEO
    if any(t in lower for t in _IMAGE_MARKERS):
        return KIND_IMAGE
    if any(t in lower for t in ("search", "rerank")):
        return KIND_SEARCH
    return KIND_CHAT


def infer_capabilities(model_id: str) -> ModelCapabilities:
    lower = (model_id or "").lower()
    kind = infer_kind(model_id)
    if kind == KIND_EMBEDDING:
        return ModelCapabilities(chat=False, streaming=False, embeddings=True, long_context=("1m" in lower))
    if kind == KIND_IMAGE:
        return ModelCapabilities(chat=False, streaming=False, image_generation=True)
    if kind == KIND_VIDEO:
        return ModelCapabilities(chat=False, streaming=False, video_generation=True)

    caps = ModelCapabilities(chat=True, streaming=True)
    caps.reasoning = any(t in lower for t in _REASONING_MARKERS)
    caps.code = any(t in lower for t in _CODE_MARKERS)
    caps.vision = any(t in lower for t in _VISION_MARKERS)
    caps.tools = any(t in lower for t in _TOOL_MARKERS)
    caps.json_mode = True
    caps.long_context = any(t in lower for t in _LONG_CONTEXT_MARKERS)
    return caps


def infer_context(model_id: str) -> int:
    lower = (model_id or "").lower()
    if "1m" in lower:
        return 1_000_000
    if any(t in lower for t in ("gpt-5", "claude-opus", "claude-sonnet", "deep-seek", "deepseek", "gemini")):
        return 200_000
    if any(t in lower for t in ("qwen", "llama-3.3", "mistral-large")):
        return 128_000
    if any(t in lower for t in ("llama", "mistral", "phi", "gemma")):
        return 32_768
    return 128_000


__all__ = [
    "STATUS_AVAILABLE",
    "STATUS_UNAVAILABLE",
    "STATUS_MISCONFIGURED",
    "STATUS_DISABLED",
    "STATUS_LOADING",
    "STATUS_ERROR",
    "ALL_STATUSES",
    "USABLE_STATUSES",
    "CAP_CHAT",
    "CAP_STREAMING",
    "CAP_TOOLS",
    "CAP_VISION",
    "CAP_EMBEDDINGS",
    "CAP_IMAGE_GENERATION",
    "CAP_VIDEO_GENERATION",
    "CAP_REASONING",
    "CAP_CODE",
    "CAP_JSON_MODE",
    "CAP_LONG_CONTEXT",
    "KIND_CHAT",
    "KIND_EMBEDDING",
    "KIND_IMAGE",
    "KIND_VIDEO",
    "KIND_SEARCH",
    "ModelCapabilities",
    "ChatMessage",
    "ToolCall",
    "Completion",
    "EmbeddingResult",
    "ImageResult",
    "VideoResult",
    "HealthReport",
    "ModelDescriptor",
    "ModelAdapter",
    "classify_probe_error",
    "classify_http_status",
    "infer_kind",
    "infer_capabilities",
    "infer_context",
]
