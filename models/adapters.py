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
# Reasoning / thinking separation
# --------------------------------------------------------------------------- #
#: Field names a provider may use to *separate* the model's chain-of-thought from
#: the answer. Ollama's OpenAI-compatible ``/v1`` surface streams it as
#: ``delta.reasoning``; its native ``/api/chat`` uses ``message.thinking``.
_REASONING_KEYS = ("reasoning", "reasoning_content", "thinking")

#: Inline blocks some providers/templates embed inside ``content``. The Qwen3
#: template opens the assistant turn with ``<think>`` and terminates it with the
#: end-of-turn token; other providers close it explicitly with ``</think>``.
#: Built via concatenation so the markers survive any markup-sensitive tooling.
_THINK_OPEN = "<" + "think" + ">"
_THINK_CLOSE = "<" + "/" + "think" + ">"
_INLINE_REASONING_BLOCKS: tuple[tuple[str, str], ...] = (
    (_THINK_OPEN, _THINK_CLOSE),
    ("<reasoning>", "</reasoning>"),
    ("<|begin_of_thought|>", "<|end_of_thought|>"),
)


def _split_reasoning_fields(payload: dict[str, Any]) -> tuple[str, str]:
    """Split a message/delta dict into ``(answer_text, reasoning_text)``.

    ``answer_text`` is ``content`` with any inline reasoning blocks removed;
    ``reasoning_text`` is the concatenation of the explicit reasoning fields
    (``reasoning`` / ``reasoning_content`` / ``thinking``) plus any inline block.
    Never raises and never mutates the input.
    """
    content = payload.get("content")
    content = "" if content is None else str(content)
    reasoning_parts = []
    for key in _REASONING_KEYS:
        value = payload.get(key)
        if value:
            reasoning_parts.append(str(value))
    if content:
        content, inline = _strip_inline_reasoning(content)
        if inline:
            reasoning_parts.append(inline)
    return content, "".join(reasoning_parts)


def _strip_inline_reasoning(text: str) -> tuple[str, str]:
    """Return ``(answer, reasoning)`` with inline reasoning blocks removed.

    Operates on a complete string (non-streaming path). Streaming uses
    :class:`ReasoningStreamSplitter`, which is boundary-aware.
    """
    splitter = ReasoningStreamSplitter()
    answer = splitter.feed(text)
    answer += splitter.flush()
    return answer, splitter.reasoning


