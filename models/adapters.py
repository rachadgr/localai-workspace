"""Provider adapters for chat/completion models.

Honesty rules enforced here:
* If an endpoint/key is missing the adapter reports ``UNAVAILABLE``.
* If a call fails the raised error is classified (never a fabricated answer).
* No adapter ever returns canned/simulated content.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterator

import requests

from backend.app.core.errors import ModelUnavailableError, NetworkError, ToolError
from backend.app.core.observability import get_logger
from configs.settings import settings

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


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


@dataclass
class Completion:
    text: str
    model: str
    provider: str
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def cost_usd(self) -> float:
        return 0.0  # proxy does not expose per-token pricing


class BaseChatAdapter:
    name = "base"
    provider = "base"

    def is_configured(self) -> bool:  # pragma: no cover - overridden
        raise NotImplementedError

    def status(self) -> str:  # pragma: no cover - overridden
        raise NotImplementedError

    def list_models(self) -> list[str]:  # pragma: no cover - overridden
        return []

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:  # pragma: no cover
        raise NotImplementedError

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:  # pragma: no cover
        raise NotImplementedError


class OpenAICompatibleAdapter(BaseChatAdapter):
    """Works with any OpenAI-compatible endpoint (incl. the local LLM proxy)."""

    name = "openai_compatible"
    provider = "openai_compatible"

    def __init__(self, base_url: str, api_key: str, label: str = "openai_compatible") -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""
        self.provider = label

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        if not self.base_url or not self.api_key:
            return "MISCONFIGURED"
        try:
            self.list_models()
            return "AVAILABLE"
        except Exception:
            return "UNAVAILABLE"

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def list_models(self) -> list[str]:
        if not self.is_configured():
            raise ModelUnavailableError("Model provider not configured")
        url = f"{self.base_url}/models"
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15)
        except requests.RequestException as exc:
            raise NetworkError("Failed to reach model provider", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Model provider rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

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


class AnthropicAdapter(BaseChatAdapter):
    """Anthropic Messages API adapter (optional, only if configured)."""

    name = "anthropic"
    provider = "anthropic"

    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key or ""

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def status(self) -> str:
        if not self.base_url or not self.api_key:
            return "MISCONFIGURED"
        return "AVAILABLE" if self.list_models() else "UNAVAILABLE"

    def list_models(self) -> list[str]:
        return ["claude-sonnet-4-5", "claude-opus-4-5"] if self.is_configured() else []

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Anthropic provider not configured")
        system = "\n".join(m.content for m in messages if m.role == "system")
        convo = [m.to_dict() for m in messages if m.role != "system"]
        payload: dict[str, Any] = {"model": model, "max_tokens": int(opts.get("max_tokens", settings.llm_max_tokens)), "messages": convo}
        if system:
            payload["system"] = system
        try:
            resp = requests.post(
                f"{self.base_url}/messages",
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"},
                data=json.dumps(payload),
                timeout=settings.llm_timeout_seconds,
            )
        except requests.RequestException as exc:
            raise NetworkError("Anthropic request failed", detail=str(exc)) from exc
        if resp.status_code >= 400:
            raise ModelUnavailableError("Anthropic rejected the request", detail=f"HTTP {resp.status_code}")
        data = resp.json()
        text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
        usage = data.get("usage") or {}
        return Completion(
            text=text,
            model=data.get("model", model),
            provider=self.provider,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
        )

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        yield self.complete(messages, model, **opts).text


class EchoAdapter(BaseChatAdapter):
    """Deterministic, offline adapter used ONLY when explicitly selected for tests.

    It is never auto-activated: the registry marks it DISABLED unless
    ``LAIW_ENABLE_ECHO_MODEL=true``. This keeps fabricated LLM output out of
    normal operation while allowing deterministic unit tests.
    """

    name = "echo"
    provider = "echo"

    def is_configured(self) -> bool:
        import os

        return os.environ.get("LAIW_ENABLE_ECHO_MODEL", "false").lower() == "true"

    def status(self) -> str:
        return "AVAILABLE" if self.is_configured() else "DISABLED"

    def list_models(self) -> list[str]:
        return ["echo"] if self.is_configured() else []

    def complete(self, messages: list[ChatMessage], model: str, **opts: Any) -> Completion:
        if not self.is_configured():
            raise ModelUnavailableError("Echo adapter disabled")
        last = next((m.content for m in reversed(messages) if m.role == "user"), "")
        return Completion(text=f"[echo] {last}", model="echo", provider="echo", tokens_in=len(last.split()), tokens_out=len(last.split()) + 1)

    def stream(self, messages: list[ChatMessage], model: str, **opts: Any) -> Iterator[str]:
        yield self.complete(messages, model, **opts).text
