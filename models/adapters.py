"""Provider adapters implementing the unified :class:`models.base.ModelAdapter`.

Concrete providers:

* :class:`OpenAICompatibleAdapter` — any OpenAI-compatible HTTP API
  (the sandbox LLM proxy, Groq, Together, vLLM, LM Studio, llama.cpp server…).
* :class:`AnthropicAdapter` — Anthropic Messages API.
* :class:`OllamaAdapter` — a local Ollama runtime (native ``/api/tags`` discovery
  plus OpenAI-compatible chat/embeddings on ``/v1``).
* :class:`EchoAdapter` — deterministic, offline adapter for tests only.

Honesty rules (unchanged, now shared through ``models.base``):

* Missing endpoint/key → ``MISCONFIGURED``; disabled → ``DISABLED``.
* A real call that fails is classified — never replaced with canned content.
* ``list_models`` is never treated as proof of usability; a real probe decides.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

import requests

from backend.app.core.errors import ModelUnavailableError, NetworkError, ToolError
from backend.app.core.observability import get_logger
from configs.settings import settings
from models.base import (
    CAP_EMBEDDINGS,
    CAP_IMAGE_GENERATION,
    KIND_EMBEDDING,
    KIND_IMAGE,
    STATUS_AVAILABLE,
    STATUS_DISABLED,
    STATUS_MISCONFIGURED,
    STATUS_UNAVAILABLE,
    ChatMessage,
    Completion,
    EmbeddingResult,
    HealthReport,
    ImageResult,
    ModelAdapter,
    ModelCapabilities,
    ModelDescriptor,
    ToolCall,
    classify_http_status,
    classify_probe_error,
    infer_capabilities,
    infer_context,
    infer_kind,
)

logger = get_logger("models")

#: The sandbox LLM proxy returns HTTP 200 with a billing notice in the body when
#: the account has no usable credits. We must surface that honestly (as
#: MODEL_UNAVAILABLE) instead of treating it as model output.
_CONTROL_MESSAGE_MARKERS = (
    "credits can't be used",
    "credits cannot be used",
    "credit_exhausted",
    "please visit https://www.genspark.ai/pricing",
    "insufficient credit",
    "quota exceeded",
    "rate limit",
)


def _guard_control_message(content: str, provider: str) -> None:
    lowered = (content or "").lower()
    if any(marker in lowered for marker in _CONTROL_MESSAGE_MARKERS):
        raise ModelUnavailableError(
            "Model provider refused the request (billing/quota notice)",
            detail=content[:300],
        )


def _host_label(url: str) -> str:
    """Return a display-safe endpoint label (host only, no credentials)."""
    if not url:
        return ""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        return f"{parsed.scheme}://{host}" if parsed.scheme else host
    except Exception:  # noqa: BLE001
        return url.split("@")[-1]


# --------------------------------------------------------------------------- #
# OpenAI-compatible
# --------------------------------------------------------------------------- #
class OpenAICompatibleAdapter(ModelAdapter):
    """Works with any OpenAI-compatible endpoint (incl. the local LLM proxy)."""

    name = "openai_compatible"
    provider = "openai_compatible"
    is_local = False

    def __init__(self, base_url: str, api_key: str, label: str = "openai_compatible", *, is_local: bool = False) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.provider = label
        self.is_local = is_local

    # ------------------------------------------------------------- config
    def is_configured(self) -> bool:
        # Local OpenAI-compatible servers frequently accept an empty key.
        if self.is_local:
            return bool(self.base_url)
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        if not self.is_configured():
            return STATUS_MISCONFIGURED
        try:
            return STATUS_AVAILABLE if self.list_models() else STATUS_UNAVAILABLE
        except Exception:  # noqa: BLE001
            return STATUS_UNAVAILABLE

    def endpoint_label(self) -> str:
        return _host_label(self.base_url)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    # ------------------------------------------------------------ discovery
    def list_models(self) -> list[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        url = f"{self.base_url}/models"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=settings.model_probe_timeout_seconds)
        except requests.RequestException as exc:
            raise NetworkError("Failed to reach model provider", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Model provider rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def discover(self) -> list[ModelDescriptor]:
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
                    endpoint=self.endpoint_label(),
                )
            )
        return out

    # ------------------------------------------------------------ execution
    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "max_tokens": int(opts.get("max_tokens", settings.llm_max_tokens)),
        }
        for key in ("temperature", "top_p", "stop", "tools", "tool_choice", "response_format", "presence_penalty", "frequency_penalty"):
            if opts.get(key) is not None:
                payload[key] = opts[key]
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.Timeout as exc:
            raise NetworkError("Model request timed out", detail=str(exc)) from exc
        except requests.RequestException as exc:
            raise NetworkError("Model request failed", detail=str(exc)) from exc

        if resp.status_code in (401, 403):
            raise ModelUnavailableError("Model provider rejected credentials", detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 500:
            raise NetworkError("Model provider server error", detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ToolError("Model request invalid", detail=resp.text[:500])
        data = resp.json()
        if not data.get("choices"):
            raise ToolError("Model returned no choices", detail=json.dumps(data)[:500])
        choice = data["choices"][0]
        message = choice.get("message") or {}
        usage = data.get("usage") or {}
        content = message.get("content") or ""
        _guard_control_message(content, self.provider)
        return Completion(
            text=content,
            model=data.get("model", model),
            provider=self.provider,
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=choice.get("finish_reason", "") or "",
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            raw={"tool_calls": message.get("tool_calls"), "id": data.get("id")},
        )

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        payload = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "stream": True,
            "max_tokens": int(opts.get("max_tokens", settings.llm_max_tokens)),
        }
        for key in ("temperature", "top_p"):
            if opts.get(key) is not None:
                payload[key] = opts[key]
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
                stream=True,
            )
        except requests.RequestException as exc:
            raise NetworkError("Streaming request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Streaming request rejected", detail=f"HTTP {resp.status_code}")
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            chunk = raw_line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            for choice in obj.get("choices", []):
                delta = choice.get("delta") or {}
                text = delta.get("content")
                if text:
                    if any(m.lower() in text.lower() for m in _CONTROL_MESSAGE_MARKERS):
                        raise ModelUnavailableError(
                            "Model provider refused the request (billing/quota notice)",
                            detail=text[:300],
                        )
                    yield text

    def embed(self, texts: list[str], model: str, **opts: Any) -> EmbeddingResult:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        payload = {"model": model, "input": texts}
        try:
            resp = requests.post(
                f"{self.base_url}/embeddings",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Embedding request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Embedding request rejected", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        vectors = [item.get("embedding", []) for item in data.get("data", [])]
        usage = data.get("usage") or {}
        return EmbeddingResult(
            vectors=vectors,
            model=data.get("model", model),
            provider=self.provider,
            dimensions=len(vectors[0]) if vectors else 0,
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
        )

    def generate_image(self, prompt: str, model: str, **opts: Any) -> ImageResult:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        payload = {"model": model, "prompt": prompt, "n": int(opts.get("n", 1))}
        for key in ("size", "response_format", "style"):
            if opts.get(key) is not None:
                payload[key] = opts[key]
        try:
            resp = requests.post(
                f"{self.base_url}/images/generations",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Image request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Image request rejected", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        return ImageResult(images=data.get("data", []), model=data.get("model", model), provider=self.provider, raw=data)

    # -------------------------------------------------------------- health
    def health_check(self, model: str | None = None) -> HealthReport:
        """A real minimal chat completion (not just a listing) decides usability."""
        if not self.is_configured():
            return HealthReport(status=STATUS_MISCONFIGURED, ok=False, error="Provider is not configured")
        if not model:
            return HealthReport(status=STATUS_UNAVAILABLE, ok=False, error="No model specified for probe")
        import time

        started = time.time()
        try:
            self.complete([ChatMessage("user", "ping")], model=model, max_tokens=5)
        except Exception as exc:  # noqa: BLE001
            return HealthReport(
                status=classify_probe_error(exc),
                ok=False,
                latency_ms=int((time.time() - started) * 1000),
                error=str(exc)[:300],
            )
        return HealthReport(status=STATUS_AVAILABLE, ok=True, latency_ms=int((time.time() - started) * 1000))


# --------------------------------------------------------------------------- #
# Anthropic
# --------------------------------------------------------------------------- #
class AnthropicAdapter(ModelAdapter):
    """Anthropic Messages API adapter (optional, only if configured)."""

    name = "anthropic"
    provider = "anthropic"
    is_local = False

    _KNOWN_MODELS = ("claude-sonnet-4-5", "claude-opus-4-5", "claude-3-5-sonnet-latest", "claude-3-5-haiku-latest")

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        if not self.is_configured():
            return STATUS_MISCONFIGURED
        return STATUS_AVAILABLE if self.list_models() else STATUS_UNAVAILABLE

    def endpoint_label(self) -> str:
        return _host_label(self.base_url)

    def list_models(self) -> list[str]:
        return list(self._KNOWN_MODELS) if self.is_configured() else []

    def discover(self) -> list[ModelDescriptor]:
        out: list[ModelDescriptor] = []
        for model_id in self.list_models():
            caps = ModelCapabilities(chat=True, streaming=True, tools=True, vision=True, reasoning=True, long_context=True)
            out.append(
                ModelDescriptor(
                    id=model_id,
                    provider=self.provider,
                    kind=infer_kind(model_id),
                    capabilities=caps.to_list(),
                    context_length=200_000,
                    local=False,
                    endpoint=self.endpoint_label(),
                )
            )
        return out

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Anthropic provider not configured")
        system = "\n".join(m.content for m in messages if m.role == "system")
        convo = [m.to_dict() for m in messages if m.role != "system"]
        payload: dict[str, Any] = {"model": model, "max_tokens": int(opts.get("max_tokens", settings.llm_max_tokens)), "messages": convo}
        if system:
            payload["system"] = system
        if opts.get("tools"):
            payload["tools"] = opts["tools"]
        try:
            resp = requests.post(
                f"{self.base_url}/messages",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Anthropic request failed", detail=str(exc)) from exc
        if resp.status_code in (401, 403):
            raise ModelUnavailableError("Anthropic rejected credentials", detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ModelUnavailableError("Anthropic rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        _guard_control_message(text, self.provider)
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=data.get("model", model),
            provider=self.provider,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
            finish_reason=data.get("stop_reason", "") or "",
        )

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        # Streaming uses the SSE Messages API; fall back to a single chunk.
        if not self.is_configured():
            raise ModelUnavailableError("Anthropic provider not configured")
        system = "\n".join(m.content for m in messages if m.role == "system")
        convo = [m.to_dict() for m in messages if m.role != "system"]
        payload: dict[str, Any] = {
            "model": model,
            "max_tokens": int(opts.get("max_tokens", settings.llm_max_tokens)),
            "messages": convo,
            "stream": True,
        }
        if system:
            payload["system"] = system
        try:
            resp = requests.post(
                f"{self.base_url}/messages",
                headers=self._headers(),
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
                stream=True,
            )
        except requests.RequestException as exc:
            raise NetworkError("Anthropic streaming request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Anthropic streaming request rejected", detail=f"HTTP {resp.status_code}")
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line or not raw_line.startswith("data:"):
                continue
            chunk = raw_line[5:].strip()
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            if obj.get("type") == "content_block_delta":
                text = (obj.get("delta") or {}).get("text")
                if text:
                    yield text


# --------------------------------------------------------------------------- #
# Ollama (local)
# --------------------------------------------------------------------------- #
class OllamaAdapter(ModelAdapter):
    """Local Ollama runtime.

    Discovery uses the native ``/api/tags`` endpoint (rich metadata, no key
    required). Chat/embeddings use the OpenAI-compatible ``/v1`` surface so the
    same code path as other providers applies. Any other OpenAI-compatible local
    server (llama.cpp / LM Studio / vLLM) can be attached with
    ``openai_compatible=True``.
    """

    name = "ollama"
    provider = "ollama"
    is_local = True

    def __init__(self, base_url: str, api_key: str = "", *, openai_compatible: bool = False) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self._openai_compatible = openai_compatible
        self._inner = OpenAICompatibleAdapter(self.base_url, self.api_key, label=self.provider, is_local=True)

    def is_configured(self) -> bool:
        return bool(self.base_url)

    def status(self) -> str:
        if not self.is_configured():
            return STATUS_MISCONFIGURED
        try:
            return STATUS_AVAILABLE if self.list_models() else STATUS_UNAVAILABLE
        except Exception:  # noqa: BLE001
            return STATUS_UNAVAILABLE

    def endpoint_label(self) -> str:
        return _host_label(self.base_url)

    def _native_base(self) -> str:
        # Strip a trailing /v1 if present, so /api/tags resolves.
        base = self.base_url
        if base.endswith("/v1"):
            base = base[:-3]
        return base

    def list_models(self) -> list[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        if self._openai_compatible:
            return self._inner.list_models()
        url = f"{self._native_base()}/api/tags"
        try:
            resp = requests.get(url, timeout=settings.model_probe_timeout_seconds)
        except requests.RequestException as exc:
            raise NetworkError("Failed to reach Ollama runtime", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Ollama rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        return [m.get("name", "") for m in data.get("models", []) if m.get("name")]

    def discover(self) -> list[ModelDescriptor]:
        out: list[ModelDescriptor] = []
        if not self._openai_compatible:
            try:
                resp = requests.get(f"{self._native_base()}/api/tags", timeout=settings.model_probe_timeout_seconds)
                if resp.status_code < 400:
                    for entry in resp.json().get("models", []):
                        model_id = entry.get("name", "")
                        if not model_id:
                            continue
                        details = entry.get("details") or {}
                        caps = infer_capabilities(model_id)
                        out.append(
                            ModelDescriptor(
                                id=model_id,
                                provider=self.provider,
                                kind=infer_kind(model_id),
                                capabilities=caps.to_list(),
                                context_length=_ollama_context(entry, model_id),
                                local=True,
                                endpoint=self.endpoint_label(),
                                raw={"family": details.get("family"), "parameter_size": details.get("parameter_size")},
                            )
                        )
                    return out
            except requests.RequestException:
                pass
        for model_id in self.list_models():
            out.append(
                ModelDescriptor(
                    id=model_id,
                    provider=self.provider,
                    kind=infer_kind(model_id),
                    capabilities=infer_capabilities(model_id).to_list(),
                    context_length=infer_context(model_id),
                    local=True,
                    endpoint=self.endpoint_label(),
                )
            )
        return out

    # Delegate execution to the OpenAI-compatible surface (/v1/...).
    def _v1(self) -> OpenAICompatibleAdapter:
        if self._inner.base_url.endswith("/v1"):
            return self._inner
        self._inner = OpenAICompatibleAdapter(f"{self.base_url}/v1", self.api_key, label=self.provider, is_local=True)
        return self._inner

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        return self._v1().complete(messages, model, **opts)

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        return self._v1().stream(messages, model, **opts)

    def embed(self, texts: list[str], model: str, **opts: Any) -> EmbeddingResult:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        return self._v1().embed(texts, model, **opts)


def _ollama_context(entry: dict[str, Any], model_id: str) -> int:
    params = entry.get("parameters") or ""
    if isinstance(params, str) and "num_ctx" in params:
        try:
            for line in params.splitlines():
                if "num_ctx" in line:
                    return int(line.split()[-1])
        except (ValueError, IndexError):
            pass
    return infer_context(model_id)


# --------------------------------------------------------------------------- #
# Echo (deterministic, tests only)
# --------------------------------------------------------------------------- #
class EchoAdapter(ModelAdapter):
    """Deterministic, offline adapter used ONLY when explicitly selected for tests.

    It is never auto-activated: the registry marks it DISABLED unless
    ``LAIW_ENABLE_ECHO_MODEL=true``. This keeps fabricated LLM output out of
    normal operation while allowing deterministic unit tests.
    """

    name = "echo"
    provider = "echo"
    is_local = True

    def is_configured(self) -> bool:
        import os

        return os.environ.get("LAIW_ENABLE_ECHO_MODEL", "false").lower() == "true"

    def status(self) -> str:
        return STATUS_AVAILABLE if self.is_configured() else STATUS_DISABLED

    def list_models(self) -> list[str]:
        return ["echo"] if self.is_configured() else []

    def discover(self) -> list[ModelDescriptor]:
        if not self.is_configured():
            return []
        return [
            ModelDescriptor(
                id="echo",
                provider=self.provider,
                kind="chat",
                capabilities=["chat", "streaming"],
                context_length=4096,
                local=True,
            )
        ]

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Echo adapter disabled")
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return Completion(
            text=f"[echo] {last}",
            model="echo",
            provider="echo",
            tokens_in=len(last.split()),
            tokens_out=len(last.split()) + 1,
        )

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        yield self.complete(messages, model, **opts).text


# --------------------------------------------------------------------------- #
# Backwards-compatible alias
# --------------------------------------------------------------------------- #
#: Older code/tests import ``BaseChatAdapter``; it now resolves to the unified
#: :class:`ModelAdapter`.
BaseChatAdapter = ModelAdapter


def _parse_tool_calls(raw: Any) -> list[ToolCall]:
    out: list[ToolCall] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        fn = item.get("function") or {}
        out.append(ToolCall(id=item.get("id", ""), name=fn.get("name", ""), arguments=fn.get("arguments")))
    return out


__all__ = [
    "ChatMessage",
    "Completion",
    "ToolCall",
    "EmbeddingResult",
    "ImageResult",
    "HealthReport",
    "ModelAdapter",
    "ModelCapabilities",
    "BaseChatAdapter",
    "OpenAICompatibleAdapter",
    "AnthropicAdapter",
    "OllamaAdapter",
    "EchoAdapter",
    "_guard_control_message",
    "_CONTROL_MESSAGE_MARKERS",
]
