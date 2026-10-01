"""AI Chat tool: model-routed conversation with context and optional tool calling."""

from __future__ import annotations

from typing import Any

from backend.app.core.errors import ModelUnavailableError
from models.adapters import ChatMessage
from models.registry import STATUS_AVAILABLE
from tools.base import BaseTool, Permission, ToolContext, ToolResult, ValidationReport
from tools.registry import register

#: Default system instruction (unchanged behaviour).
_DEFAULT_SYSTEM = (
    "You are LocalAI Workspace, a precise, honest assistant. If you are unsure or lack data, "
    "say so explicitly instead of inventing facts."
)

#: Header for the live runtime-context system message. It states explicitly that the
#: values are read from the registry and are authoritative runtime facts that must
#: not be contradicted or replaced by general knowledge.
_RUNTIME_CONTEXT_INTRO = (
    "Runtime facts about the model currently handling this conversation. "
    "These values are read live from the model registry and are authoritative: "
    "do not contradict, replace, or guess them from general knowledge. "
    "When the user asks about the model's status, provider, endpoint, capabilities, "
    "or whether it runs locally, rely on these runtime facts rather than general assumptions."
)


def _runtime_model_facts(model_id: str, registry: Any) -> dict[str, Any] | None:
    """Read the chosen model's registry metadata as plain runtime facts.

    Returns ``None`` when the registry exposes no ``ModelInfo`` for ``model_id``
    (or the lookup fails for any reason). It never raises, so a missing lookup
    degrades to the current behaviour instead of breaking the chat. No provider,
    model name, or endpoint is hardcoded: every value is taken from the registry.
    """
    try:
        getter = getattr(registry, "get", None)
        if not callable(getter):
            return None
        info = getter(model_id)
    except Exception:  # noqa: BLE001 - metadata is best-effort, never fatal
        return None
    if info is None:
        return None

    def _get(name: str, default: Any = None) -> Any:
        try:
            return getattr(info, name, default)
        except Exception:  # noqa: BLE001
            return default

    context_window = _get("context_window", 0) or _get("context_length", 0) or 0
    return {
        "id": _get("id", model_id) or model_id,
        "name": _get("name", "") or model_id,
        "provider": _get("provider", ""),
        "status": _get("status", ""),
        "local": bool(_get("local", False)),
        "endpoint": _get("endpoint", "") or "",
        "vision": bool(_get("vision", False)),
        "tools": bool(_get("tools", False)),
        "streaming": bool(_get("streaming", False)),
        "context_window": context_window,
    }


def _render_runtime_context(facts: dict[str, Any]) -> str:
    """Render runtime facts as an authoritative system message (no hardcoding)."""
    lines = [
        _RUNTIME_CONTEXT_INTRO,
        "",
        "Current runtime facts:",
        f"- model_id: {facts['id']}",
        f"- model_name: {facts['name']}",
        f"- provider: {facts['provider']}",
        f"- status: {facts['status']}",
        f"- local: {'true' if facts['local'] else 'false'}",
        f"- endpoint: {facts['endpoint'] or '(not disclosed)'}",
        f"- vision: {'true' if facts['vision'] else 'false'}",
        f"- tools: {'true' if facts['tools'] else 'false'}",
        f"- streaming: {'true' if facts['streaming'] else 'false'}",
        f"- context_window: {facts['context_window']}",
    ]
    return "\n".join(lines)


@register
class ChatTool(BaseTool):
    name = "chat"
    description = "Answer a message with a routed LLM, optionally using project context and prior conversation history."
    category = "chat"
    permissions = [Permission.READ, Permission.MODEL]
    cost_estimate = "model-tokens"
    input_schema = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "User message"},
            "history": {"type": "array", "items": {"type": "object", "properties": {"role": {"type": "string"}, "content": {"type": "string"}}}},
            "context": {"type": "string", "description": "Extra project context"},
            "system": {"type": "string", "description": "System instruction override"},
            "model": {"type": "string"},
            "temperature": {"type": "number"},
            "max_tokens": {"type": "integer"},
        },
        "required": ["message"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "text": {"type": "string"},
            "model": {"type": "string"},
            "tokens_in": {"type": "integer"},
            "tokens_out": {"type": "integer"},
        },
    }

    def availability(self, ctx: ToolContext | None = None) -> str:
        registry = getattr(ctx, "model_registry", None) if ctx else None
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry
        try:
            return "AVAILABLE" if registry.chat_available() else "UNAVAILABLE"
        except Exception:
            return "UNAVAILABLE"

    def unavailable_reason(self, ctx: ToolContext | None = None) -> str:
        return "No chat model is reachable (check LLM base URL / API key)."

    def execute(self, ctx: ToolContext, payload: dict[str, Any]) -> ToolResult:
        message = self.require(payload, "message")
        registry = getattr(ctx, "model_registry", None)
        if registry is None:
            from models.registry import registry as global_registry

            registry = global_registry

        model = payload.get("model") or registry.default_chat_model()
        system = payload.get("system") or _DEFAULT_SYSTEM

        messages: list[ChatMessage] = [ChatMessage("system", system)]
        # Inject live runtime facts about the selected model (best-effort; never fatal).
        runtime_facts = _runtime_model_facts(model, registry)
        if runtime_facts is not None:
            messages.append(ChatMessage("system", _render_runtime_context(runtime_facts)))
        if payload.get("context"):
            messages.append(ChatMessage("system", f"Project context:\n{payload['context']}"))
        for item in payload.get("history") or []:
            role = str(item.get("role", "user"))
            content = str(item.get("content", ""))
            if role in ("system", "user", "assistant") and content:
                messages.append(ChatMessage(role, content))
        messages.append(ChatMessage("user", message))

        opts: dict[str, Any] = {}
        if payload.get("temperature") is not None:
            opts["temperature"] = payload["temperature"]
        if payload.get("max_tokens") is not None:
            opts["max_tokens"] = payload["max_tokens"]

        try:
            completion = registry.complete(messages, model=model, **opts)
        except ModelUnavailableError as exc:
            return ToolResult(status="UNAVAILABLE", summary=exc.message, error=exc.message, error_class="ModelUnavailable")

        return ToolResult(
            status="SUCCESS",
            summary=completion.text[:280],
            data={
                "text": completion.text,
                "model": completion.model,
                "provider": completion.provider,
                "tokens_in": completion.tokens_in,
                "tokens_out": completion.tokens_out,
                "finish_reason": completion.finish_reason,
            },
        )

    def validate(self, ctx: ToolContext, result: ToolResult) -> ValidationReport:
        checks = [{"name": "status", "ok": result.status in ("SUCCESS", "UNAVAILABLE"), "detail": result.status}]
        if result.status == "SUCCESS":
            text = result.data.get("text", "")
            checks.append({"name": "non_empty", "ok": bool(text.strip()), "detail": f"{len(text)} chars"})
        return ValidationReport(valid=all(c["ok"] for c in checks), checks=checks, message="chat validation")