class ReasoningStreamSplitter:
    """Boundary-aware separator for streamed tokens.

    Adapters feed raw ``content`` text; the splitter returns the *answer* text to
    emit and accumulates the reasoning internally. Explicit reasoning fields are
    fed straight to :meth:`add_reasoning`. Inline `` thinking…`` blocks (which may
    be split across transport chunks) are buffered so a partial marker is never
    emitted as an answer and reasoning never leaks into the visible stream.
    """

    def __init__(self, blocks: tuple[tuple[str, str], ...] = _INLINE_REASONING_BLOCKS) -> None:
        self._blocks = blocks
        self._openers = tuple(o for o, _ in blocks)
        self._closer = ""  # first block's closing marker drives the "inside" state
        self._in_reasoning = False
        self._buffer = ""
        self._reasoning: list[str] = []

    def add_reasoning(self, text: str | None) -> None:
        if text:
            self._reasoning.append(str(text))

    def feed(self, text: str | None) -> str:
        """Consume raw ``content``; return the answer text to emit (may be ``""``)."""
        if not text:
            return ""
        self._buffer += str(text)
        out: list[str] = []
        while self._buffer:
            if not self._in_reasoning:
                idx, opener = self._find_opener(self._buffer)
                if idx == -1:
                    keep = self._partial_suffix(self._buffer, self._openers)
                    out.append(self._buffer[: len(self._buffer) - keep] if keep else self._buffer)
                    self._buffer = self._buffer[len(self._buffer) - keep:] if keep else ""
                    break
                out.append(self._buffer[:idx])
                self._buffer = self._buffer[idx + len(opener):]
                self._closer = dict(self._blocks).get(opener, "")
                self._in_reasoning = True
            else:
                idx = self._buffer.find(self._closer) if self._closer else -1
                if idx == -1:
                    keep = self._partial_suffix(self._buffer, (self._closer,)) if self._closer else 0
                    if keep:
                        self._reasoning.append(self._buffer[: len(self._buffer) - keep])
                        self._buffer = self._buffer[len(self._buffer) - keep:]
                    else:
                        self._reasoning.append(self._buffer)
                        self._buffer = ""
                    break
                self._reasoning.append(self._buffer[:idx])
                self._buffer = self._buffer[idx + len(self._closer):]
                self._in_reasoning = False
        return "".join(out)

    def flush(self) -> str:
        """Return any trailing answer text once the stream has ended."""
        leftover = self._buffer
        self._buffer = ""
        if not leftover:
            return ""
        if self._in_reasoning:
            self._reasoning.append(leftover)
            return ""
        return leftover

    @property
    def reasoning(self) -> str:
        return "".join(self._reasoning)

    def _find_opener(self, text: str) -> tuple[int, str]:
        best_idx = -1
        best_opener = ""
        for opener in self._openers:
            idx = text.find(opener)
            if idx != -1 and (best_idx == -1 or idx < best_idx):
                best_idx, best_opener = idx, opener
        return best_idx, best_opener

    @staticmethod
    def _partial_suffix(text: str, markers: tuple[str, ...]) -> int:
        """Longest ``k`` (``k < len(marker)``) where ``text`` ends with ``marker[:k]``."""
        best = 0
        for marker in markers:
            if not marker:
                continue
            for k in range(min(len(marker) - 1, len(text)), 0, -1):
                if text.endswith(marker[:k]):
                    best = max(best, k)
                    break
        return best


def _contains_control_message(text: str) -> bool:
    lowered = (text or "").lower()
    return any(marker in lowered for marker in _CONTROL_MESSAGE_MARKERS)


def _first_reasoning_field(payload: dict[str, Any]) -> str:
    """Return the first non-empty separated reasoning value in ``payload``.

    Streaming deltas carry reasoning in a single key at a time
    (``reasoning`` / ``reasoning_content`` / ``thinking``); this returns whichever
    is present so the caller can accumulate it internally.
    """
    for key in _REASONING_KEYS:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


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
        #: Reasoning captured from the most recent ``complete``/``stream`` call
        #: (when the provider separates it). Never emitted as answer text.
        self.last_reasoning = ""

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
        # Separate the answer (content) from any reasoning the provider exposes
        # separately or inlines. Reasoning is captured, never returned as text.
        content, reasoning = _split_reasoning_fields(message)
        self.last_reasoning = reasoning
        _guard_control_message(content, self.provider)
        return Completion(
            text=content,
            model=data.get("model", model),
            provider=self.provider,
            tokens_in=int(usage.get("prompt_tokens", 0) or 0),
            tokens_out=int(usage.get("completion_tokens", 0) or 0),
            finish_reason=choice.get("finish_reason", "") or "",
            tool_calls=_parse_tool_calls(message.get("tool_calls")),
            raw={"tool_calls": message.get("tool_calls"), "id": data.get("id"), "reasoning": reasoning},
            reasoning=reasoning,
        )

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        return self._stream_impl(messages, model, **opts)

    def _stream_impl(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
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
        if opts.get("think") is not None:
            # Only forwarded when explicitly requested; providers that do not
            # understand it simply ignore the extra field.
            payload["think"] = opts["think"]
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
        splitter = ReasoningStreamSplitter()
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
                # Explicit reasoning fields → internal only (never emitted).
                reasoning_field = _first_reasoning_field(delta)
                if reasoning_field:
                    splitter.add_reasoning(reasoning_field)
                content = delta.get("content")
                if content:
                    for piece in (splitter.feed(content),):
                        if piece:
                            if _contains_control_message(piece):
                                raise ModelUnavailableError(
                                    "Model provider refused the request (billing/quota notice)",
                                    detail=piece[:300],
                                )
                            yield piece
        tail = splitter.flush()
        if tail:
            if _contains_control_message(tail):
                raise ModelUnavailableError(
                    "Model provider refused the request (billing/quota notice)",
                    detail=tail[:300],
                )
            yield tail
        self.last_reasoning = splitter.reasoning

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
        #: Reasoning captured from the most recent call (native or /v1 path).
        self.last_reasoning = ""

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

    # ------------------------------------------------------------- thinking
    @staticmethod
    def _coerce_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    def _resolve_think(self, opts: dict[str, Any]) -> bool | None:
        """Resolve the requested thinking mode (and consume the ``think`` opt).

        Priority: explicit per-call ``think`` opt → ``LAIW_OLLAMA_THINK`` setting.
        ``None`` means "no preference" (keep the default OpenAI-compatible path).

        Empirically, Ollama's OpenAI-compatible ``/v1`` surface *ignores* the
        ``think`` field, while the native ``/api/chat`` honours it — so whenever a
        preference is expressed we must use the native endpoint (no hack, no
        hardcoded assumption).
        """
        if opts.get("think") is not None:
            return self._coerce_bool(opts.pop("think"))
        opts.pop("think", None)
        configured = getattr(settings, "ollama_think", "") or ""
        if str(configured).strip() != "":
            return self._coerce_bool(configured)
        return None

    def _native_options(self, opts: dict[str, Any]) -> dict[str, Any]:
        options: dict[str, Any] = {}
        if opts.get("temperature") is not None:
            options["temperature"] = opts["temperature"]
        if opts.get("top_p") is not None:
            options["top_p"] = opts["top_p"]
        if opts.get("max_tokens") is not None:
            options["num_predict"] = int(opts["max_tokens"])
        return options

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        think = self._resolve_think(opts)
        if think is not None:
            return self._native_complete(messages, model, think=think, **opts)
        return self._v1().complete(messages, model, **opts)

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        think = self._resolve_think(opts)
        if think is not None:
            return self._native_stream(messages, model, think=think, **opts)
        return self._v1().stream(messages, model, **opts)

    def embed(self, texts: list[str], model: str, **opts: Any) -> EmbeddingResult:
        if not self.is_configured():
            raise ModelUnavailableError("Ollama provider not configured")
        return self._v1().embed(texts, model, **opts)

    # ------------------------------------------------------ native /api/chat
    def _native_payload(self, messages: list[ChatMessage], model: str, think: bool, opts: dict[str, Any]) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_dict() for m in messages],
            "think": think,
        }
        options = self._native_options(opts)
        if options:
            payload["options"] = options
        return payload

    def _native_complete(self, messages: list[ChatMessage], model: str, *, think: bool, **opts: Any) -> Completion:
        payload = {**self._native_payload(messages, model, think, opts), "stream": False}
        try:
            resp = requests.post(
                f"{self._native_base()}/api/chat",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Ollama request failed", detail=str(exc)) from exc
        if resp.status_code in (401, 403):
            raise ModelUnavailableError("Ollama rejected credentials", detail=f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise ModelUnavailableError("Ollama rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        message = data.get("message") or {}
        content, reasoning = _split_reasoning_fields(message)
        self.last_reasoning = reasoning
        _guard_control_message(content, self.provider)
        return Completion(
            text=content,
            model=data.get("model", model),
            provider=self.provider,
            tokens_in=int(data.get("prompt_eval_count", 0) or 0),
            tokens_out=int(data.get("eval_count", 0) or 0),
            finish_reason=data.get("done_reason", "") or "",
            raw={"reasoning": reasoning, "thinking": message.get("thinking")},
            reasoning=reasoning,
        )

    def _native_stream(self, messages: list[ChatMessage], model: str, *, think: bool, **opts: Any) -> Iterator[str]:
        payload = {**self._native_payload(messages, model, think, opts), "stream": True}
        try:
            resp = requests.post(
                f"{self._native_base()}/api/chat",
                headers={"Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
                stream=True,
            )
        except requests.RequestException as exc:
            raise NetworkError("Ollama streaming request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Ollama streaming request rejected", detail=f"HTTP {resp.status_code}")
        splitter = ReasoningStreamSplitter()
        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line[5:].strip() if raw_line.startswith("data:") else raw_line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("error"):
                raise ModelUnavailableError("Ollama returned an error", detail=str(obj.get("error"))[:300])
            message = obj.get("message") or {}
            reasoning_field = _first_reasoning_field(message)
            if reasoning_field:
                splitter.add_reasoning(reasoning_field)
            content = message.get("content")
            if content:
                piece = splitter.feed(content)
                if piece:
                    if _contains_control_message(piece):
                        raise ModelUnavailableError(
                            "Model provider refused the request (billing/quota notice)",
                            detail=piece[:300],
                        )
                    yield piece
            if obj.get("done"):
                break
        tail = splitter.flush()
        if tail:
            if _contains_control_message(tail):
                raise ModelUnavailableError(
                    "Model provider refused the request (billing/quota notice)",
                    detail=tail[:300],
                )
            yield tail
        self.last_reasoning = splitter.reasoning


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
# LocalAI (self-hosted, OpenAI-compatible)
# --------------------------------------------------------------------------- #
class LocalAIAdapter(OpenAICompatibleAdapter):
    """LocalAI runtime adapter (https://localai.io).

    LocalAI is a self-hosted, OpenAI-compatible server that serves *local* models:
    chat, embeddings, image generation and (where a model is installed) more. It
    exposes the standard OpenAI surface (``/v1/models``, ``/v1/chat/completions``,
    ``/v1/embeddings``, ``/v1/images/generations``) plus a readiness probe at
    ``/readyz``.

    This adapter simply specializes :class:`OpenAICompatibleAdapter` so:

    * discovery uses the real ``/v1/models`` listing (no fabricated models);
    * an empty API key is accepted (LocalAI runs unauthenticated by default — an
      ``is_local`` OpenAI-compatible server);
    * ``status()`` additionally consults ``/readyz`` so a reachable-but-not-ready
      runtime is reported honestly instead of being marked ``AVAILABLE``.

    Honesty rules are inherited unchanged: a model is only ``AVAILABLE`` after a
    real minimal request succeeds; nothing is ever fabricated and no model is
    downloaded. A LocalAI model that is listed but not installed on the host is
    reported whatever its probe genuinely returns — never forced to ``AVAILABLE``.
    """

    name = "localai"
    provider = "localai"
    is_local = True

    def __init__(self, base_url: str, api_key: str = "") -> None:
        # LocalAI speaks OpenAI-compatible at the root or under /v1; normalize to
        # the /v1 surface (matching OpenAICompatibleAdapter expectations).
        base = (base_url or "").rstrip("/")
        if base and not base.endswith("/v1"):
            base = f"{base}/v1"
        super().__init__(base, api_key, label="localai", is_local=True)

    def _native_base(self) -> str:
        base = self.base_url
        return base[:-3] if base.endswith("/v1") else base

    def readyz(self) -> bool | None:
        """Consult LocalAI's readiness probe.

        Returns ``True`` when ``/readyz`` answers 2xx, ``False`` when it answers a
        non-2xx status, and ``None`` when the probe could not be reached at all
        (so a missing ``/readyz`` on older builds never forces a false verdict).
        """
        if not self.base_url:
            return None
        try:
            resp = requests.get(f"{self._native_base()}/readyz", timeout=settings.model_probe_timeout_seconds)
        except requests.RequestException:
            return None
        return 200 <= resp.status_code < 300

    def status(self) -> str:
        if not self.is_configured():
            return STATUS_MISCONFIGURED
        ready = self.readyz()
        if ready is False:
            # Reachable server that is not ready to serve yet.
            return STATUS_UNAVAILABLE
        try:
            return STATUS_AVAILABLE if self.list_models() else STATUS_UNAVAILABLE
        except Exception:  # noqa: BLE001
            return STATUS_UNAVAILABLE


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
    "LocalAIAdapter",
    "EchoAdapter",
    "_guard_control_message",
    "_CONTROL_MESSAGE_MARKERS",
]
